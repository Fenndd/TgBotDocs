"""Real parser/render checks and kill-before-cleanup lifecycle checks (no GPU)."""
import asyncio
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sys
import struct
import zlib

from PIL import Image
import pypdfium2 as pdfium
import pytest

from tgbotdocs.recognition import preparation as prep


def limits(**changes):
    return prep.PreparationLimits(free_reserve_bytes=0, **changes)


def image_file(path, size=(60, 40), format="PNG", orientation=None):
    with Image.new("RGB", size, "red") as image:
        exif = Image.Exif()
        if orientation:
            exif[274] = orientation
        image.save(path, format=format, exif=exif)
    return path


def pdf_file(path, sizes=((72, 144), (144, 72))):
    with pdfium.PdfDocument.new() as document:
        for size in sizes:
            document.new_page(*size).close()
        document.save(path)
    return path


@pytest.fixture
def scratch(tmp_path):
    directory = tmp_path / "scratch"
    directory.mkdir()
    return directory


def inspect(files, scratch, policy=None):
    return asyncio.run(prep.inspect_document(tuple(files), scratch, policy or limits(), 15))


def assert_clean(scratch):
    assert not list(scratch.iterdir())


def test_indexes_every_page_across_content_sniffed_files_and_is_immutable(tmp_path, scratch):
    first = image_file(tmp_path / "image.pdf")
    second = pdf_file(tmp_path / "document.jpg")
    third = image_file(tmp_path / "photo.bin", format="JPEG")
    document = inspect([first, second, third], scratch)
    assert [(p.page_id, p.file_index, p.file_page_index, p.kind) for p in document.pages] == [
        (1, 0, 0, "png"), (2, 1, 0, "pdf"), (3, 1, 1, "pdf"), (4, 2, 0, "jpeg")]
    with pytest.raises(FrozenInstanceError):
        document.pages[0].page_id = 8
    assert_clean(scratch)
    assert all(p.exists() for p in (first, second, third))


def test_lazy_pdf_renders_only_selected_pages_and_removes_batch_on_exit(tmp_path, scratch):
    original = pdf_file(tmp_path / "document", ((72, 144), (144, 72), (216, 72)))
    document = inspect([original], scratch)
    assert_clean(scratch)

    async def scenario():
        async with prep.render_batch(document, (2,), 150, scratch=scratch, timeout_s=15) as pages:
            assert len(pages) == 1 and pages[0].page_id == 2
            assert (pages[0].width, pages[0].height) == (300, 150)
            assert len(list(pages[0].path.parent.iterdir())) == 1
            with Image.open(pages[0].path) as image:
                assert image.size == (300, 150)
            output = pages[0].path
        assert not output.exists()

    asyncio.run(scenario())
    assert original.exists()
    assert_clean(scratch)


def test_exif_orientation_and_whole_page_downscale(tmp_path, scratch):
    original = image_file(tmp_path / "oriented", (60, 40), "JPEG", orientation=6)
    document = inspect([original], scratch)
    assert (document.pages[0].width, document.pages[0].height) == (40, 60)

    async def scenario():
        async with prep.render_batch(document, (1,), 150, 30, scratch=scratch, timeout_s=15) as pages:
            assert (pages[0].width, pages[0].height) == (20, 30)
            with Image.open(pages[0].path) as image:
                assert image.getexif().get(274) is None
                assert image.getpixel((0, 0))[0] > 200

    asyncio.run(scenario())
    assert_clean(scratch)


def test_huge_pdf_is_downscaled_before_bitmap_allocation(tmp_path, scratch):
    original = pdf_file(tmp_path / "large", ((7200, 3600),))
    document = inspect([original], scratch, limits(max_pixels=10000))

    async def scenario():
        async with prep.render_batch(document, (1,), 200, 100, scratch=scratch, timeout_s=15) as pages:
            assert (pages[0].width, pages[0].height) == (100, 50)
        with pytest.raises(prep.PreparationError, match="pixel_limit"):
            async with prep.render_batch(document, (1,), 200, scratch=scratch, timeout_s=15):
                pytest.fail("oversized PDF must be refused")

    asyncio.run(scenario())
    assert_clean(scratch)


