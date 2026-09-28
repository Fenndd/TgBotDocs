import asyncio
import errno
import sys
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pypdfium2 as pdfium
import pytest

from tgbotdocs.application.intake import IntakeError, IntakeManager
from tgbotdocs.application.lifecycle import TemporaryLifecycle
from tgbotdocs.application.supervision import supervise_children
from tgbotdocs.application.transport import Upload


def frozen(*, budget=1800, pixels=10000, p5=10):
    return SimpleNamespace(page_times=tuple(SimpleNamespace(kind=k, p5=p5) for k in ("png", "jpeg", "pdf")),
        core=SimpleNamespace(processing_budget_s=budget, call_timeout_s=30,
            max_pixels=pixels, quota_bytes=2 * 1024**3, free_reserve_bytes=0))


def image_bytes(format="PNG"):
    stream = BytesIO()
    with Image.new("RGB", (60, 40), "red") as image:
        image.save(stream, format=format)
    return stream.getvalue()


def pdf_bytes(tmp_path, pages=2):
    path = tmp_path / "synthetic-pdf"
    with pdfium.PdfDocument.new() as document:
        for index in range(pages):
            document.new_page(72 + index, 144).close()
        document.save(path)
    return path.read_bytes()


class Transport:
    def __init__(self, payloads):
        self.payloads, self.calls = payloads, []
        self.gate = None
        self.active, self.maximum = 0, 0
        self.started = asyncio.Event()

    async def download(self, upload, sink):
        self.calls.append(upload.file_id)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            payload = self.payloads[upload.file_id]
            sink.write(payload[:8])
            self.started.set()
            if self.gate:
                await self.gate.wait()
            sink.write(payload[8:])
        finally:
            self.active -= 1


async def setup(tmp_path, payloads, **kwargs):
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0, backoff_s=0)
    await lifecycle.initialize()
    transport = Transport(payloads)
    manager = IntakeManager(lifecycle, transport, kwargs.pop("frozen", frozen()), **kwargs)
    return lifecycle, transport, manager


async def test_real_worker_all_pages_content_sniff_and_album_order_stable_binding(tmp_path):
    lifecycle, transport, manager = await setup(tmp_path,
        {"png": image_bytes(), "pdf": pdf_bytes(tmp_path), "jpeg": image_bytes("JPEG")})
    submission = manager.reserve(1, "job", 0, 1, mode="album", album_id="synthetic")
    try:
        async with supervise_children(lifecycle):
            jpeg = await manager.receive(submission, Upload("jpeg", None, True), message_id=30, update_id=1)
            pdf = await manager.receive(submission, Upload("pdf", 1), message_id=20, update_id=2)
            png = await manager.receive(submission, Upload("png", 1), message_id=10, update_id=3)
            ready = await manager.seal(submission)
            assert [f.kind for f in ready.files] == ["png", "pdf", "jpeg"]
            assert [p.file_index for p in ready.document.pages] == [0, 1, 1, 2]
            assert [p.file_page_index for p in ready.document.pages] == [0, 0, 1, 0]
            assert ready.page_bindings == ((png.file_key, 0), (pdf.file_key, 0), (pdf.file_key, 1), (jpeg.file_key, 0))
            assert ready.estimate_s == 40 and jpeg.compressed
            assert all(p.exists() for p in ready.paths)
            assert not lifecycle._processes
    finally:
        await manager.close()
    assert not submission.path.exists() and not manager.submissions


async def test_duplicate_pending_and_accepted_update_and_message_download_once(tmp_path):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    transport.gate = asyncio.Event()
    submission = manager.reserve(1, "job", 0, 1, mode="several")
    first = asyncio.create_task(manager.receive(submission, Upload("png", None), message_id=1, update_id=1))
    await transport.started.wait()
    duplicate = asyncio.create_task(manager.receive(submission, Upload("png", None), message_id=1, update_id=1))
    transport.gate.set()
    try:
        one, two = await asyncio.gather(first, duplicate)
        assert one is two
        assert await manager.receive(submission, Upload("png", None), message_id=1, update_id=2) is one
        assert transport.calls == ["png"] and len(submission.files) == 1
    finally:
        await manager.close()


