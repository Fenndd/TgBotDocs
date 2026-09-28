"""Model-based checks of the STATE_MACHINE invariants (TEST_STRATEGY, T06).

Hypothesis drives random event sequences for two users through the real product
actor and document flow, with a fake clock, Telegram, intake, recognition,
compiler and storage. Recognition and compilation park until a rule releases
them, so Cancel, Logout, late album parts, ticks and stale buttons race with
running operations. Invariants from STATE_MACHINE are checked after every step.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from tgbotdocs.application.compiler import CompileError, CompileResult
from tgbotdocs.application.documents import DocumentsFlow
from tgbotdocs.application.events import ButtonClick, Event
from tgbotdocs.application.intake import IntakeError
from tgbotdocs.application.pipeline import PhaseOutcome
from tgbotdocs.application.product import ProductApplication
from tgbotdocs.application.profiles import PreviewService
from tgbotdocs.application.transport import Upload
from tgbotdocs.recognition.contracts import (ExtractionProfile, FieldResult, MatchingResponse, RecognitionResult,
                                             ScalarField)
from tgbotdocs.recognition.core import CoreResult

PASSWORD = "synthetic-password-123"
OWNERS = (1, 2)
PROCESSING_S = 60.0
CHARGE_S = 7.0


def profile(owner, name):
    return ExtractionProfile(id=str(uuid4()), owner=str(owner), version=1, name=name, description=name,
                             original_instruction="Read the ID", fields=(ScalarField(
                                 id="identifier", label="Identifier", description="ID", type="text"),))


class Model:
    """Shared record of what the fakes observed, checked by the invariants."""

    def __init__(self):
        self.violations, self.parked, self.compiles = [], [], []
        self.results_allowed = {owner: 0 for owner in OWNERS}
        self.reserved, self.cleaned = set(), set()


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Transport:
    def __init__(self):
        self.sent, self.answers = [], []

    async def send(self, owner, text, **kwargs):
        self.sent.append((owner, text))

    async def delete(self, owner, identifier):
        return True

    async def answer_callback(self, query_id, text):
        self.answers.append(text)


class Store:
    def __init__(self):
        self.rows = {}

    async def list_profiles(self, owner):
        return tuple(p for p in self.rows.values() if p.owner == str(owner))

    async def save_drafts(self, owner, drafts):
        self.rows.update((p.id, p) for p in drafts)
        return drafts


class Intake:
    def __init__(self, model, machine):
        self.model, self.machine, self.submissions = model, machine, {}

    def reserve(self, owner, job_id, generation, admission_order, *, mode, album_id=None):
        if any(s.owner == owner for s in self.submissions.values()):
            raise IntakeError("active_document")
        if not self.machine.app.session(owner).signed_in:
            self.model.violations.append("reserved_before_sign_in")
        submission = SimpleNamespace(owner=owner, job_id=job_id, generation=generation, admission_order=admission_order,
                                     admission_time=self.machine.clock(), mode=mode, album_id=album_id, files=[],
                                     path=Path("job"))
        self.submissions[job_id] = submission
        self.model.reserved.add(job_id)
        return submission

    async def receive(self, submission, upload, *, message_id, update_id):
        if not self.machine.app.session(submission.owner).signed_in:
            self.model.violations.append("download_before_sign_in")
        item = SimpleNamespace(file_key=upload.file_id, message_id=message_id, compressed=upload.compressed,
                               path=Path(upload.file_id), pages=(object(),))
        submission.files.append(item)
        return item

    async def seal(self, submission, *, remaining_budget_s=None):
        if remaining_budget_s is not None and remaining_budget_s <= 0:
            raise IntakeError("processing_limit")
        files = tuple(submission.files)
        return SimpleNamespace(files=files, generation=submission.generation, estimate_s=1.0,
                               paths=tuple(f.path for f in files),
                               document=SimpleNamespace(pages=tuple(object() for _ in files)))

    def cancel_now(self, submission):
        submission.generation += 1

    async def drain(self, submission):
        pass

    async def close_submission(self, submission):
        self.cancel_now(submission)
        self.submissions.pop(submission.job_id, None)
        self.model.cleaned.add(submission.job_id)

    async def close(self):
        pass


class Recognition:
    def __init__(self, model, machine):
        self.model, self.machine = model, machine

    async def run(self, *, key, admission_order, files, pages, scratch, snapshots, remaining_s, charge,
                  selected_profile=None, started=None):
        job_id, generation, _ = key.split(":")
        owner = next((o for o, j in self.machine.flow.jobs.items() if j.submission.job_id == job_id), None)
        job = self.machine.flow.jobs.get(owner)
        # No model call for a cancelled job or an old generation (STATE_MACHINE invariants).
        if job is None or job.state != "queued" or job.generation != int(generation):
            self.model.violations.append("call_for_cancelled_or_stale_job")
        if remaining_s <= 0:
            self.model.violations.append("call_without_budget")
        future = asyncio.get_running_loop().create_future()
        self.calls = getattr(self, "calls", 0) + 1
        entry = SimpleNamespace(owner=owner, job_id=job_id, generation=int(generation), future=future,
                                snapshots=snapshots, selected=selected_profile, late=self.calls % 2 == 0)
        self.model.parked.append(entry)
        try:
            if started:
                started()
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                if not entry.late:
                    raise
                # A late model response: the call returns after the job moved on.
                return await future
        finally:
            charge(CHARGE_S)
            if entry in self.model.parked:
                self.model.parked.remove(entry)


class Compiler:
    def __init__(self, model):
        self.model = model

    async def compile(self, owner, instruction, *, current=(), remaining_budget_s=300, charged=None, **kwargs):
        future = asyncio.get_running_loop().create_future()
        entry = SimpleNamespace(owner=owner, future=future)
        self.model.compiles.append(entry)
        try:
            return await future
        finally:
            if charged is not None:
                charged(1.0)
            if entry in self.model.compiles:
                self.model.compiles.remove(entry)


OUTCOMES = st.sampled_from(("matched", "uncertain", "no_profile", "unreadable", "mixed", "error", "budget"))


class JobMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.model, self.clock, self.transport, self.store = Model(), Clock(), Transport(), Store()
        self.config = SimpleNamespace(password=PASSWORD, inactivity_s=900, processing_s=PROCESSING_S,
                                      album_quiet_s=2, delivery_s=60, delivery_attempts=3, operator_ids=())
        self.message_id, self.albums, self.tokens = 1, {}, {owner: [] for owner in OWNERS}
        self.loop.run_until_complete(self._build())
        for owner in OWNERS:
            saved = profile(owner, f"Saved{owner}")
            self.store.rows[saved.id] = saved

    async def _build(self):
        self.app = ProductApplication(self.config, self.transport, self.store, Compiler(self.model), clock=self.clock)
        self.flow = DocumentsFlow(Intake(self.model, self), self.transport, self.app.submit, self.config,
                                  recognition=Recognition(self.model, self), store=self.store,
                                  compiler=self.app.settings.compiler,
                                  previews=PreviewService(self.store, ttl_s=900, clock=self.clock), clock=self.clock)
        self.app.attach(self.flow)

    def settle(self, action=None):
        """Apply ``action`` inside the machine's loop, then run until quiescent."""
        async def quiesce():
            if action is not None:
                action()
            for _ in range(400):
                for actor in tuple(self.app.actors.values()):
                    await actor.mailbox.join()
                await asyncio.sleep(0)
        self.loop.run_until_complete(quiesce())
        for owner in OWNERS:
            job = self.flow.jobs.get(owner)
            if job is not None:
                self.tokens[owner].extend(t for t in job.buttons if t not in self.tokens[owner])

    def submit(self, event):
        self.settle(lambda: self.app.submit(event))

    def next_id(self):
        self.message_id += 1
        return self.message_id

    @initialize()
    def both_users_sign_in(self):
        for owner in OWNERS:
            self.sign_in(owner)

    @rule(owner=st.sampled_from(OWNERS))
    def sign_in(self, owner):
        self.submit(Event("text", owner, payload="/start"))
        self.submit(Event("text", owner, payload=PASSWORD, message_id=self.next_id()))

    @rule(owner=st.sampled_from(OWNERS), album=st.booleans(), compressed=st.booleans())
    def send_file(self, owner, album, compressed):
        identifier = self.next_id()
        group = None
        if album:
            group = self.albums.setdefault(owner, f"g{owner}-{identifier}")
        self.submit(Event("file", owner, update_id=identifier, message_id=identifier,
                          payload=Upload(f"f{identifier}", 1, compressed, group)))

    @rule(owner=st.sampled_from(OWNERS))
    def new_album(self, owner):
        self.albums.pop(owner, None)

    @rule(owner=st.sampled_from(OWNERS), text=st.sampled_from((
        "Read the ID", "Read the ID", "Read the ID", "Several pages", "Process", "Cancel", "Logout", "Settings",
        "/start")))
    def text(self, owner, text):
        self.submit(Event("text", owner, payload=text))

    @rule(seconds=st.sampled_from((0.5, 3.0, 400.0, 1000.0)))
    def tick(self, seconds):
        self.clock.now += seconds
        self.settle(self.app.tick)

    @precondition(lambda self: self.model.parked or self.model.compiles)
    @rule(data=st.data(), outcome=OUTCOMES, kind=st.sampled_from(("drafts", "two_drafts", "questions", "error")))
    def release(self, data, outcome, kind):
        """Complete one running model operation: a recognition phase or a compilation."""
        pending = self.model.parked + self.model.compiles
        entry = pending[data.draw(st.integers(0, 7)) % len(pending)]
        if entry in self.model.compiles:
            self.release_compile(entry, kind)
            return
        if entry.future.done():
            return
        chosen = entry.selected or (entry.snapshots[0] if entry.snapshots else profile(entry.owner or 1, "Card"))
        if outcome == "matched":
            field = FieldResult(field_id="identifier", status="extracted", raw_value="SYN-1", source_pages=(1,))
            value = PhaseOutcome(result=CoreResult(MatchingResponse(status="matched", profile_index=1), chosen,
                                 RecognitionResult(fields=(field,), lists=(), outcome="complete"),
                                 entry.selected is not None))
            job = self.flow.jobs.get(entry.owner)
            if job is not None and job.submission.job_id == entry.job_id and job.generation == entry.generation:
                self.model.results_allowed[entry.owner] += 1
        elif outcome == "error":
            value = PhaseOutcome(error="runtime_unavailable")
        elif outcome == "budget":
            value = PhaseOutcome(error="processing_budget_exhausted")
        else:
            value = PhaseOutcome(result=CoreResult(MatchingResponse(
                status=outcome, type_description="x" if outcome == "no_profile" else None), None, None, False))
        self.settle(lambda: entry.future.set_result(value))

    def release_compile(self, entry, kind):
        if entry.future.done():
            return
        if kind == "error":
            action = lambda: entry.future.set_exception(CompileError("compiler_invalid_contract"))  # noqa: E731
        elif kind == "questions":
            action = lambda: entry.future.set_result(CompileResult(questions=("Which fields?",)))  # noqa: E731
        else:
            drafts = tuple(profile(entry.owner, f"P{i}") for i in range(2 if kind == "two_drafts" else 1))
            action = lambda: entry.future.set_result(CompileResult(drafts=drafts))  # noqa: E731
        self.settle(action)

    @rule(owner=st.sampled_from(OWNERS), data=st.data())
    def click_current(self, owner, data):
        job = self.flow.jobs.get(owner)
        if job is None or not job.buttons:
            return
        # Insertion order is deterministic; token text is random per run.
        tokens = list(job.buttons)
        token = tokens[data.draw(st.integers(0, 15)) % len(tokens)]
        self.submit(Event("callback", owner, payload=ButtonClick(token, "q")))

    @precondition(lambda self: any(self.tokens.values()))
    @rule(owner=st.sampled_from(OWNERS), data=st.data())
    def click_own_old(self, owner, data):
        pool = self.tokens[owner]
        if not pool:
            return
        token = pool[data.draw(st.integers(0, 63)) % len(pool)]
        self.submit(Event("callback", owner, payload=ButtonClick(token, "q")))

    @precondition(lambda self: any(self.tokens.values()))
    @rule(owner=st.sampled_from(OWNERS), data=st.data())
    def click_foreign(self, owner, data):
        pool = self.tokens[2 if owner == 1 else 1]
        if not pool:
            return
        token = pool[data.draw(st.integers(0, 63)) % len(pool)]

        def state():
            return {o: (j.state, j.generation, j.used_s, j.selected) for o, j in self.flow.jobs.items()}
        before, rows = state(), dict(self.store.rows)
        self.submit(Event("callback", owner, payload=ButtonClick(token, "q")))
        # Another user's button changes nothing for anyone.
        assert state() == before and self.store.rows == rows
        assert self.transport.answers[-1] == "Session expired"

    @rule(owner=st.sampled_from(OWNERS))
    def open_settings_draft(self, owner):
        """Settings, then Create profile: a Settings draft that waits for the user's input."""
        self.submit(Event("text", owner, payload="Settings"))
        create = [t for t, (action, _) in self.app.settings.session(owner).buttons.items() if action == "create"]
        if create:
            self.submit(Event("callback", owner, payload=ButtonClick(create[0], "create")))

    @rule(owner=st.sampled_from(OWNERS), data=st.data())
    def settings_button(self, owner, data):
        buttons = self.app.settings.session(owner).buttons
        if not buttons:
            return
        tokens = list(buttons)
        token = tokens[data.draw(st.integers(0, 15)) % len(tokens)]
        self.submit(Event("callback", owner, payload=ButtonClick(token, "s")))

    @invariant()
    def no_recorded_violation(self):
        assert not self.model.violations, self.model.violations

    @invariant()
    def at_most_one_job_and_one_waiting_flow(self):
        for owner in OWNERS:
            assert sum(s.owner == owner for s in self.flow.intake.submissions.values()) <= 1
            assert not (self.flow.waiting(owner) and self.app.settings.waiting(owner)), owner

    @invariant()
    def terminal_jobs_are_cleaned_and_budget_is_bounded(self):
        live = {job.submission.job_id for job in self.flow.jobs.values()}
        assert self.model.reserved - live <= self.model.cleaned
        for job in self.flow.jobs.values():
            assert job.used_s <= PROCESSING_S + CHARGE_S

    @invariant()
    def results_only_for_released_current_matches(self):
        for owner in OWNERS:
            results = sum(1 for who, text in self.transport.sent if who == owner and text.startswith("Result:"))
            assert results <= self.model.results_allowed[owner]
        assert not any(who not in OWNERS for who, _ in self.transport.sent)

    @invariant()
    def job_drafts_exist_only_for_live_jobs(self):
        for (owner, _), entry in self.flow.previews._entries.items():
            job = self.flow.jobs.get(owner)
            assert job is not None and entry.preview.job_id == job.submission.job_id
            assert job.state in ("awaiting_confirmation", "saving")

    @invariant()
    def signed_out_users_have_no_job(self):
        for owner in OWNERS:
            job = self.flow.jobs.get(owner)
            if not self.app.session(owner).signed_in and job is not None:
                assert job.state == "finishing"

    def teardown(self):
        try:
            self.settle(lambda: [self.app.submit(Event("text", owner, payload="Logout")) for owner in OWNERS])
            # Late model responses end now; their results must not reach anyone.
            for entry in list(self.model.parked):
                if not entry.future.done():
                    self.settle(lambda entry=entry: entry.future.set_result(PhaseOutcome(error="runtime_timeout")))
            assert not self.flow.jobs and not self.flow.intake.submissions
            assert self.model.reserved <= self.model.cleaned
            assert not self.model.parked and not self.model.compiles
            self.loop.run_until_complete(self.app.close())
        finally:
            self.loop.close()


JobMachine.TestCase.settings = settings(max_examples=300, stateful_step_count=60, deadline=None,
                                        suppress_health_check=[HealthCheck.too_slow])
TestJobStateMachine = JobMachine.TestCase