@pytest.mark.parametrize("payload,code", [(b"not an image", "unsupported_format"),
                                           (b"%PDF-1.7\nbroken", "damaged_input"),
                                           (b"\x89PNG\r\n\x1a\ninvalid", "damaged_input")])
def test_refuses_unsupported_and_damaged_inputs_with_content_free_codes(tmp_path, scratch, payload, code):
    path = tmp_path / "SECRET_ORIGINAL_NAME.png"
    path.write_bytes(payload)
    with pytest.raises(prep.PreparationError) as caught:
        inspect([path], scratch)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert path.name not in str(caught.value)
    assert_clean(scratch)


def test_refuses_configured_image_pixel_limit_even_with_downscale(tmp_path, scratch):
    original = image_file(tmp_path / "image", (100, 100))
    with pytest.raises(prep.PreparationError, match="pixel_limit"):
        inspect([original], scratch, limits(max_pixels=9999))
    assert_clean(scratch)


def test_default_pillow_bomb_warning_is_a_refusal_without_allocating_huge_image(tmp_path, scratch):
    original = image_file(tmp_path / "bomb", (2, 2))
    content = bytearray(original.read_bytes())
    content[16:24] = struct.pack(">II", 10000, 10000)
    content[29:33] = struct.pack(">I", zlib.crc32(content[12:29]))
    original.write_bytes(content)
    with pytest.raises(prep.PreparationError, match="pixel_limit"):
        inspect([original], scratch)
    assert_clean(scratch)


def test_encrypted_pdf_is_refused_even_when_empty_user_password_can_open(tmp_path, scratch):
    canvas_module = pytest.importorskip("reportlab.pdfgen.canvas")
    encryption = pytest.importorskip("reportlab.lib.pdfencrypt")
    for password in ("password", ""):
        path = tmp_path / f"encrypted-{len(password)}.pdf"
        canvas = canvas_module.Canvas(str(path), encrypt=encryption.StandardEncryption(password, ownerPassword="owner"))
        canvas.drawString(10, 20, "synthetic")
        canvas.save()
        with pytest.raises(prep.PreparationError, match="encrypted_pdf"):
            inspect([path], scratch)
    assert_clean(scratch)


@pytest.mark.parametrize("policy", [limits(quota_bytes=100), prep.PreparationLimits(free_reserve_bytes=2**63)])
def test_storage_limits_refuse_before_render_and_preserve_original(tmp_path, scratch, policy):
    original = pdf_file(tmp_path / "document")
    document = inspect([original], scratch, policy)

    async def scenario():
        with pytest.raises(prep.PreparationError, match="storage_limit"):
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=15):
                pytest.fail("quota violation must not produce a batch")

    asyncio.run(scenario())
    assert original.exists()
    assert_clean(scratch)


def test_quota_counts_existing_job_files(tmp_path, scratch):
    original = image_file(tmp_path / "original")
    retained = scratch / "retained.bin"
    retained.write_bytes(b"x" * 1000)
    document = inspect([original], scratch, limits(quota_bytes=1000))

    async def scenario():
        with pytest.raises(prep.PreparationError, match="storage_limit"):
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=15):
                pytest.fail()

    asyncio.run(scenario())
    assert retained.read_bytes() == b"x" * 1000
    assert list(scratch.iterdir()) == [retained]


def test_missing_path_symlink_and_linked_scratch_refused_without_touching_target(tmp_path, scratch):
    original = image_file(tmp_path / "original")
    with pytest.raises(prep.PreparationError, match="invalid_path"):
        inspect([tmp_path / "missing"], scratch)
    link = tmp_path / "linked"
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("Host has no symlink privilege")
    with pytest.raises(prep.PreparationError, match="invalid_path"):
        inspect([link], scratch)
    linked_scratch = tmp_path / "linked-scratch"
    linked_scratch.symlink_to(scratch, target_is_directory=True)
    with pytest.raises(prep.PreparationError, match="invalid_path"):
        inspect([original], linked_scratch)
    assert original.exists()
    assert_clean(scratch)