async def test_cancel_partial_download_drain_preserves_accepted_and_replay_generation(tmp_path):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    submission = manager.reserve(1, "job", 4, 1, mode="album")
    accepted = await manager.receive(submission, Upload("png", None), message_id=1, update_id=1)
    transport.started.clear()
    transport.gate = asyncio.Event()
    pending = asyncio.create_task(manager.receive(submission, Upload("png", None), message_id=2, update_id=2))
    await transport.started.wait()
    manager.cancel_now(submission)
    assert submission.generation == 5
    with pytest.raises(IntakeError, match="operation_draining"):
        await manager.receive(submission, Upload("png", None), message_id=3, update_id=3)
    await manager.drain(submission)
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert submission.files == [accepted] and accepted.path.exists()
    assert len(list(submission.path.glob("original-*"))) == 1
    transport.gate = None
    await manager.receive(submission, Upload("png", None), message_id=3, update_id=3)
    ready = await manager.seal(submission, remaining_budget_s=20)
    assert ready.generation == 5 and ready.page_bindings[0] == (accepted.file_key, 0)
    await manager.close()


@pytest.mark.parametrize(("kind", "expected"), [("junk", "unsupported_format"), ("jpeg", "damaged_input"),
    ("pdf", "damaged_input"), ("pixels", "pixel_limit"), ("many", "processing_limit")])
async def test_worker_fixed_refusals_remove_failed_original_without_readers(tmp_path, kind, expected):
    payload = {"junk": b"not a document", "jpeg": image_bytes("JPEG")[:-25],
               "pdf": b"%PDF-1.7\ncorrupt", "pixels": image_bytes(), "many": pdf_bytes(tmp_path, pages=4)}[kind]
    lifecycle, transport, manager = await setup(tmp_path, {"input": payload},
        frozen=frozen(budget=30 if kind == "many" else 1800, pixels=10 if kind == "pixels" else 10000))
    submission = manager.reserve(1, "job", 0, 1, mode="several")
    try:
        with pytest.raises(IntakeError) as failure:
            await manager.receive(submission, Upload("input", None), message_id=1, update_id=1)
        assert failure.value.code == expected
        assert not submission.files and not list(submission.path.glob("original-*"))
    finally:
        await manager.close()


async def test_admission_pool_before_download_and_full_set_budget_no_truncation(tmp_path):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()}, admitted_jobs=1)
    submission = manager.reserve(1, "job", 0, 1, mode="several")
    try:
        with pytest.raises(IntakeError, match="busy"):
            manager.reserve(2, "second", 0, 2, mode="single")
        with pytest.raises(IntakeError, match="active_document"):
            manager.reserve(1, "third", 0, 3, mode="single")
        assert not transport.calls
        with pytest.raises(IntakeError, match="no_document"):
            await manager.seal(submission)
        for index in range(2):
            await manager.receive(submission, Upload("png", None), message_id=index + 1, update_id=index + 1)
        with pytest.raises(IntakeError, match="processing_limit"):
            await manager.seal(submission, remaining_budget_s=19)
        assert len(submission.files) == 2
    finally:
        await manager.close()


async def test_global_download_concurrency_and_fake_metadata_quota_refusal(tmp_path):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()}, download_limit=2)
    transport.gate = asyncio.Event()
    submissions = [manager.reserve(i, str(i), 0, i, mode="single") for i in range(1, 4)]
    tasks = [asyncio.create_task(manager.receive(s, Upload("png", 1), message_id=1, update_id=s.owner)) for s in submissions]
    await transport.started.wait()
    for _ in range(5):
        await asyncio.sleep(0)
    assert transport.maximum == 2 and len(transport.calls) == 2
    transport.gate.set()
    try:
        await asyncio.gather(*tasks)
        assert transport.maximum == 2
        lifecycle.quota_bytes = sum(p.stat().st_size for p in lifecycle.root.rglob("*") if p.is_file()) + 5
        with pytest.raises(IntakeError, match="storage_limit"):
            await manager.receive(submissions[0], Upload("png", 1), message_id=2, update_id=5)
    finally:
        await manager.close()


