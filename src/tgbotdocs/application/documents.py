"""Ordered document collection under the user's nonblocking actor.

The intake layer owns files and child processes; this flow owns dialogue states,
generations and timers. Recognition is attached through ``on_ready`` in T05.
"""

import asyncio
from dataclasses import dataclass, field
import itertools
import secrets
import time
from uuid import uuid4

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .events import ButtonClick, Event
from .intake import IntakeError
from .transport import Upload


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
    activity_at: float = 0.0
    process_requested: bool = False
    delivery_started: bool = False
    album_groups: set = field(default_factory=set)
    late_album_quiet: bool = False
    used_s: float = 0.0
    ready: object = None
    cleanup: asyncio.Task | None = None
    restart: asyncio.Task | None = None

    @property
    def generation(self):
        return self.submission.generation


class DocumentsFlow:
    def __init__(self, intake, transport, submit, config, *, on_ready=None,
                 discard_drafts=None, clock=time.monotonic):
        self.intake, self.transport, self.submit, self.config = intake, transport, submit, config
        self.on_ready, self.discard_drafts, self.clock = on_ready, discard_drafts, clock
        self.jobs, self.remembered, self.tasks = {}, {}, set()
        self.nonce = secrets.token_hex(4)
        self.closing = False
        self._admissions = itertools.count()

    def active(self, owner):
        return owner in self.jobs

    def waiting(self, owner):
        job = self.jobs.get(owner)
        return job is not None and job.state == "collecting" and job.submission.mode == "several" and (
            not job.process_requested)

    def status(self, owner):
        job = self.jobs.get(owner)
        return {"collecting": "collecting pages", "restarting": "updating the album",
                "admission": "checking the complete document", "queued": "queued",
                "finishing": "cleaning up"}.get(job.state, job.state) if job else "none"

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
        """Buttons stay valid for the job's current generation (STATE_MACHINE)."""
        if self.closing:
            return
        markup = None
        if job is not None:
            rows = []
            for label, action in actions:
                token = f"j:{self.nonce}:{job.submission.job_id}:{job.generation:x}:{secrets.token_hex(4)}"
                job.buttons[token] = action
                rows.append([InlineKeyboardButton(text=label, callback_data=token)])
            if rows:
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        generation = job.generation if job else None
        async def send():
            if job and (job.generation != generation or job.state == "finishing"):
                return
            await self.transport.send(owner, text, reply_markup=markup)
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

    def _finish(self, job, *, reason=None):
        if job.state == "finishing":
            return
        if reason:
            self._say(job.submission.owner, reason)
        self.intake.cancel_now(job.submission)
        job.state, job.buttons = "finishing", {}
        for task in tuple(job.tasks):
            if not task.cancelling():
                task.cancel()
        if job.restart is not None and not job.restart.done():
            job.restart.cancel()
        if self.discard_drafts:
            self.discard_drafts(job.submission.owner, job.submission.job_id)
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

    def settings_closed(self, owner):
        # Document questions are attached by the recognition/dialogue bridge.
        return None

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
        generation = job.generation
        async def drain():
            await asyncio.gather(*previous, return_exceptions=True)
            await self.intake.drain(job.submission)
            self.submit(Event("document_recollected", job.submission.owner,
                job_id=job.submission.job_id, generation=generation))
        job.restart = self._task(drain())
        self._say(job.submission.owner, "A late album page arrived. The earlier pass was stopped; the complete album will be checked again.")

    async def handle(self, event):
        job = self.jobs.get(event.owner)
        if event.kind.startswith("document_"):
            if job is None or (event.job_id, event.generation) != (job.submission.job_id, job.generation):
                return True
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
                    job.pending -= 1
                    if code:
                        reason = MESSAGES.get(code, MESSAGES["temporarily_unavailable"])
                        if job.submission.mode == "several" and code != "storage_limit":
                            self._say(event.owner, reason + " Other accepted pages are still collected.")
                        else:
                            self._finish(job, reason=reason)
                            return True
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
                elif kind == "seal":
                    if code:
                        self._finish(job, reason=MESSAGES.get(code, MESSAGES["temporarily_unavailable"]))
                    else:
                        job.state, job.ready = "queued", value
                        if self.on_ready:
                            self._task(self.on_ready(job, value), job)
            return True
        if self.closing:
            return False
        if event.kind == "tick":
            now = self.clock()
            self.remembered = {key: value for key, value in self.remembered.items()
                               if now - value[0] < self.config.inactivity_s}
            if job and job.state in ("collecting", "restarting"):
                elapsed = now - (job.submission.admission_time if job.submission.mode == "album" else job.activity_at)
                if elapsed >= self.config.inactivity_s:
                    self._finish(job, reason="The document collection expired. Please resend it.")
                elif (job.submission.mode == "album" or job.late_album_quiet) and now - job.last_arrival >= self.config.album_quiet_s:
                    self._seal(job)
            return True
        if event.kind == "callback" and isinstance(event.payload, ButtonClick):
            if not event.payload.data.startswith("j:"):
                return False
            action = job.buttons.get(event.payload.data) if job else None
            self._task(self.transport.answer_callback(event.payload.query_id, "" if action else "Session expired"))
            if action == "cancel":
                self._finish(job)
            elif action == "process" and job.state == "collecting":
                job.activity_at, job.process_requested = self.clock(), True
                if job.pending:
                    self._say(event.owner, "Waiting for all accepted file downloads before Process.")
                else:
                    self._seal(job)
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
                self._say(event.owner, "Send pages or choose Process." if self.waiting(event.owner)
                          else "A document is active. Wait or Cancel and resend.")
                return True
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