def test_tampered_document_metadata_and_invalid_page_requests_refused(tmp_path, scratch):
    original = image_file(tmp_path / "original")
    document = inspect([original], scratch)
    bad = replace(document, pages=(replace(document.pages[0], file_index=999),))

    async def scenario():
        for ids in ((0,), (2,), (1, 1), ()):
            with pytest.raises(prep.PreparationError, match="invalid_request"):
                async with prep.render_batch(document, ids, 150, scratch=scratch, timeout_s=15):
                    pytest.fail()
        with pytest.raises(prep.PreparationError, match="invalid_request"):
            async with prep.render_batch(bad, (1,), 150, scratch=scratch, timeout_s=15):
                pytest.fail()

    asyncio.run(scenario())
    assert_clean(scratch)


def slow_worker(monkeypatch, marker):
    script = ("import json,sys,time;from pathlib import Path;"
              "r=json.load(sys.stdin);p=Path(r['owned'])/'partial.png';"
              "f=p.open('wb');f.write(b'private partial data');f.flush();"
              f"Path({str(marker)!r}).write_text('ready');time.sleep(120)")
    monkeypatch.setattr(prep, "_worker_command", lambda: (sys.executable, "-u", "-c", script))
    real_spawn = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(prep.asyncio, "create_subprocess_exec", spawn)
    return processes


def test_timeout_kills_and_waits_worker_before_partial_cleanup(tmp_path, scratch, monkeypatch):
    original = image_file(tmp_path / "original")
    document = inspect([original], scratch)
    marker = tmp_path / "ready"
    processes = slow_worker(monkeypatch, marker)

    async def scenario():
        with pytest.raises(prep.PreparationError, match="worker_timeout"):
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=1):
                pytest.fail()
        assert processes and processes[0].returncode is not None

    asyncio.run(scenario())
    assert marker.exists()
    assert original.exists()
    assert_clean(scratch)


def test_cancellation_kills_and_waits_worker_before_partial_cleanup(tmp_path, scratch, monkeypatch):
    original = image_file(tmp_path / "original")
    document = inspect([original], scratch)
    marker = tmp_path / "ready"
    processes = slow_worker(monkeypatch, marker)

    async def scenario():
        async def render():
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=30):
                pytest.fail()
        task = asyncio.create_task(render())
        async with asyncio.timeout(10):
            while not marker.exists():  # noqa: ASYNC110 - observe a marker from a separate OS process
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None

    asyncio.run(scenario())
    assert original.exists()
    assert_clean(scratch)


def test_consumer_exception_and_cancellation_cleanup_rendered_batch(tmp_path, scratch):
    original = image_file(tmp_path / "original")
    document = inspect([original], scratch)

    async def scenario():
        with pytest.raises(ValueError):
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=15):
                raise ValueError("consumer failure")
        with pytest.raises(asyncio.CancelledError):
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=15):
                raise asyncio.CancelledError()

    asyncio.run(scenario())
    assert original.exists()
    assert_clean(scratch)


def test_worker_crash_emits_fixed_error_and_removes_owned_directory(tmp_path, scratch, monkeypatch):
    original = image_file(tmp_path / "original")
    script = "import sys;sys.stderr.write('private document content');sys.exit(9)"
    monkeypatch.setattr(prep, "_worker_command", lambda: (sys.executable, "-c", script))
    with pytest.raises(prep.PreparationError) as caught:
        inspect([original], scratch)
    assert str(caught.value) == "worker_failed"
    assert original.exists()
    assert_clean(scratch)


def test_cleanup_failure_is_reported_and_never_removes_caller_files(tmp_path, scratch, monkeypatch):
    original = image_file(tmp_path / "original")
    document = inspect([original], scratch)
    real_unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path.name == "page-1.png":
            raise PermissionError("locked synthetic output")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)

    async def scenario():
        with pytest.raises(prep.PreparationError, match="cleanup_failed"):
            async with prep.render_batch(document, (1,), 150, scratch=scratch, timeout_s=15):
                pass

    asyncio.run(scenario())
    assert original.exists()
    assert len(list(scratch.iterdir())) == 1
