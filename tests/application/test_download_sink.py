from types import SimpleNamespace

import pytest

from tgbotdocs.application.download_sink import DownloadError, DownloadSink, FILE_LIMIT, QuotaCoordinator
from tgbotdocs.application.lifecycle import LifecycleError
from tgbotdocs.application.transport import TelegramTransport, Upload


def test_actual_limit_checked_before_write_and_no_memory_buffer(tmp_path):
    checks = []
    coordinator = QuotaCoordinator(SimpleNamespace(check_capacity=checks.append))
    target = tmp_path / "owned"
    with DownloadSink(target, coordinator, limit_bytes=5) as sink:
        sink.write(b"123")
        with pytest.raises(DownloadError, match="file_too_large"):
            sink.write(b"456")
        assert sink.written == 3 and target.read_bytes() == b"123"
    assert checks == [3]
    assert sink.closed


def test_shared_physical_quota_check_write_is_atomic_between_sinks(tmp_path):
    def capacity(extra):
        if sum(p.stat().st_size for p in tmp_path.iterdir()) + extra > 7:
            raise LifecycleError("storage_limit")
    coordinator = QuotaCoordinator(SimpleNamespace(check_capacity=capacity))
    with DownloadSink(tmp_path / "a", coordinator) as first, DownloadSink(tmp_path / "b", coordinator) as second:
        first.write(b"1234")
        second.write(b"567")
        with pytest.raises(LifecycleError, match="storage_limit"):
            first.write(b"8")
        assert (tmp_path / "a").read_bytes() == b"1234"
        assert (tmp_path / "b").read_bytes() == b"567"


async def test_transport_download_uses_binary_sink_and_never_seeks(tmp_path):
    class Bot:
        async def get_file(self, identifier):
            return SimpleNamespace(file_path="remote", file_size=1)

        async def download_file(self, path, *, destination, seek):
            assert not seek and path == "remote"
            destination.write(b"actual")
    transport = TelegramTransport(Bot())
    coordinator = QuotaCoordinator(SimpleNamespace(check_capacity=lambda _: None))
    with DownloadSink(tmp_path / "a", coordinator, limit_bytes=5) as sink:
        with pytest.raises(DownloadError, match="file_too_large"):
            await transport.download(Upload("synthetic", 1), sink)
    with DownloadSink(tmp_path / "b", coordinator) as sink:
        with pytest.raises(DownloadError, match="file_too_large"):
            await transport.download(Upload("synthetic", FILE_LIMIT + 1), sink)


def test_standard_twenty_mib_boundary_cannot_be_bypassed_by_many_chunks(tmp_path):
    target = tmp_path / "owned"
    coordinator = QuotaCoordinator(SimpleNamespace(check_capacity=lambda _: None))
    with DownloadSink(target, coordinator) as sink:
        for _ in range(FILE_LIMIT // 65536):
            sink.write(b"x" * 65536)
        assert sink.written == FILE_LIMIT
        with pytest.raises(DownloadError, match="file_too_large"):
            sink.write(b"x")
    assert target.stat().st_size == FILE_LIMIT


def test_failed_constructor_has_safe_close_without_unraisable_finalizer(tmp_path):
    coordinator = QuotaCoordinator(SimpleNamespace(check_capacity=lambda _: None))
    sink = DownloadSink.__new__(DownloadSink)
    with pytest.raises(DownloadError, match="storage_limit"):
        sink.__init__(tmp_path / "missing" / "original", coordinator)
    sink.flush()
    sink.close()
    assert sink.closed and sink._stream is None


def test_native_write_error_preserves_close_and_does_not_charge_bytes(tmp_path, monkeypatch):
    coordinator = QuotaCoordinator(SimpleNamespace(check_capacity=lambda _: None))
    with DownloadSink(tmp_path / "owned", coordinator) as sink:
        def failed_write(stream, chunk):
            raise OSError("Synthetic write failure")
        monkeypatch.setattr(coordinator, "write", failed_write)
        with pytest.raises(DownloadError, match="storage_limit"):
            sink.write(b"synthetic")
        assert sink.written == 0
    assert sink.closed
