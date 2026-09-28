"""Document jobs under the user's nonblocking actor (STATE_MACHINE, Document Job).

T04 collects one ordered submission. T05 runs recognition phases through
``RecognitionService`` within the job's single processing budget. T06 asks the
user to choose or describe a profile, compiles and previews an instruction, and
delivers the result. The intake layer owns files and parser children and the GPU
scheduler owns model calls; this flow owns dialogue states, generations, timers
and the charged budget. Every operation reports back as a generation-tagged
event, so Cancel is handled while it runs and a replaced pass's late result is
discarded. ``on_ready`` replaces recognition only in collection-level tests.
"""

import asyncio
from dataclasses import dataclass, field
import itertools
import logging
import secrets
import time
from uuid import uuid4

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tgbotdocs.storage import ProfileConflict, ProfileNotFound, StorageUnavailable

from .compiler import CompileError
from .delivery import BLOCKED, CANCELLED, COMPLETE, deliver
from .events import ButtonClick, Event
from .intake import IntakeError
from .pipeline import PhaseOutcome
from .profiles import PreviewExpired
from .rendering import RenderingError, render_result
from .settings import profile_text, split_preview
from .transport import SendSkipped, Upload


MESSAGES = {
    "busy": "Busy. Please try again later.",
    "temporarily_unavailable": "Temporarily unavailable. Please try again later.",
    "file_too_large": "This file exceeds the 20 MB download limit. Send a smaller original file.",
    "download_failed": "This file could not be downloaded. Please resend it.",
    "unsupported_format": "Unsupported file. Send a PNG, JPEG or PDF.",
    "damaged_input": "This file is damaged or cannot be decoded. Please resend the original.",
    "encrypted_pdf": "This PDF is password protected. Send an unprotected copy.",
    "pixel_limit": "This image exceeds the decoded pixel limit. Send a smaller image.",
    "storage_limit": "Temporary storage is unavailable or full. Please try again later.",
    "parser_timeout": "This file could not be prepared within the time limit.",
    "parser_failed": "This file could not be prepared safely. Please resend the original.",
    "processing_limit": "The complete document cannot be processed within the time limit on this machine. Nothing was truncated.",
}
TIME_LIMIT = "The document could not be processed within the time limit on this machine. No result was returned."
TECHNICAL = "The document could not be processed because of a technical error. Please resend it."
RUNTIME = "The local recognition service is temporarily unavailable. Please resend the document later."
FAILURES = {
    "processing_budget_exhausted": TIME_LIMIT,
    "runtime_timeout": TIME_LIMIT,
    "worker_timeout": TIME_LIMIT,
    "queue_wait_expired": "The document waited too long in the queue and expired. Please resend it later.",
    "profiles_unavailable": "Your profiles could not be read. Please resend the document later.",
    "profile_or_page_exceeds_context": "A page or the profile does not fit the local model's context. "
                                       "Send the pages separately or simplify the profile.",
    "recognition_contract_violation": TECHNICAL,
}
MATCHING = {
    "unreadable": "The document could not be read. Send a clearer image or the original file.",
    "mixed": "The pages seem to belong to different documents. Send each document separately.",
    "not_document": "This does not look like a document. Nothing was extracted.",
}
EVENTS = logging.getLogger("tgbotdocs.events")
WAITING = ("awaiting_choice", "awaiting_instruction", "awaiting_confirmation")
INSTRUCTION = "Describe the document type and exactly which fields or lists to extract."


def _failure(code):
    if code in FAILURES:
        return FAILURES[code]
    if code in MESSAGES:
        return MESSAGES[code]
    if code.startswith("runtime_"):
        return RUNTIME
    return TECHNICAL


def _label(text):
    return text if len(text) <= 48 else text[:47] + "…"


