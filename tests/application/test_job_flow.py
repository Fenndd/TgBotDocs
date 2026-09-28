"""T06 job dialogue through the real product actor, with controlled substitutes.

Telegram, intake, recognition, compiler and storage are fakes; the actors, the
document state machine, previews, rendering and delivery are the product code.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from tgbotdocs.application.compiler import CompileError, CompileResult
from tgbotdocs.application.documents import DocumentsFlow
from tgbotdocs.application.events import ButtonClick, Event
from tgbotdocs.application.intake import IntakeError
from tgbotdocs.application.pipeline import PhaseOutcome
from tgbotdocs.application.product import ProductApplication
from tgbotdocs.application.profiles import PreviewService
from tgbotdocs.application.transport import OrderedTransport, Upload
from tgbotdocs.recognition.contracts import (ExtractionProfile, FieldResult, ListField, ListResult, ListRow,
                                             MatchingResponse, RecognitionResult, ScalarField)
from tgbotdocs.recognition.core import CoreResult
from tgbotdocs.storage import StorageUnavailable

PASSWORD = "synthetic-password-123"
METHOD = SendMessage(chat_id=1, text="x")


def profile(owner, name="Card", field="identifier"):
    return ExtractionProfile(id=str(uuid4()), owner=str(owner), version=1, name=name,
                             description="Fictional " + name, original_instruction="Read " + field,
                             fields=(ScalarField(id=field, label=field.title(), description="Printed value",
                                                 type="text"),))


def recognized(p, value="SYN-1", *, user_selected=False, status="extracted"):
    field = FieldResult(field_id=p.fields[0].id, status=status, raw_value=value if status == "extracted" else None,
                        source_pages=(1,) if status == "extracted" else ())
    outcome = "complete" if status in ("extracted",) else "failed"
    matching = MatchingResponse(status="matched", profile_index=1)
    return PhaseOutcome(result=CoreResult(matching, p, RecognitionResult(fields=(field,), lists=(), outcome=outcome),
                                          user_selected))


def matching(status, description=None):
    response = MatchingResponse(status=status, type_description=description)
    return PhaseOutcome(result=CoreResult(response, None, None, False))


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Transport:
    def __init__(self):
        self.sent, self.answers, self.deleted, self.failures = [], [], [], []
        self.gate = None

    async def send(self, owner, text, **kwargs):
        if self.gate is not None and "Result" in text:
            await self.gate.wait()
        if self.failures and "Result" in text or self.failures and text.startswith("Part"):
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        self.sent.append((owner, text, kwargs))

    async def delete(self, owner, identifier):
        self.deleted.append((owner, identifier))
        return True

    async def answer_callback(self, query_id, text):
        self.answers.append((query_id, text))


class Store:
    def __init__(self):
        self.rows, self.unavailable, self.save_failures = {}, False, 0

    async def list_profiles(self, owner):
        if self.unavailable:
            raise StorageUnavailable("unavailable")
        return tuple(p for p in self.rows.values() if p.owner == str(owner))

    async def save_drafts(self, owner, drafts):
        if self.save_failures:
            self.save_failures -= 1
            raise StorageUnavailable("unavailable")
        self.rows.update((p.id, p) for p in drafts)
        return drafts


class Compiler:
    def __init__(self):
        self.calls, self.results = [], []

    async def compile(self, owner, instruction, *, current=(), remaining_budget_s=300, charged=None, **kwargs):
        self.calls.append((instruction, current, remaining_budget_s))
        if charged is not None:
            charged(5.0)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result(owner, instruction, current)
        return result


class Recognition:
    def __init__(self):
        self.calls, self.results, self.gate = [], [], None
        self.ignore_cancel = False

    async def run(self, *, key, admission_order, files, pages, scratch, snapshots, remaining_s, charge,
                  selected_profile=None, started=None):
        self.calls.append(SimpleNamespace(key=key, order=admission_order, snapshots=snapshots,
                                          remaining=remaining_s, selected=selected_profile))
        if started:
            started()
        try:
            if self.gate is not None:
                try:
                    await self.gate.wait()
                except asyncio.CancelledError:
                    # Models a late model response that arrives after cancellation.
                    if not self.ignore_cancel:
                        raise
                    await self.gate.wait()
            result = self.results.pop(0)
            return result(snapshots) if callable(result) else result
        finally:
            charge(10.0)


class Intake:
    def __init__(self):
        self.submissions, self.cleaned, self.downloads = {}, [], []

    def reserve(self, owner, job_id, generation, admission_order, *, mode, album_id=None):
        if any(s.owner == owner for s in self.submissions.values()):
            raise IntakeError("active_document")
        result = SimpleNamespace(owner=owner, job_id=job_id, generation=generation, admission_order=admission_order,
                                 admission_time=0.0, mode=mode, album_id=album_id, files=[], path=Path("job"))
        self.submissions[job_id] = result
        return result

    async def receive(self, submission, upload, *, message_id, update_id):
        self.downloads.append(upload.file_id)
        item = SimpleNamespace(file_key=upload.file_id, message_id=message_id, compressed=upload.compressed,
                               path=Path(upload.file_id), pages=(object(),))
        submission.files.append(item)
        return item

    async def seal(self, submission, *, remaining_budget_s=None):
        files = tuple(sorted(submission.files, key=lambda f: f.message_id))
        pages = tuple(SimpleNamespace(kind="png", width=10, height=10) for _ in files)
        return SimpleNamespace(files=files, generation=submission.generation, estimate_s=10,
                               paths=tuple(f.path for f in files), document=SimpleNamespace(pages=pages))

    def cancel_now(self, submission):
        submission.generation += 1

    async def drain(self, submission):
        pass

    async def close_submission(self, submission):
        self.cancel_now(submission)
        self.cleaned.append(submission.job_id)
        self.submissions.pop(submission.job_id, None)

    async def close(self):
        pass


class Harness:
    def __init__(self, **config):
        self.clock, self.transport, self.store = Clock(), Transport(), Store()
        self.compiler, self.recognition, self.intake = Compiler(), Recognition(), Intake()
        values = dict(password=PASSWORD, inactivity_s=900, processing_s=1800, album_quiet_s=2, delivery_s=60,
                      delivery_attempts=3, operator_ids=(999,))
        values.update(config)
        self.config = SimpleNamespace(**values)
        self.previews = PreviewService(self.store, ttl_s=900, clock=self.clock)
        self.flow = None
        self.app = ProductApplication(self.config, OrderedTransport(self.transport), self.store, self.compiler,
                                      clock=self.clock)
        self.flow = DocumentsFlow(self.intake, OrderedTransport(self.transport), self.app.submit, self.config,
                                  recognition=self.recognition, store=self.store, compiler=self.compiler,
                                  previews=self.previews, clock=self.clock)
        self.app.documents = self.flow
        self.flow.settings_waiting, self.flow.alert = self.app.settings.waiting, self.app.alert

    async def settle(self):
        async with asyncio.timeout(5):
            while True:
                for actor in tuple(self.app.actors.values()):
                    await actor.mailbox.join()
                await asyncio.sleep(0.001)
                busy = [t for t in (*self.app.tasks, *self.flow.tasks, *self.app.settings.tasks) if not t.done()]
                if not busy and all(a.mailbox.empty() for a in self.app.actors.values()):
                    return

    async def until(self, predicate):
        async with asyncio.timeout(5):
            while not predicate():
                for actor in tuple(self.app.actors.values()):
                    await actor.mailbox.join()
                await asyncio.sleep(0.001)

    async def sign_in(self, owner=1):
        self.app.submit(Event("text", owner, payload="/start"))
        self.app.submit(Event("text", owner, payload=PASSWORD, message_id=1))
        await self.settle()

    async def text(self, value, owner=1):
        self.app.submit(Event("text", owner, payload=value))
        await self.settle()

    async def file(self, name, owner=1, *, message_id=10, compressed=False, album=None):
        self.app.submit(Event("file", owner, update_id=message_id, message_id=message_id,
                              payload=Upload(name, 1, compressed, album)))
        await self.settle()

    def buttons(self, owner=1):
        job = self.flow.jobs.get(owner)
        return {} if job is None else job.buttons

    async def click(self, label_or_action, owner=1, query="q"):
        for token, action in self.buttons(owner).items():
            name = action[0] if isinstance(action, tuple) else action
            target = action[1].name if isinstance(action, tuple) and name == "choose" else name
            if label_or_action in (name, target):
                chosen = token
        self.app.submit(Event("callback", owner, payload=ButtonClick(chosen, query)))
        await self.settle()

    def texts(self, owner=1):
        return [text for who, text, _ in self.transport.sent if who == owner]

    def results(self, owner=1):
        return [(text, kwargs) for who, text, kwargs in self.transport.sent if who == owner and "Result:" in text]

    async def close(self):
        await self.app.close()


async def test_matched_document_is_delivered_with_code_entities_and_cleaned_up():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.recognition.results.append(recognized(card, "https://example.invalid/@x"))
        await h.file("photo", compressed=True)
        (text, kwargs), = h.results()
        entity = kwargs["entities"][0]
        assert entity.type == "code" and "https://example.invalid/@x" in text and "Profile: Card" in text
        assert "(chosen by you)" not in text
        call = h.recognition.calls[0]
        assert call.snapshots == (card,) and call.selected is None and call.remaining == 1800
        assert not h.flow.jobs and h.intake.cleaned
    finally:
        await h.close()


async def test_uncertain_choice_continues_budget_and_marks_user_selection():
    h = Harness()
    try:
        first, second = profile(1, "Invoice"), profile(1, "Receipt")
        h.store.rows.update({first.id: first, second.id: second})
        await h.sign_in()
        h.recognition.results.append(matching("uncertain"))
        await h.file("scan")
        job = h.flow.jobs[1]
        assert job.state == "awaiting_choice" and h.flow.waiting(1)
        # A profile saved meanwhile does not change the job's snapshot.
        late = profile(1, "Late")
        h.store.rows[late.id] = late
        assert {a[1].name for a in job.buttons.values() if isinstance(a, tuple)} == {"Invoice", "Receipt"}
        h.recognition.results.append(recognized(second, user_selected=True))
        await h.click("Receipt")
        call = h.recognition.calls[-1]
        assert call.selected == second and call.snapshots == (second,) and call.remaining == 1790
        (text, _), = h.results()
        assert "Profile: Receipt (chosen by you)" in text and not h.flow.jobs
    finally:
        await h.close()


async def test_no_profile_instruction_questions_preview_save_and_choice_among_new_profiles():
    h = Harness()
    try:
        await h.sign_in()
        h.recognition.results.append(matching("no_profile", "anything"))
        await h.file("scan")
        assert h.flow.jobs[1].state == "awaiting_instruction"
        assert "anything" not in "".join(h.texts())  # model text is never shown
        h.compiler.results.append(CompileResult(questions=("Which date format?",)))
        await h.text("Read invoices and receipts")
        assert h.flow.jobs[1].state == "awaiting_instruction" and "Which date format?" in h.texts()[-1]
        drafts = (profile(1, "Invoice", "number"), profile(1, "Receipt", "total"))
        h.compiler.results.append(CompileResult(drafts=drafts))
        await h.text("ISO dates")
        assert h.compiler.calls[-1][0] == "Read invoices and receipts\nISO dates"
        assert h.compiler.calls[-1][2] == 1800 - 10 - 5
        job = h.flow.jobs[1]
        assert job.state == "awaiting_confirmation" and not h.store.rows and not h.flow.waiting(2)
        assert "Invoice" in h.texts()[-1] and "Receipt" in h.texts()[-1]
        h.store.save_failures = 1
        await h.click("save")
        assert job.state == "awaiting_confirmation" and "Nothing is reported saved" in h.texts()[-1]
        await h.click("save")
        assert len(h.store.rows) == 2 and job.state == "awaiting_choice"
        h.recognition.results.append(recognized(drafts[1], user_selected=True))
        await h.click("Receipt")
        assert h.recognition.calls[-1].selected == drafts[1]
        assert "Profile: Receipt (chosen by you)" in h.results()[0][0]
        assert job.used_s == 10 + 5 + 5 + 10
    finally:
        await h.close()


async def test_single_saved_profile_applies_directly_and_stale_preview_buttons_do_nothing():
    h = Harness()
    try:
        await h.sign_in()
        h.recognition.results.append(matching("no_profile", "x"))
        await h.file("scan")
        draft = profile(1, "Card")
        h.compiler.results.append(CompileResult(drafts=(draft,)))
        await h.text("Read the card number")
        job = h.flow.jobs[1]
        old = next(t for t, a in job.buttons.items() if isinstance(a, tuple) and a[0] == "save")
        edited = draft.model_copy(update={"name": "Edited card"})
        h.compiler.results.append(CompileResult(drafts=(edited,)))
        await h.click("edit")
        assert job.state == "awaiting_instruction" and job.current == (draft,)
        await h.text("Call it Edited card")
        assert h.compiler.calls[-1][1] == (draft,) and job.state == "awaiting_confirmation"
        h.app.submit(Event("callback", 1, payload=ButtonClick(old, "stale")))
        await h.settle()
        assert job.state == "awaiting_confirmation" and not h.store.rows
        h.recognition.results.append(recognized(edited, user_selected=True))
        await h.click("save")
        assert list(h.store.rows.values()) == [edited]
        assert h.recognition.calls[-1].selected == edited and not h.flow.jobs
        assert any("Profile saved" in text for text in h.texts())
    finally:
        await h.close()


async def test_job_question_is_deferred_while_a_settings_draft_is_open():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        await h.text("Settings")
        create = next(t for t, (a, _) in h.app.settings.session(1).buttons.items() if a == "create")
        h.app.submit(Event("callback", 1, payload=ButtonClick(create, "c")))
        await h.settle()
        assert h.app.settings.waiting(1)
        h.recognition.results.append(matching("uncertain"))
        await h.file("scan")
        job = h.flow.jobs[1]
        assert job.state == "awaiting_choice" and job.deferred is not None and not h.flow.waiting(1)
        assert "continues after you save or cancel" in h.texts()[-1]
        # A Settings instruction still goes to Settings, not to the job.
        h.clock.now = 850
        h.compiler.results.append(CompileResult(drafts=(profile(1, "Other"),)))
        await h.text("Read another ID")
        assert h.app.settings.session(1).state == "preview"
        # The deferred job has no inactivity timer while the draft stays open.
        h.clock.now = 1700
        h.app.tick()
        await h.settle()
        assert h.flow.active(1) and job.deferred is not None
        cancel = next(t for t, (a, _) in h.app.settings.session(1).buttons.items() if a == "cancel")
        h.app.submit(Event("callback", 1, payload=ButtonClick(cancel, "x")))
        await h.settle()
        assert job.deferred is None and h.flow.waiting(1) and "unclear" in h.texts()[-1]
        h.clock.now = 1700 + 899
        h.app.tick()
        await h.settle()
        assert h.flow.active(1)
        h.clock.now = 1700 + 901
        h.app.tick()
        await h.settle()
        assert not h.flow.active(1) and "waited too long" in "".join(h.texts())
    finally:
        await h.close()


async def test_settings_is_view_only_while_the_job_waits_and_editable_while_it_processes():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.recognition.gate = asyncio.Event()
        h.recognition.results.append(matching("uncertain"))
        h.app.submit(Event("file", 1, update_id=10, message_id=10, payload=Upload("scan", 1)))
        await h.until(lambda: h.flow.status(1) == "processing")
        h.app.submit(Event("text", 1, payload="Settings"))
        await h.until(lambda: any(a == "create" for a, _ in h.app.settings.session(1).buttons.values()))
        h.recognition.gate.set()
        await h.settle()
        assert h.flow.waiting(1)
        await h.text("Settings")
        assert not any(a == "create" for a, _ in h.app.settings.session(1).buttons.values())
        assert "Answer the document first" in h.texts()[-1]
    finally:
        await h.close()


async def test_terminal_matching_statuses_errors_and_budget():
    h = Harness()
    try:
        await h.sign_in()
        cases = [
            (matching("unreadable"), True, "could not be read", "as a file"),
            (matching("mixed"), False, "different documents", None),
            (matching("not_document"), False, "does not look like a document", None),
            (PhaseOutcome(error="processing_budget_exhausted"), False, "time limit", None),
            (PhaseOutcome(error="queue_wait_expired"), False, "queue", None),
            (PhaseOutcome(error="runtime_unavailable"), False, "temporarily unavailable", None),
            (PhaseOutcome(error="storage_limit"), False, "Temporary storage", None),
        ]
        for index, (outcome, compressed, expected, hint) in enumerate(cases):
            h.recognition.results.append(outcome)
            await h.file(f"doc{index}", message_id=100 + index, compressed=compressed)
            assert not h.flow.jobs and expected in h.texts()[-1], (index, h.texts()[-1])
            if hint:
                assert hint in h.texts()[-1]
        h.store.unavailable = True
        await h.file("no_profiles", message_id=200)
        assert "profiles could not be read" in h.texts()[-1] and len(h.recognition.calls) == len(cases)
    finally:
        await h.close()


async def test_cancel_during_recognition_discards_late_result_and_budget_stops_second_phase():
    h = Harness(processing_s=10)
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.recognition.gate = asyncio.Event()
        h.recognition.results.append(recognized(card))
        h.app.submit(Event("file", 1, update_id=10, message_id=10, payload=Upload("scan", 1)))
        await h.until(lambda: h.flow.status(1) == "processing")
        h.app.submit(Event("text", 1, payload="Cancel"))
        await h.until(lambda: not h.flow.jobs)
        h.recognition.gate.set()
        await h.settle()
        assert not h.results() and not h.flow.jobs and h.intake.cleaned
        # The first phase charged the whole budget: no second phase starts.
        h.recognition.gate = None
        h.recognition.results[:] = [matching("uncertain")]
        await h.file("again", message_id=11)
        assert h.flow.jobs[1].state == "awaiting_choice"
        calls = len(h.recognition.calls)
        await h.click("Card")
        assert "time limit" in h.texts()[-1] and not h.flow.jobs and len(h.recognition.calls) == calls
    finally:
        await h.close()


async def test_compile_failure_returns_to_instruction_or_ends_on_exhausted_budget():
    h = Harness(processing_s=30)
    try:
        await h.sign_in()
        h.recognition.results.append(matching("no_profile", "x"))
        await h.file("scan")
        h.compiler.results.append(CompileError("compiler_invalid_contract"))
        await h.text("Read something")
        assert h.flow.jobs[1].state == "awaiting_instruction" and "could not be compiled" in h.texts()[-1]
        h.compiler.results.append(CompileError("processing_budget_exhausted"))
        h.flow.jobs[1].used_s = 26
        await h.text("Read something else")
        assert not h.flow.jobs and "time limit" in h.texts()[-1]
    finally:
        await h.close()


async def test_late_album_fragment_during_a_question_resets_decisions_and_rematches():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.recognition.results.append(matching("no_profile", "x"))
        await h.file("a1", message_id=1, album="g")
        h.clock.now = 3
        h.app.tick()
        await h.settle()
        job = h.flow.jobs[1]
        h.compiler.results.append(CompileResult(drafts=(profile(1, "Draft"),)))
        await h.text("Read the draft ID")
        assert job.state == "awaiting_confirmation" and job.preview is not None
        h.recognition.results.append(recognized(card))
        await h.file("a2", message_id=2, album="g")
        assert job.preview is None and job.instruction == "" and job.state == "collecting"
        h.clock.now = 6
        h.app.tick()
        await h.settle()
        assert h.recognition.calls[-1].selected is None and h.recognition.calls[-1].snapshots == (card,)
        assert h.results() and not h.store.rows.get(job.preview)
    finally:
        await h.close()


async def test_delivery_retries_only_retry_after_and_reports_uncertain_delivery():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.transport.failures = [TelegramRetryAfter(METHOD, "flood", 0)]
        h.recognition.results.append(recognized(card))
        await h.file("one", message_id=1)
        assert len(h.results()) == 1 and not h.flow.jobs
        h.transport.failures = [TelegramNetworkError(METHOD, "lost")]
        h.recognition.results.append(recognized(card))
        await h.file("two", message_id=2)
        assert not h.results()[1:] and "could not be delivered completely" in h.texts()[-1]
        assert any(who == 999 and "delivery_failed" in text for who, text, _ in h.transport.sent)
        h.transport.failures = [TelegramForbiddenError(METHOD, "blocked")]
        h.recognition.results.append(recognized(card))
        await h.file("three", message_id=3)
        # A user who blocked the bot gets no further message and no operator alert.
        assert not h.flow.jobs and sum("could not be delivered" in text for text in h.texts()) == 1
        assert sum("delivery_failed" in text for who, text, _ in h.transport.sent if who == 999) == 1
    finally:
        await h.close()


async def test_cancel_during_delivery_lets_the_started_part_finish_and_sends_nothing_more():
    h = Harness()
    try:
        field = ListField(id="rows", label="Rows", description="Rows", columns=(
            ScalarField(id="value", label="Value", description="Value", type="text"),))
        table = ExtractionProfile(id=str(uuid4()), owner="1", version=1, name="Table", description="Table",
                                  original_instruction="Rows", fields=(field,))
        h.store.rows[table.id] = table
        rows = tuple(ListRow(cells=(FieldResult(field_id="value", status="extracted", raw_value="v" * 900,
                                                source_pages=(1,)),), source_pages=(1,), source_key=str(i))
                     for i in range(12))
        listing = ListResult(field_id="rows", status="complete", rows=rows, enumeration_complete=True)
        result = CoreResult(MatchingResponse(status="matched", profile_index=1), table,
                            RecognitionResult(fields=(), lists=(listing,), outcome="complete"), False)
        h.recognition.results.append(PhaseOutcome(result=result))
        gate = asyncio.Event()
        original = h.transport.send

        async def slow(owner, text, **kwargs):
            if text.startswith("Part 1/"):
                await gate.wait()
            return await original(owner, text, **kwargs)

        h.transport.send = slow
        await h.sign_in()
        h.app.submit(Event("file", 1, update_id=5, message_id=5, payload=Upload("big", 1)))
        await h.until(lambda: 1 in h.flow.jobs and h.flow.jobs[1].state == "delivering")
        h.app.submit(Event("text", 1, payload="Cancel"))
        await h.until(lambda: h.flow.jobs[1].state == "finishing")
        gate.set()
        await h.settle()
        parts = [text for text in h.texts() if text.startswith("Part ")]
        assert len(parts) == 1 and parts[0].startswith("Part 1/") and not h.flow.jobs
    finally:
        await h.close()


async def test_stale_buttons_after_restart_answer_expired_with_one_notice():
    h = Harness()
    try:
        await h.sign_in()
        h.app.submit(Event("callback", 1, payload=ButtonClick("j:deadbeef:" + "0" * 32 + ":1:00000000", "a")))
        h.app.submit(Event("callback", 1, payload=ButtonClick("s:deadbeef:1:0000000000000000", "b")))
        await h.settle()
        assert ("a", "Session expired") in h.transport.answers and ("b", "Session expired") in h.transport.answers
        assert sum("restarted" in text for text in h.texts()) == 1
    finally:
        await h.close()