@pytest.mark.parametrize("case", ["timeout", "oversized_stdout", "spawn_cancel"])
async def test_parser_failure_and_cancel_kill_child_before_partial_cleanup(tmp_path, monkeypatch, case):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    submission = manager.reserve(1, "job", 0, 1, mode="single")
    original = asyncio.create_subprocess_exec
    processes, started, release = [], asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        code = ("import sys,time;sys.stdin.read();sys.stdout.write('x'*200000);sys.stdout.flush();time.sleep(30)"
                if case == "oversized_stdout" else "import time;time.sleep(30)")
        process = await original(sys.executable, "-u", "-c", code, **kwargs)
        processes.append(process)
        started.set()
        if case == "spawn_cancel":
            await release.wait()
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    manager.parser_timeout_s = .15
    task = asyncio.create_task(manager.receive(submission, Upload("png", None), message_id=1, update_id=1))
    await started.wait()
    if case == "spawn_cancel":
        manager.cancel_now(submission)
        # The in-progress spawn must finish before kill/wait and deletion.
        assert list(submission.path.glob("original-*"))
        release.set()
        await manager.drain(submission)
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(IntakeError) as failure:
            await task
        assert failure.value.code == ("parser_timeout" if case == "timeout" else "parser_failed")
    assert all(process.returncode is not None for process in processes)
    assert not submission.files and not list(submission.path.glob("original-*"))
    await manager.close()


async def test_generation_change_never_attaches_late_cancellation_resistant_metadata(tmp_path, monkeypatch):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    submission = manager.reserve(1, "job", 0, 1, mode="album")
    original = manager._inspect
    started, release = asyncio.Event(), asyncio.Event()
    async def inspect(path, root):
        metadata = await original(path, root)
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return metadata
    monkeypatch.setattr(manager, "_inspect", inspect)
    task = asyncio.create_task(manager.receive(submission, Upload("png", None), message_id=1, update_id=1))
    await started.wait()
    manager.cancel_now(submission)
    release.set()
    await manager.drain(submission)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not submission.files and not list(submission.path.glob("original-*"))
    await manager.close()


async def test_close_releases_slot_only_after_cleanup_and_unhealthy_refuses(tmp_path):
    healthy = [False]
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()}, healthy=lambda: healthy[0])
    with pytest.raises(IntakeError, match="temporarily_unavailable"):
        manager.reserve(1, "job", 0, 1, mode="single")
    assert not transport.calls
    healthy[0] = True
    submission = manager.reserve(1, "job", 0, 1, mode="single")
    await manager.receive(submission, Upload("png", None), message_id=1, update_id=1)
    await manager.close_submission(submission)
    assert not submission.path.exists() and 1 not in manager.submissions
    replacement = manager.reserve(1, "new", 0, 2, mode="single")
    assert replacement.path != submission.path
    await manager.close()


@pytest.mark.parametrize("password", ["synthetic-password", ""])
async def test_protected_pdf_refused_even_if_empty_user_password_opens(tmp_path, password):
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen.canvas import Canvas
    path = tmp_path / "synthetic-encrypted.pdf"
    canvas = Canvas(str(path), encrypt=StandardEncryption(password, ownerPassword="synthetic-owner"))
    canvas.drawString(10, 20, "Synthetic fixture")
    canvas.save()
    lifecycle, transport, manager = await setup(tmp_path, {"pdf": path.read_bytes()})
    submission = manager.reserve(1, "job", 0, 1, mode="single")
    try:
        with pytest.raises(IntakeError, match="encrypted_pdf"):
            await manager.receive(submission, Upload("pdf", None), message_id=1, update_id=1)
        assert not submission.files and not list(submission.path.glob("original-*"))
    finally:
        await manager.close()