@dataclass(repr=False)
class DocumentJob:
    submission: object
    state: str = "collecting"
    pending: int = 0
    accepted: dict = field(default_factory=dict)
    tasks: set = field(default_factory=set)
    replay: list = field(default_factory=list)
    buttons: dict = field(default_factory=dict)
    last_arrival: float = 0.0
    activity_at: float | None = 0.0
    process_requested: bool = False
    delivery_started: bool = False
    album_groups: set = field(default_factory=set)
    late_album_quiet: bool = False
    used_s: float = 0.0
    ready: object = None
    cleanup: asyncio.Task | None = None
    restart: asyncio.Task | None = None
    # Recognition and dialogue after collection; RAM only, discarded at the end.
    phase: int = 0
    phase_started: bool = False
    snapshots: tuple = ()
    choices: tuple = ()
    selected: object = None
    instruction: str = ""
    current: tuple = ()
    preview: object = None
    deferred: object = None
    compressed: bool = False

    @property
    def generation(self):
        return self.submission.generation

    def reset_decisions(self):
        """A new pass matches the complete document again from the beginning."""
        self.phase_started, self.snapshots, self.choices, self.selected = False, (), (), None
        self.instruction, self.current, self.preview, self.deferred = "", (), None, None


class DocumentsFlow:
    def __init__(self, intake, transport, submit, config, *, recognition=None, store=None, compiler=None,
                 previews=None, on_ready=None, discard_drafts=None, alert=None, settings_waiting=None,
                 clock=time.monotonic):
        self.intake, self.transport, self.submit, self.config = intake, transport, submit, config
        self.recognition, self.store, self.compiler, self.previews = recognition, store, compiler, previews
        self.on_ready, self.clock = on_ready, clock
        if discard_drafts is None and previews is not None:
            discard_drafts = previews.discard_job
        self.discard_drafts, self.alert = discard_drafts, alert
        self.settings_waiting = settings_waiting or (lambda owner: False)
        self.jobs, self.remembered, self.tasks = {}, {}, set()
        self.nonce = secrets.token_hex(4)
        self.closing = False
        self._admissions = itertools.count()

    def active(self, owner):
        return owner in self.jobs

    def waiting(self, owner):
        """Whether the job waits for this user's input (Settings is then view-only)."""
        job = self.jobs.get(owner)
        if job is None:
            return False
        if job.state in WAITING:
            return job.deferred is None
        return job.state == "collecting" and job.submission.mode == "several" and not job.process_requested

    def status(self, owner):
        job = self.jobs.get(owner)
        if job is None:
            return "none"
        if job.deferred is not None:
            return "waiting until the profile draft is saved or cancelled"
        if job.state == "queued" and job.phase_started:
            return "processing"
        return {"collecting": "collecting pages", "restarting": "updating the album",
                "admission": "checking the complete document", "queued": "queued",
                "awaiting_choice": "waiting for your profile choice",
                "awaiting_instruction": "waiting for your instruction",
                "compiling": "preparing the profile preview",
                "awaiting_confirmation": "waiting for your preview confirmation",
                "saving": "saving the profiles", "delivering": "sending the result",
                "finishing": "cleaning up"}.get(job.state, job.state)

    def _task(self, operation, job=None):
        task = asyncio.create_task(operation)
        self.tasks.add(task)
        if job is not None:
            job.tasks.add(task)
        def done(task):
            self.tasks.discard(task)
            if job is not None:
                job.tasks.discard(task)
            if not task.cancelled():
                task.exception()
        task.add_done_callback(done)
        return task

    def _say(self, owner, text, *, job=None, actions=()):
        """Buttons stay valid for the job's current generation (STATE_MACHINE).

        Each token maps to a concrete action; a profile choice or preview decision
        is bound to that profile or preview, so an earlier message cannot act on a
        newer list. A new generation clears every token.
        """
        if self.closing:
            return
        markup = None
        if job is not None:
            rows = []
            for label, action in actions:
                token = f"j:{self.nonce}:{job.submission.job_id}:{job.generation:x}:{secrets.token_hex(4)}"
                job.buttons[token] = action
                rows.append([InlineKeyboardButton(text=_label(label), callback_data=token)])
            if rows:
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        generation = job.generation if job else None

        def current():
            return not self.closing and (job is None or (job.generation == generation and job.state != "finishing"))

        async def send():
            parts = split_preview(text)
            try:
                for index, part in enumerate(parts):
                    if not current():
                        return
                    await self.transport.send(owner, part, guard=current,
                                              reply_markup=markup if index == len(parts) - 1 else None)
            except SendSkipped:
                pass
        self._task(send())

    def _request(self, job, kind, factory):
        generation, submission = job.generation, job.submission
        async def work():
            try:
                value, code = await factory(), None
            except asyncio.CancelledError:
                return
            except IntakeError as error:
                value, code = None, error.code
            except StorageUnavailable:
                value, code = None, "storage"
            except (ProfileConflict, ProfileNotFound):
                value, code = None, "conflict"
            except PreviewExpired:
                value, code = None, "expired"
            except CompileError:
                value, code = None, "compiler"
            except Exception:
                value, code = None, "temporarily_unavailable"
            self.submit(Event("document_io", submission.owner, job_id=submission.job_id,
                              generation=generation, payload=(kind, value, code)))
        return self._task(work(), job)

    def _reserve(self, owner, mode, album_id=None):
        now = self.clock()
        try:
            submission = self.intake.reserve(owner, uuid4().hex, 1, next(self._admissions), mode=mode,
                                             album_id=album_id)
        except IntakeError as error:
            self._say(owner, MESSAGES.get(error.code, MESSAGES["temporarily_unavailable"]))
            return None
        job = DocumentJob(submission, last_arrival=now, activity_at=now)
        self.jobs[owner] = job
        return job

    def _receive(self, job, event):
        # A page accepted by collecting is activity even while it downloads.
        job.pending += 1
        job.last_arrival = job.activity_at = self.clock()
        if event.payload.media_group_id is not None:
            job.album_groups.add(event.payload.media_group_id)
        self._request(job, "receive", lambda: self.intake.receive(job.submission, event.payload,
            message_id=event.message_id, update_id=event.update_id))

    def _seal(self, job):
        if job.state != "collecting" or job.pending:
            return
        if not job.accepted:
            self._say(job.submission.owner, "No document is present. Send pages before Process.", job=job,
                      actions=(("Process", "process"), ("Cancel", "cancel")))
            job.process_requested = job.late_album_quiet = False
            return
        job.state = "admission"
        self._request(job, "seal", lambda: self.intake.seal(job.submission,
            remaining_budget_s=self.config.processing_s - job.used_s))

    def _finish(self, job, *, reason=None, code="cancelled"):
        if job.state == "finishing":
            return
        # Technical event only: fixed code, random job ID, page count and charged time.
        pages = len(job.ready.document.pages) if job.ready is not None and hasattr(job.ready, "document") else 0
        EVENTS.info("job_finished %s %s pages=%d charged_s=%.1f", job.submission.job_id, code, pages, job.used_s)
        if reason:
            self._say(job.submission.owner, reason)
        self.intake.cancel_now(job.submission)
        job.state, job.buttons, job.deferred = "finishing", {}, None
        for task in tuple(job.tasks):
            if not task.cancelling():
                task.cancel()
        if job.restart is not None and not job.restart.done():
            job.restart.cancel()
        if self.discard_drafts:
            self.discard_drafts(job.submission.owner, job.submission.job_id)
        job.preview = None
        async def clean():
            await asyncio.gather(*tuple(job.tasks), return_exceptions=True)
            await self.intake.close_submission(job.submission)
            self.submit(Event("document_terminal", job.submission.owner,
                job_id=job.submission.job_id, generation=job.generation))
        job.cleanup = self._task(clean())

    def cancel(self, owner):
        job = self.jobs.get(owner)
        if job is not None:
            self._finish(job)

    def finish(self, owner, *, reason=None):
        job = self.jobs.get(owner)
        if job is not None:
            self._finish(job, reason=reason)

    def mark_delivering(self, owner):
        job = self.jobs[owner]
        job.state, job.delivery_started = "delivering", True

    # Questions and the Settings overlap (ED-013): at most one flow waits for input.

    def _ask(self, job, question):
        owner = job.submission.owner
        if self.settings_waiting(owner):
            job.deferred, job.activity_at = question, None
            self._say(owner, "Your document is waiting for an answer. It continues after you save or cancel "
                             "the open profile draft.")
        else:
            job.deferred, job.activity_at = None, self.clock()
            question()

    def settings_closed(self, owner):
        job = self.jobs.get(owner)
        if job is None or job.deferred is None or job.state not in WAITING:
            return
        question, job.deferred = job.deferred, None
        job.activity_at = self.clock()
        question()

    def _choose(self, job, profiles, text):
        job.state, job.choices = "awaiting_choice", tuple(profiles)
        def question():
            actions = [(profile.name, ("choose", profile)) for profile in job.choices]
            actions += [("New instruction", "instruct"), ("Cancel", "cancel")]
            self._say(job.submission.owner, text, job=job, actions=actions)
        self._ask(job, question)

    def _instruct(self, job, text):
        job.state, job.choices = "awaiting_instruction", job.snapshots
        def question():
            actions = [(profile.name, ("choose", profile)) for profile in job.choices]
            self._say(job.submission.owner, text + ("\nOr choose one of your profiles." if actions else ""),
                      job=job, actions=(*actions, ("Cancel", "cancel")))
        self._ask(job, question)

    def _confirm(self, job, prefix=""):
        job.state = "awaiting_confirmation"
        def question():
            nonce = job.preview.nonce
            # The draft's lifetime starts when the user sees it, also after a deferral.
            try:
                self.previews.get(job.submission.owner, nonce)
            except PreviewExpired:
                job.preview, job.current = None, ()
                self._instruct(job, "The profile preview expired. " + INSTRUCTION)
                return
            self._say(job.submission.owner, prefix + "Review every profile before saving. Saved profiles are "
                      "also used for later documents.\n\n" + "\n\n".join(profile_text(p) for p in job.preview.drafts),
                      job=job, actions=(("Save all", ("save", nonce)), ("Edit", ("edit", nonce)),
                                        ("Cancel draft", ("discard", nonce))))
        self._ask(job, question)

    def _discard_preview(self, job):
        if job.preview is not None and self.discard_drafts:
            self.discard_drafts(job.submission.owner, job.submission.job_id)
        job.preview = None

    # Recognition phases (T05) and delivery.

    def _remaining(self, job):
        return self.config.processing_s - job.used_s

    def _ready(self, job, ready):
        job.state, job.ready = "queued", ready
        job.compressed = any(getattr(item, "compressed", False) for item in ready.files)
        if self.on_ready is not None:
            self._task(self.on_ready(job, ready), job)
            return
        self._recognize(job)

    def _recognize(self, job):
        remaining = self._remaining(job)
        if remaining <= 0:
            self._finish(job, reason=TIME_LIMIT, code="processing_budget_exhausted")
            return
        job.phase += 1
        job.state, job.phase_started, job.activity_at = "queued", False, self.clock()
        owner, generation, ready, selected = job.submission.owner, job.generation, job.ready, job.selected
        key = f"{job.submission.job_id}:{generation}:{job.phase}"

        def charge(seconds):
            # A replaced or cancelled pass stays charged (STATE_MACHINE late fragments).
            job.used_s += seconds

        def started():
            if job.generation == generation:
                job.phase_started = True

        async def work():
            snapshots = (selected,)
            if selected is None:
                # The job's immutable snapshot, taken before matching (DATA_MODEL).
                try:
                    snapshots = tuple(await self.store.list_profiles(owner))
                except Exception:
                    return PhaseOutcome(error="profiles_unavailable"), ()
            outcome = await self.recognition.run(
                key=key, admission_order=job.submission.admission_order, files=ready.paths,
                pages=ready.document.pages, scratch=job.submission.path, snapshots=snapshots,
                remaining_s=remaining, charge=charge, selected_profile=selected, started=started)
            return outcome, snapshots
        self._request(job, "recognized", work)

    def _recognized(self, job, outcome, snapshots):
        if job.selected is None:
            job.snapshots = snapshots
        if outcome.error:
            self._finish(job, reason=_failure(outcome.error), code=outcome.error)
            return
        result = outcome.result
        status = result.matching.status
        if status == "matched" and result.profile is not None and result.recognition is not None:
            self._deliver(job, result.profile, result.recognition, result.user_selected)
        elif status == "uncertain" and job.snapshots:
            self._choose(job, job.snapshots, "The document type or the matching profile is unclear. "
                         "Choose the profile for this document, or send a new instruction.")
        elif status in ("uncertain", "no_profile"):
            self._instruct(job, "None of your profiles matches this document. " + INSTRUCTION)
        elif status in MATCHING:
            reason = MATCHING[status]
            if status == "unreadable" and job.compressed:
                reason += " A photo is recompressed by Telegram; sending the image as a file keeps its quality."
            self._finish(job, reason=reason, code=status)
        else:
            self._finish(job, reason=TECHNICAL, code="unexpected_matching_status")

    def _compile(self, job, text):
        remaining = self._remaining(job)
        if remaining <= 0:
            self._finish(job, reason=TIME_LIMIT, code="processing_budget_exhausted")
            return
        # Clarification answers extend the instruction; they never replace earlier requests.
        job.instruction = job.instruction + "\n" + text if job.instruction else text
        job.state, job.activity_at = "compiling", self.clock()
        owner, instruction, current = job.submission.owner, job.instruction, job.current

        def charged(seconds):
            job.used_s += seconds

        self._request(job, "compiled", lambda: self.compiler.compile(
            owner, instruction, current=current, remaining_budget_s=remaining, charged=charged))

    def _compiled(self, job, result, code):
        if code:
            if self._remaining(job) <= 0:
                self._finish(job, reason=TIME_LIMIT, code="processing_budget_exhausted")
            else:
                self._instruct(job, "The instruction could not be compiled. Please simplify it and try again.")
            return
        if result.questions:
            self._instruct(job, "\n".join(result.questions))
            return
        try:
            job.preview = self.previews.stage(job.submission.owner, result, job_id=job.submission.job_id)
        except ValueError:
            self._instruct(job, "The instruction could not be compiled. Please simplify it and try again.")
            return
        self._confirm(job)

    def _save(self, job):
        owner, nonce = job.submission.owner, job.preview.nonce
        job.state, job.activity_at = "saving", self.clock()
        self._request(job, "saved", lambda: self.previews.confirm(owner, nonce))

    def _saved(self, job, profiles, code):
        owner = job.submission.owner
        if code == "storage":
            self._confirm(job, "Storage is temporarily unavailable. Nothing is reported saved; retry this "
                               "preview.\n\n")
            return
        self._discard_preview(job)
        job.instruction, job.current = "", ()
        if code:
            self._instruct(job, "The preview could not be saved. " + INSTRUCTION)
        elif len(profiles) == 1:
            job.selected = profiles[0]
            self._say(owner, "Profile saved. The document continues with it.")
            self._recognize(job)
        else:
            self._choose(job, profiles, "Profiles saved. Choose the profile for this document.")

    def _deliver(self, job, profile, recognition, user_selected):
        note = "Profile: " + _label(profile.name) + (" (chosen by you)" if user_selected else "")
        try:
            parts = render_result(profile, recognition, compressed=job.compressed, note=note)
        except RenderingError:
            self._finish(job, reason="A value is longer than one Telegram message, so the result could not be "
                                     "sent. Nothing was truncated.", code="result_too_long")
            return
        job.state, job.delivery_started = "delivering", True
        owner, generation = job.submission.owner, job.generation

        def current():
            return not self.closing and job.generation == generation and job.state == "delivering"

        self._request(job, "delivered", lambda: deliver(
            self.transport, owner, parts, window_s=getattr(self.config, "delivery_s", 60.0),
            attempts=getattr(self.config, "delivery_attempts", 3), current=current))

    def _delivered(self, job, outcome):
        if outcome in (COMPLETE, BLOCKED, CANCELLED):
            self._finish(job, code="delivered_" + outcome)
            return
        if self.alert is not None:
            self.alert("delivery_failed", job.submission.job_id)
        self._finish(job, reason="The result could not be delivered completely. Please resend the document.",
                     code="delivered_" + outcome)

    def _restart_album(self, job, event):
        job.replay.append(event)
        if job.state == "restarting":
            return
        self.intake.cancel_now(job.submission)
        job.state, job.buttons, job.pending, job.ready = "restarting", {}, 0, None
        job.late_album_quiet = True
        previous = tuple(job.tasks)
        for task in previous:
            if not task.cancelling():
                task.cancel()
        if self.discard_drafts:
            self.discard_drafts(job.submission.owner, job.submission.job_id)
        job.reset_decisions()
        generation = job.generation
        async def drain():
            await asyncio.gather(*previous, return_exceptions=True)
            await self.intake.drain(job.submission)
            self.submit(Event("document_recollected", job.submission.owner,
                job_id=job.submission.job_id, generation=generation))
        job.restart = self._task(drain())
        self._say(job.submission.owner, "A late album page arrived. The earlier pass was stopped; the complete album will be checked again.")

    def _internal(self, job, event):
        if job is None or (event.job_id, event.generation) != (job.submission.job_id, job.generation):
            return
        if event.kind == "document_terminal":
            for album in job.album_groups:
                self.remembered[(event.owner, album)] = (self.clock(), job.delivery_started)
            self.jobs.pop(event.owner)
        elif event.kind == "document_recollected" and job.state == "restarting":
            job.state, job.restart = "collecting", None
            queued, job.replay = job.replay, []
            for item in queued:
                self._receive(job, item)
        elif event.kind == "document_io" and job.state != "finishing":
            kind, value, code = event.payload
            if kind == "receive":
                self._received(job, event, value, code)
            elif kind == "seal":
                if code:
                    self._finish(job, reason=MESSAGES.get(code, MESSAGES["temporarily_unavailable"]), code=code)
                else:
                    self._ready(job, value)
            elif kind == "recognized" and job.state == "queued":
                if code:
                    self._finish(job, reason=TECHNICAL, code=code)
                else:
                    self._recognized(job, *value)
            elif kind == "compiled" and job.state == "compiling":
                self._compiled(job, value, code)
            elif kind == "saved" and job.state == "saving":
                self._saved(job, value, code)
            elif kind == "delivered" and job.state == "delivering":
                self._delivered(job, value if not code else "uncertain")

    def _received(self, job, event, value, code):
        job.pending -= 1
        if code:
            reason = MESSAGES.get(code, MESSAGES["temporarily_unavailable"])
            if job.submission.mode == "several" and code != "storage_limit":
                self._say(event.owner, reason + " Other accepted pages are still collected.")
            else:
                self._finish(job, reason=reason, code=code)
                return
        else:
            job.accepted[value.file_key] = value
            job.activity_at = self.clock()
            if job.submission.mode == "several" and not job.process_requested:
                page_count = sum(len(item.pages) for item in job.accepted.values())
                self._say(event.owner, f"Collected {len(job.accepted)} files and {page_count} pages. Send more or choose Process.",
                          job=job, actions=(("Process", "process"), ("Cancel", "cancel")))
        if job.submission.mode == "single" or (job.process_requested and not job.late_album_quiet):
            self._seal(job)
        elif (job.submission.mode == "album" or job.late_album_quiet) and self.clock() - job.last_arrival >= self.config.album_quiet_s:
            self._seal(job)

    def _tick(self, job, owner):
        now = self.clock()
        self.remembered = {key: value for key, value in self.remembered.items()
                           if now - value[0] < self.config.inactivity_s}
        if job is None:
            return
        if job.state in ("collecting", "restarting"):
            elapsed = now - (job.submission.admission_time if job.submission.mode == "album" else job.activity_at)
            if elapsed >= self.config.inactivity_s:
                self._finish(job, reason="The document collection expired. Please resend it.", code="expired")
            elif (job.submission.mode == "album" or job.late_album_quiet) and now - job.last_arrival >= self.config.album_quiet_s:
                self._seal(job)
        elif job.state in WAITING and job.deferred is None and job.activity_at is not None and (
                now - job.activity_at >= self.config.inactivity_s):
            self._finish(job, reason="The document waited too long for your answer and expired. Please resend it.",
                         code="expired")

    def _button(self, job, event):
        action = job.buttons.get(event.payload.data) if job else None
        deferred = action is not None and action != "cancel" and job.deferred is not None
        self._task(self.transport.answer_callback(event.payload.query_id, "Session expired" if action is None
            else "Save or cancel the open profile draft first." if deferred else ""))
        if action is None or deferred:
            return
        name, argument = action if isinstance(action, tuple) else (action, None)
        preview = job.preview is not None and argument == job.preview.nonce
        if name == "cancel":
            self._finish(job, reason="Cancelled. Cleanup is running.")
        elif name == "process" and job.state == "collecting":
            job.activity_at, job.process_requested = self.clock(), True
            if job.pending:
                self._say(event.owner, "Waiting for all accepted file downloads before Process.")
            else:
                self._seal(job)
        elif name == "choose" and job.state in ("awaiting_choice", "awaiting_instruction"):
            # A manual choice pins that snapshot and is marked user-selected.
            job.selected = argument
            job.instruction, job.current = "", ()
            self._recognize(job)
        elif name == "instruct" and job.state == "awaiting_choice":
            self._instruct(job, INSTRUCTION)
        elif name == "save" and job.state == "awaiting_confirmation" and preview:
            self._save(job)
        elif name == "edit" and job.state == "awaiting_confirmation" and preview:
            job.current = job.preview.drafts
            self._discard_preview(job)
            self._instruct(job, "Describe the changes to this preview. Unchanged requested fields will be kept.")
        elif name == "discard" and job.state == "awaiting_confirmation" and preview:
            self._discard_preview(job)
            job.instruction, job.current = "", ()
            self._instruct(job, "Draft cancelled. Saved profiles were not changed. " + INSTRUCTION)

    def _text(self, job, event):
        if job.deferred is not None:
            return False
        if job.state == "awaiting_instruction":
            text = str(event.payload).strip()
            if text:
                self._compile(job, text)
            else:
                self._say(event.owner, "Send a nonempty instruction, or Cancel.")
        elif self.waiting(event.owner) and job.state == "collecting":
            self._say(event.owner, "Send pages or choose Process.")
        elif job.state in ("awaiting_choice", "awaiting_confirmation"):
            self._say(event.owner, "Choose one of the buttons above, or Cancel.")
        else:
            self._say(event.owner, "A document is active. Wait or Cancel and resend.")
        return True

    async def handle(self, event):
        job = self.jobs.get(event.owner)
        if event.kind.startswith("document_"):
            self._internal(job, event)
            return True
        if self.closing:
            return False
        if event.kind == "tick":
            self._tick(job, event.owner)
            return True
        if event.kind == "callback" and isinstance(event.payload, ButtonClick):
            if not event.payload.data.startswith("j:"):
                return False
            self._button(job, event)
            return True
        if event.kind == "text" and event.payload == "Several pages":
            if job:
                self._say(event.owner, "A document is active. Wait or Cancel and resend.")
            else:
                job = self._reserve(event.owner, "several")
                if job:
                    self._say(event.owner, "Send all pages as photos or PNG, JPEG and PDF files, then choose Process.",
                              job=job, actions=(("Process", "process"), ("Cancel", "cancel")))
            return True
        if event.kind == "text" and event.payload == "Process" and job and job.submission.mode == "several":
            if job.state == "collecting":
                job.activity_at, job.process_requested = self.clock(), True
                if job.pending:
                    self._say(event.owner, "Waiting for all accepted file downloads before Process.")
                else:
                    self._seal(job)
            return True
        if event.kind != "file" or not isinstance(event.payload, Upload):
            if event.kind == "text" and job:
                return self._text(job, event)
            return False
        album = event.payload.media_group_id
        if album is not None and (event.owner, album) in self.remembered:
            delivered = self.remembered[(event.owner, album)][1]
            self._say(event.owner, "The result was for an incomplete album. Resend the complete set using Several pages."
                      if delivered else "That album is closed. Resend the complete set using Several pages.")
            return True
        if job is None:
            job = self._reserve(event.owner, "album" if album is not None else "single", album)
            if job is None:
                self._close_album(event.owner, album)
                return True
        elif album is not None and album in job.album_groups:
            if job.delivery_started:
                self._say(event.owner, "The result was for an incomplete album. Resend the complete set using Several pages.")
                return True
            if job.state != "collecting":
                if job.state != "finishing":
                    self._restart_album(job, event)
                return True
            if job.submission.mode == "several" and job.process_requested:
                job.late_album_quiet = True
            self._receive(job, event)
            return True
        elif job.submission.mode != "several" or job.state != "collecting" or job.process_requested:
            self._say(event.owner, "A document is active. Wait or Cancel and resend.")
            self._close_album(event.owner, album)
            return True
        self._receive(job, event)
        return True

    def _close_album(self, owner, album):
        """A refused album part closes its group: the rest never form a partial set."""
        if album is not None:
            self.remembered[(owner, album)] = (self.clock(), False)

    async def close(self):
        self.closing = True
        for owner in tuple(self.jobs):
            self.cancel(owner)
        cleanups = {job.cleanup for job in self.jobs.values() if job.cleanup is not None}
        for task in tuple(self.tasks):
            if task not in cleanups:
                task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await self.intake.close()
        self.jobs.clear()
