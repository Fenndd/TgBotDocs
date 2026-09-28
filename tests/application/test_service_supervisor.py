import asyncio
from types import SimpleNamespace

import pytest

from tgbotdocs.application import service
from tgbotdocs.application.bootstrap import configured_runtime_files
from tgbotdocs.application.config import ConfigurationError


async def test_supervision_retries_startup_and_runtime_failures_then_stops(monkeypatch, caplog):
    attempts, delays = [], []

    async def serve(source):
        attempts.append(source)
        if len(attempts) < 3:
            raise RuntimeError("synthetic-private-url-and-token")

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(service, "serve", serve)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    await service.supervised_serve("external.env")
    assert attempts == ["external.env"] * 3
    assert delays == [60.0, 60.0]
    assert "synthetic-private" not in caplog.text
    assert caplog.text.count("service_retry_scheduled") == 2


@pytest.mark.parametrize("during_retry", [False, True])
async def test_supervision_cancellation_never_restarts(monkeypatch, during_retry):
    attempts = []

    async def serve(source):
        attempts.append(source)
        if during_retry:
            raise RuntimeError("synthetic failure")
        raise asyncio.CancelledError

    async def sleep(delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(service, "serve", serve)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await service.supervised_serve("external.env")
    assert attempts == ["external.env"]


def test_runtime_relocation_requires_the_calibrated_binary(tmp_path):
    frozen = SimpleNamespace(runtime_artifacts=SimpleNamespace(executable_sha256="a" * 64))
    cfg = SimpleNamespace(data_root=tmp_path, runtime_executable=tmp_path / "relocated.exe",
                          runtime_executable_sha256="b" * 64)
    with pytest.raises(ConfigurationError, match="runtime_executable_differs_from_frozen_recalibrate"):
        configured_runtime_files(cfg, frozen)
    cfg.runtime_executable_sha256 = "a" * 64
    files = configured_runtime_files(cfg, frozen)
    assert files.executable == cfg.runtime_executable and files.executable_sha256 == "a" * 64


def test_check_rejects_service_restart_flag(monkeypatch):
    from tgbotdocs.__main__ import main

    monkeypatch.setattr("sys.argv", ["tgbotdocs", "check", "--restart-on-failure"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