async def test_cleanup_failure_retains_owned_files_closes_intake_then_retry_reopens(tmp_path, monkeypatch):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    lifecycle.attempts = 1
    submission = manager.reserve(1, "job", 0, 1, mode="single")
    await manager.receive(submission, Upload("png", None), message_id=1, update_id=1)
    original = lifecycle._delete
    async def locked(path):
        raise OSError("Synthetic lock")
    monkeypatch.setattr(lifecycle, "_delete", locked)
    assert not await manager.close_submission(submission)
    assert submission.path.exists() and not lifecycle.intake_available
    with pytest.raises(IntakeError, match="temporarily_unavailable"):
        manager.reserve(1, "another", 0, 2, mode="single")
    monkeypatch.setattr(lifecycle, "_delete", original)
    assert await lifecycle.retry_pending()
    assert not submission.path.exists()
    await manager.close()


async def test_download_read_error_is_content_free_and_partial_is_removed(tmp_path, monkeypatch):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    submission = manager.reserve(1, "job", 0, 1, mode="single")
    async def failed_read(upload, sink):
        sink.write(b"partial")
        raise ConnectionError("Synthetic remote detail must not escape")
    monkeypatch.setattr(transport, "download", failed_read)
    with pytest.raises(IntakeError) as failure:
        await manager.receive(submission, Upload("png", None), message_id=1, update_id=1)
    assert failure.value.code == str(failure.value) == "download_failed"
    assert not submission.files and not list(submission.path.glob("original-*"))
    await manager.close()


async def test_several_pages_preserves_pdf_positions_and_reorders_album_members(tmp_path):
    lifecycle, transport, manager = await setup(tmp_path, {"pdf": pdf_bytes(tmp_path), "png": image_bytes()})
    submission = manager.reserve(1, "job", 0, 1, mode="several")
    try:
        first = await manager.receive(submission, Upload("pdf", None), message_id=100, update_id=1)
        later = await manager.receive(submission, Upload("png", None, media_group_id="synthetic-album"),
                                      message_id=103, update_id=2)
        earlier = await manager.receive(submission, Upload("png", None, media_group_id="synthetic-album"),
                                        message_id=101, update_id=3)
        last = await manager.receive(submission, Upload("pdf", None), message_id=104, update_id=4)
        ready = await manager.seal(submission)
        assert ready.files == (first, earlier, later, last)
        assert earlier.album_id == later.album_id == "synthetic-album"
        assert ready.paths == (first.path, earlier.path, later.path, last.path)
        assert [page.file_index for page in ready.document.pages] == [0, 0, 1, 2, 3, 3]
        assert ready.page_bindings == ((first.file_key, 0), (first.file_key, 1),
            (earlier.file_key, 0), (later.file_key, 0), (last.file_key, 0), (last.file_key, 1))
        assert ready.estimate_s == 60
    finally:
        await manager.close()


async def test_native_disk_full_is_storage_error_in_manual_set(tmp_path, monkeypatch):
    lifecycle, transport, manager = await setup(tmp_path, {"png": image_bytes()})
    submission = manager.reserve(1, "job", 0, 1, mode="several")
    def disk_full(stream, chunk):
        raise OSError(errno.ENOSPC, "Synthetic disk full")
    monkeypatch.setattr(manager.quota, "write", disk_full)
    try:
        with pytest.raises(IntakeError) as failure:
            await manager.receive(submission, Upload("png", None), message_id=1, update_id=1)
        assert failure.value.code == "storage_limit"
        assert not submission.files and not list(submission.path.glob("original-*"))
    finally:
        await manager.close()
