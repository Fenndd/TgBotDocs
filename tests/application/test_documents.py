"""Actor-level collection checks; real content/parser checks live in test_intake."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from tgbotdocs.application.documents import DocumentsFlow
from tgbotdocs.application.events import ButtonClick, Event, UserActor
from tgbotdocs.application.intake import IntakeError
from tgbotdocs.application.transport import Upload


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


class Transport:
    def __init__(self):
        self.sent, self.answered = [], []
    async def send(self, owner, text, **kwargs):
        self.sent.append((owner, text, kwargs))
    async def answer_callback(self, query_id, text):
        self.answered.append((query_id, text))


class Intake:
    def __init__(self, root, *, capacity=8):
        self.root, self.capacity = root, capacity
        self.submissions, self.running, self.gates = {}, {}, {}
        self.downloads, self.cleaned, self.drained = [], [], []
        self.fail, self.healthy = {}, True
    def reserve(self, owner, job_id, generation, admission_order, *, mode, album_id=None):
        if not self.healthy:
            raise IntakeError("temporarily_unavailable")
        if len(self.submissions) >= self.capacity:
            raise IntakeError("busy")
        result = SimpleNamespace(owner=owner, job_id=job_id, generation=generation,
            admission_order=admission_order, admission_time=admission_order,
            mode=mode, album_id=album_id, files=[], path=self.root)
        self.submissions[job_id], self.running[job_id] = result, set()
        return result
    async def receive(self, submission, upload, *, message_id, update_id):
        task, generation = asyncio.current_task(), submission.generation
        self.running[submission.job_id].add(task)
        self.downloads.append((submission.owner, upload.file_id))
        try:
            if upload.file_id in self.gates:
                await self.gates[upload.file_id].wait()
            if upload.file_id in self.fail:
                raise IntakeError(self.fail[upload.file_id])
            if generation != submission.generation:
                raise asyncio.CancelledError
            result = SimpleNamespace(file_key=upload.file_id, message_id=message_id,
                compressed=upload.compressed, path=Path(upload.file_id), arrival_sequence=len(submission.files),
                pages=(object(),))
            submission.files.append(result)
            return result
        finally:
            self.running[submission.job_id].discard(task)
    async def seal(self, submission, *, remaining_budget_s=None):
        estimate = len(submission.files) * 10
        if estimate > remaining_budget_s:
            raise IntakeError("processing_limit")
        files = tuple(sorted(submission.files, key=lambda f: f.message_id)) if submission.mode == "album" else tuple(submission.files)
        return SimpleNamespace(files=files, generation=submission.generation, estimate_s=estimate)
    def cancel_now(self, submission):
        submission.generation += 1
        for task in tuple(self.running[submission.job_id]):
            if not task.cancelling():
                task.cancel()
    async def drain(self, submission):
        await asyncio.gather(*tuple(self.running[submission.job_id]), return_exceptions=True)
        assert not self.running[submission.job_id]
        self.drained.append(submission.job_id)
    async def close_submission(self, submission):
        self.cancel_now(submission)
        await self.drain(submission)
        self.cleaned.append(submission.job_id)
        self.submissions.pop(submission.job_id)
    async def close(self):
        assert not self.submissions


class Harness:
    def __init__(self, root, **kwargs):
        self.clock, self.transport, self.ready, self.actors, self.discarded = Clock(), Transport(), [], {}, []
        self.intake = Intake(root, **kwargs)
        config = SimpleNamespace(processing_s=1800, inactivity_s=900, album_quiet_s=2)
        async def ready(job, document):
            self.ready.append((job.submission.owner, document))
        self.flow = DocumentsFlow(self.intake, self.transport, self.submit, config, clock=self.clock,
            on_ready=ready, discard_drafts=lambda *args: self.discarded.append(args))
    def submit(self, event):
        if event.owner not in self.actors:
            self.actors[event.owner] = UserActor(event.owner, self.flow.handle)
        self.actors[event.owner].enqueue(event)
    def file(self, owner, identifier, *, message_id=1, album=None):
        self.submit(Event("file", owner, update_id=message_id, message_id=message_id,
                          payload=Upload(identifier, None, media_group_id=album)))
    async def until(self, predicate):
        async with asyncio.timeout(3):
            while True:
                for actor in tuple(self.actors.values()):
                    await actor.mailbox.join()
                await asyncio.sleep(.001)
                if predicate():
                    return
    async def settle(self):
        await self.until(lambda: not self.flow.tasks)
    async def close(self):
        await self.flow.close()
        for actor in self.actors.values():
            await actor.close()


async def test_single_auto_start_second_document_and_pre_download_admission(tmp_path):
    h = Harness(tmp_path, capacity=1)
    try:
        h.intake.healthy = False
        h.file(1, "unavailable")
        await h.settle()
        assert not h.intake.downloads and not h.flow.jobs
        h.intake.healthy = True
        h.file(1, "first")
        await h.settle()
        assert h.ready[0][1].files[0].file_key == "first"
        h.file(1, "second")
        h.file(2, "busy")
        await h.settle()
        assert h.intake.downloads == [(1, "first")]
        assert any("Busy" in text for _, text, _ in h.transport.sent)
        h.flow.cancel(1)
        h.flow.cancel(1)
        await h.settle()
        assert not h.flow.jobs and len(h.intake.cleaned) == 1
        h.file(1, "after_cancel", message_id=3)
        await h.settle()
        assert h.intake.downloads[-1] == (1, "after_cancel")
    finally:
        await h.close()


async def test_several_pages_empty_process_waits_for_pending_and_keeps_invalid_file_out(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        assert h.flow.waiting(1)
        job = h.flow.jobs[1]
        tokens = dict(job.buttons)
        assert all(len(token.encode()) <= 64 for token in tokens)
        process = next(token for token, action in tokens.items() if action == "process")
        h.submit(Event("callback", 2, payload=ButtonClick(process, "foreign")))
        h.submit(Event("text", 1, payload="Process"))
        await h.settle()
        assert not h.ready and h.transport.answered[-1] == ("foreign", "Session expired")
        h.intake.gates["pending"] = asyncio.Event()
        h.file(1, "pending")
        await h.until(lambda: bool(h.intake.downloads))
        h.submit(Event("text", 1, payload="Process"))
        await h.until(lambda: job.process_requested)
        h.file(1, "after_process", message_id=2)
        await h.until(lambda: len(h.transport.sent) >= 4)
        assert not h.ready
        h.intake.gates["pending"].set()
        await h.settle()
        assert [f.file_key for f in h.ready[0][1].files] == ["pending"]
        assert (1, "after_process") not in h.intake.downloads
        h.flow.cancel(1)
        await h.settle()
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        h.intake.fail["bad"] = "damaged_input"
        h.file(1, "bad", message_id=2)
        h.file(1, "valid", message_id=3)
        await h.settle()
        assert h.flow.active(1) and h.flow.waiting(1)
        h.submit(Event("text", 1, payload="Process"))
        await h.settle()
        assert [f.file_key for f in h.ready[-1][1].files] == ["valid"]
    finally:
        await h.close()


async def test_album_quiet_waits_for_all_files_and_late_replay_preserves_admission_and_budget(tmp_path):
    h = Harness(tmp_path)
    try:
        h.intake.gates["earlier"] = asyncio.Event()
        h.file(1, "later", message_id=12, album="group")
        h.file(1, "earlier", message_id=11, album="group")
        await h.until(lambda: len(h.intake.downloads) == 2)
        h.clock.now = 3
        h.submit(Event("tick", 1))
        await h.until(lambda: h.flow.jobs[1].pending == 1)
        assert not h.ready
        h.intake.gates["earlier"].set()
        await h.settle()
        job = h.flow.jobs[1]
        assert [f.file_key for f in h.ready[0][1].files] == ["earlier", "later"]
        generation, admission = job.generation, job.submission.admission_order
        job.used_s = 42
        h.file(1, "latest", message_id=13, album="group")
        await h.settle()
        assert job.generation == generation + 1 and job.used_s == 42
        assert job.submission.admission_order == admission
        assert h.intake.drained and not h.intake.cleaned
        h.clock.now = 6
        h.submit(Event("tick", 1))
        await h.settle()
        assert [f.file_key for f in h.ready[-1][1].files] == ["earlier", "later", "latest"]
        assert h.ready[-1][1].generation == job.generation
        h.flow.mark_delivering(1)
        h.file(1, "too_late", message_id=14, album="group")
        await h.settle()
        assert len(h.intake.downloads) == 3
        h.flow.finish(1)
        await h.settle()
        h.file(1, "closed_album", message_id=15, album="group")
        await h.settle()
        assert len(h.intake.downloads) == 3 and not h.flow.jobs
    finally:
        await h.close()


async def test_manual_known_album_late_replay_delivery_refusal_and_terminal_memory(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        h.file(1, "loose", message_id=1)
        h.file(1, "a1", message_id=2, album="g")
        h.file(1, "a2", message_id=3, album="g")
        await h.settle()
        job = h.flow.jobs[1]
        assert job.album_groups == {"g"} and h.flow.waiting(1)
        h.submit(Event("text", 1, payload="Process"))
        await h.settle()
        assert [f.file_key for f in h.ready[-1][1].files] == ["loose", "a1", "a2"]
        assert not h.flow.waiting(1)
        generation, admission = job.generation, job.submission.admission_order
        job.used_s = 30
        h.file(1, "unrelated", message_id=4)
        await h.settle()
        assert (1, "unrelated") not in h.intake.downloads
        # A known album's late fragment restarts the pass before delivery and keeps
        # the admission place and the budget already charged.
        h.file(1, "a3", message_id=5, album="g")
        await h.settle()
        assert job.generation > generation and job.used_s == 30
        assert job.submission.admission_order == admission
        assert h.discarded[-1] == (1, job.submission.job_id)
        assert len(h.ready) == 1 and h.intake.drained and not h.intake.cleaned
        h.file(1, "unrelated_after_restart", message_id=6)
        h.clock.now = 3
        h.submit(Event("tick", 1))
        await h.settle()
        assert [f.file_key for f in h.ready[-1][1].files] == ["loose", "a1", "a2", "a3"]
        assert h.ready[-1][1].generation == job.generation
        assert (1, "unrelated_after_restart") not in h.intake.downloads
        # After delivery starts the fragment is refused without a download.
        h.flow.mark_delivering(1)
        h.file(1, "a4", message_id=7, album="g")
        await h.settle()
        assert (1, "a4") not in h.intake.downloads
        assert "incomplete album" in h.transport.sent[-1][1]
        h.flow.finish(1)
        await h.settle()
        assert not h.flow.jobs
        # The group stays remembered after the job ends; no new job starts.
        h.file(1, "a5", message_id=8, album="g")
        await h.settle()
        assert not h.flow.jobs and (1, "a5") not in h.intake.downloads
        assert "incomplete album" in h.transport.sent[-1][1]
        h.clock.now = 3 + 901
        h.submit(Event("tick", 1))
        await h.settle()
        assert (1, "g") not in h.flow.remembered
    finally:
        await h.close()


async def test_cancelled_album_is_remembered_as_closed_and_pending_process_waits_for_quiet(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        h.intake.gates["slow"] = asyncio.Event()
        h.file(1, "slow", message_id=1, album="late")
        await h.until(lambda: bool(h.intake.downloads))
        h.submit(Event("text", 1, payload="Process"))
        await h.until(lambda: h.flow.jobs[1].process_requested)
        # A new album after Process is unrelated input and is refused.
        h.file(1, "other_album", message_id=2, album="other")
        # A known album's member after Process waits for the album quiet window.
        h.file(1, "m1", message_id=3, album="late")
        h.intake.gates["slow"].set()
        await h.settle()
        assert not h.ready and h.flow.jobs[1].late_album_quiet
        assert (1, "other_album") not in h.intake.downloads
        h.clock.now = 5
        h.submit(Event("tick", 1))
        await h.settle()
        assert [f.file_key for f in h.ready[-1][1].files] == ["slow", "m1"]
        h.flow.cancel(1)
        await h.settle()
        h.file(1, "m2", message_id=4, album="late")
        await h.settle()
        assert not h.flow.jobs and (1, "m2") not in h.intake.downloads
        assert "album is closed" in h.transport.sent[-1][1]
    finally:
        await h.close()


async def test_refused_first_album_part_closes_its_group(tmp_path):
    h = Harness(tmp_path, capacity=1)
    try:
        h.file(2, "other")
        await h.settle()
        # Busy: the first part is refused before any download, so the group closes.
        h.file(1, "p1", message_id=1, album="busy")
        await h.settle()
        h.flow.cancel(2)
        await h.settle()
        h.file(1, "p2", message_id=2, album="busy")
        h.clock.now = 3
        h.submit(Event("tick", 1))
        await h.settle()
        assert not h.flow.jobs and (1, "p2") not in h.intake.downloads
        assert "album is closed" in h.transport.sent[-1][1]
        # A part refused while another job is active closes that group too.
        h.file(1, "single", message_id=3)
        await h.settle()
        h.file(1, "q1", message_id=4, album="while_active")
        await h.settle()
        h.flow.cancel(1)
        await h.settle()
        h.file(1, "q2", message_id=5, album="while_active")
        await h.settle()
        assert not h.flow.jobs and (1, "q2") not in h.intake.downloads
    finally:
        await h.close()


async def test_earlier_buttons_of_the_current_generation_stay_valid(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        first = {action: token for token, action in h.flow.jobs[1].buttons.items()}
        h.file(1, "page")
        await h.settle()
        h.submit(Event("callback", 1, payload=ButtonClick(first["process"], "q1")))
        await h.settle()
        assert h.transport.answered[-1] == ("q1", "")
        assert [f.file_key for f in h.ready[-1][1].files] == ["page"]
        # Cancel from the first message still acts on the job of that generation.
        h.submit(Event("callback", 1, payload=ButtonClick(first["cancel"], "q2")))
        await h.settle()
        assert not h.flow.jobs
        h.submit(Event("callback", 1, payload=ButtonClick(first["process"], "q3")))
        await h.settle()
        assert h.transport.answered[-1] == ("q3", "Session expired")
    finally:
        await h.close()


async def test_accepted_pages_and_process_reset_inactivity_and_expiry_is_final(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        tokens = {action: token for token, action in h.flow.jobs[1].buttons.items()}
        h.clock.now = 800
        h.intake.gates["slow"] = asyncio.Event()
        h.file(1, "slow", album="group")
        await h.until(lambda: bool(h.intake.downloads))
        # A page still downloading counts as activity.
        h.clock.now = 1000
        h.submit(Event("tick", 1))
        await h.until(lambda: True)
        assert h.flow.active(1)
        h.intake.gates["slow"].set()
        await h.settle()
        h.clock.now = 1650
        h.submit(Event("text", 1, payload="Process"))
        await h.settle()
        assert h.ready
        h.flow.jobs[1].state = "collecting"  # model a pass that returned to collection
        h.flow.jobs[1].process_requested = False
        h.clock.now = 1650 + 899
        h.submit(Event("tick", 1))
        await h.settle()
        assert h.flow.active(1)
        h.clock.now = 1650 + 901
        h.submit(Event("tick", 1))
        await h.settle()
        assert not h.flow.active(1)
        # The expired job's own button and a late part of its album revive nothing.
        h.submit(Event("callback", 1, payload=ButtonClick(tokens["process"], "late")))
        h.file(1, "late_part", message_id=9, album="group")
        await h.settle()
        assert not h.flow.jobs and h.transport.answered[-1] == ("late", "Session expired")
        assert (1, "late_part") not in h.intake.downloads
    finally:
        await h.close()


async def test_empty_seal_after_failed_late_album_parts_waits_for_process_again(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        h.intake.fail.update({"g1": "damaged_input", "g2": "damaged_input"})
        h.intake.gates["g1"] = asyncio.Event()
        h.file(1, "g1", message_id=1, album="g")
        await h.until(lambda: bool(h.intake.downloads))
        h.submit(Event("text", 1, payload="Process"))
        await h.until(lambda: h.flow.jobs[1].process_requested)
        h.file(1, "g2", message_id=2, album="g")
        h.intake.gates["g1"].set()
        await h.settle()
        h.clock.now = 3
        h.submit(Event("tick", 1))
        await h.settle()
        job = h.flow.jobs[1]
        assert not job.late_album_quiet and not job.process_requested and h.flow.waiting(1)
        notices = sum("No document is present" in text for _, text, _ in h.transport.sent)
        h.clock.now = 6
        h.submit(Event("tick", 1))
        h.file(1, "loose", message_id=3)
        await h.settle()
        h.clock.now = 10
        h.submit(Event("tick", 1))
        await h.settle()
        # No repeated notice, and the loose page waits for an explicit Process.
        assert sum("No document is present" in text for _, text, _ in h.transport.sent) == notices
        assert not h.ready and job.state == "collecting"
    finally:
        await h.close()


async def test_album_failure_is_whole_set_manual_quota_ends_job_and_cancel_drains(tmp_path):
    h = Harness(tmp_path)
    try:
        h.intake.fail["bad"] = "encrypted_pdf"
        h.intake.gates["running"] = asyncio.Event()
        h.file(1, "running", message_id=1, album="g")
        h.file(1, "bad", message_id=2, album="g")
        await h.settle()
        assert not h.flow.jobs and not h.ready and h.intake.cleaned
        assert not any(h.intake.running.values())
        h.submit(Event("text", 2, payload="Several pages"))
        await h.settle()
        h.intake.fail["full"] = "storage_limit"
        h.file(2, "full")
        await h.settle()
        assert not h.flow.jobs
        h.file(3, "running")
        await h.until(lambda: h.flow.jobs[3].pending == 1 and bool(h.intake.running[h.flow.jobs[3].submission.job_id]))
        old = h.flow.jobs[3]
        generation = old.generation
        h.flow.cancel(3)
        await h.settle()
        h.submit(Event("document_io", 3, job_id=old.submission.job_id,
                       generation=generation, payload=("receive", SimpleNamespace(file_key="stale"), None)))
        await h.settle()
        assert not h.flow.jobs and not h.ready and not any(h.intake.running.values())
    finally:
        await h.close()


async def test_collection_expiry_uses_accepted_activity_and_absolute_album_deadline(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        h.clock.now = 800
        h.submit(Event("text", 1, payload="unrelated input"))
        h.clock.now = 901
        h.submit(Event("tick", 1))
        await h.settle()
        assert not h.flow.active(1)
        h.file(2, "page", album="album")
        await h.settle()
        h.clock.now = 1800
        h.file(2, "new_page", message_id=2, album="album")
        await h.settle()
        h.clock.now = 1802
        h.submit(Event("tick", 2))
        await h.settle()
        assert not h.flow.active(2) and not h.ready
    finally:
        await h.close()


async def test_complete_set_budget_refusal_has_no_ready_prefix(tmp_path):
    h = Harness(tmp_path)
    try:
        h.submit(Event("text", 1, payload="Several pages"))
        await h.settle()
        h.file(1, "one")
        h.file(1, "two", message_id=2)
        await h.settle()
        h.flow.jobs[1].used_s = 1790
        h.submit(Event("text", 1, payload="Process"))
        await h.settle()
        assert not h.ready and not h.flow.jobs
        assert any("Nothing was truncated" in text for _, text, _ in h.transport.sent)
    finally:
        await h.close()


async def test_product_auth_and_ordered_intake_with_actual_supervised_parser(tmp_path):
    from io import BytesIO
    from PIL import Image
    import pypdfium2 as pdfium
    from tgbotdocs.application.intake import IntakeManager
    from tgbotdocs.application.lifecycle import TemporaryLifecycle
    from tgbotdocs.application.product import ProductApplication
    from tgbotdocs.application.supervision import supervise_children

    image = BytesIO()
    with Image.new("RGB", (60, 40), "red") as source:
        source.save(image, format="PNG")
    pdf_path = tmp_path / "source-pdf"
    with pdfium.PdfDocument.new() as source:
        source.new_page(72, 144).close()
        source.new_page(144, 72).close()
        source.save(pdf_path)
    payloads = {"photo": image.getvalue(), "file": image.getvalue(), "pdf": pdf_path.read_bytes()}
    class ControlledTransport(Transport):
        def __init__(self):
            super().__init__()
            self.downloads = []
        async def download(self, upload, sink):
            self.downloads.append(upload.file_id)
            content = payloads[upload.file_id]
            sink.write(content[:8])
            await asyncio.sleep(0)
            sink.write(content[8:])
        async def delete(self, owner, message_id):
            return True
    lifecycle = TemporaryLifecycle(tmp_path / "owned", free_reserve_bytes=0)
    assert await lifecycle.initialize()
    transport = ControlledTransport()
    core = SimpleNamespace(processing_budget_s=1800, call_timeout_s=30,
        max_pixels=10000, quota_bytes=2 * 1024**3, free_reserve_bytes=0)
    frozen = SimpleNamespace(core=core, page_times=tuple(
        SimpleNamespace(kind=kind, p5=10) for kind in ("png", "jpeg", "pdf")))
    manager = IntakeManager(lifecycle, transport, frozen)
    config = SimpleNamespace(password="synthetic-password-123", inactivity_s=900,
        processing_s=1800, album_quiet_s=2, operator_ids=())
    parent = ProductApplication(config, transport, object(), object())
    ready = []
    async def prepared(job, document):
        ready.append((job.submission.owner, document))
    flow = DocumentsFlow(manager, transport, parent.submit, config, on_ready=prepared)
    parent.documents = flow
    async def settle():
        async with asyncio.timeout(15):
            while True:
                for actor in tuple(parent.actors.values()):
                    await actor.mailbox.join()
                await asyncio.sleep(.005)
                if not parent.tasks and not flow.tasks and not parent.settings.tasks:
                    return
    try:
        async with supervise_children(lifecycle):
            parent.submit(Event("file", 1, update_id=1, message_id=1, payload=Upload("file", None)))
            await settle()
            assert not transport.downloads and not manager.submissions
            for owner in (1, 2):
                parent.submit(Event("text", owner, payload="/start", message_id=2))
                parent.submit(Event("text", owner, payload=config.password, message_id=3))
                parent.submit(Event("text", owner, payload="Several pages"))
            await settle()
            assert flow.waiting(1) and flow.waiting(2)
            # Distinct messages with identical bytes stay distinct; update redelivery does not.
            duplicate = Event("file", 1, update_id=10, message_id=10, payload=Upload("photo", 1, True))
            parent.submit(duplicate)
            parent.submit(duplicate)
            await settle()
            assert any(owner == 1 and "1 files and 1 pages" in text for owner, text, _ in transport.sent)
            parent.submit(Event("file", 1, update_id=11, message_id=11, payload=Upload("pdf", 1)))
            parent.submit(Event("file", 1, update_id=12, message_id=12, payload=Upload("file", 1)))
            parent.submit(Event("file", 2, update_id=13, message_id=13, payload=Upload("file", 1)))
            parent.submit(Event("text", 1, payload="Process"))
            parent.submit(Event("text", 2, payload="Process"))
            await settle()
            first = next(document for owner, document in ready if owner == 1)
            second = next(document for owner, document in ready if owner == 2)
            assert [f.kind for f in first.files] == ["png", "pdf", "png"]
            assert len(first.document.pages) == 4 and len(first.page_bindings) == 4
            assert first.files[0].compressed and not first.files[2].compressed
            assert first.page_bindings[0][0] != first.page_bindings[-1][0]
            assert len(second.document.pages) == 1
            assert any("files and" in text and "pages" in text for _, text, _ in transport.sent)
            assert set(first.paths).isdisjoint(second.paths)
            assert transport.downloads.count("photo") == 1
            assert not lifecycle._processes
            parent.submit(Event("text", 1, payload="Logout"))
            parent.submit(Event("text", 2, payload="Cancel"))
            await settle()
            assert not flow.jobs and not manager.submissions
            assert not list(lifecycle.root.glob("job-*"))
    finally:
        await parent.close()
