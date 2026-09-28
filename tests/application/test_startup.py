import asyncio

import pytest

from tgbotdocs.application.bootstrap import prepare_runtime_temp, resources
from tgbotdocs.application.config import ConfigurationError
from tgbotdocs.application.instance import instance_lock
from tgbotdocs.application.lifecycle import TemporaryLifecycle
from tgbotdocs.application.maintenance import cleanup_sweep, stop_task


def test_second_instance_is_refused_without_waiting_or_cleanup(tmp_path):
    path = tmp_path / "instance.lock"
    with instance_lock(path):
        with pytest.raises(ConfigurationError, match="already_running"):
            with instance_lock(path):
                pass
    with instance_lock(path):
        pass


def test_owned_runtime_keys_removed_and_unknown_files_preserved(tmp_path):
    directory = prepare_runtime_temp(tmp_path)
    key = directory / "tgbotdocs-runtime-key-synthetic"
    key.write_text("synthetic-key")
    prepare_runtime_temp(tmp_path)
    assert not key.exists()
    unknown = directory / "unknown.txt"
    unknown.write_text("keep-this")
    with pytest.raises(ConfigurationError, match="unowned_runtime"):
        prepare_runtime_temp(tmp_path)
    assert unknown.read_text() == "keep-this"


async def test_cleanup_precedes_missing_token_and_database_checks(tmp_path):
    directory = tmp_path / "temporary"
    lifecycle = TemporaryLifecycle(directory, free_reserve_bytes=0)
    await lifecycle.initialize()
    job = lifecycle.create_job("synthetic")
    await asyncio.to_thread((job / "original").write_text, "synthetic-leftover")
    config = tmp_path / "incomplete.env"
    await asyncio.to_thread(config.write_text, f"DATA_ROOT={tmp_path}\nTEMPORARY_ROOT={directory}\n")
    with pytest.raises(ConfigurationError):
        async with resources(config):
            pass
    assert not job.exists()


async def test_automatic_sweep_reopens_intake_after_transient_lock(tmp_path, monkeypatch):
    reopened = asyncio.Event()

    async def alert(code):
        if code == "intake_reopened":
            reopened.set()

    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0, attempts=1,
                                   backoff_s=0, alert=alert)
    await lifecycle.initialize()
    job = lifecycle.create_job("synthetic")
    original_remove = lifecycle._remove_job
    locked = True

    def remove(path):
        if locked:
            raise PermissionError("synthetic lock")
        original_remove(path)

    monkeypatch.setattr(lifecycle, "_remove_job", remove)
    assert not await lifecycle.cleanup_job(job) and not lifecycle.intake_available
    task = asyncio.create_task(cleanup_sweep(lifecycle, interval_s=.005))
    try:
        locked = False
        async with asyncio.timeout(2):
            await reopened.wait()
        assert not job.exists()
    finally:
        await stop_task(task)
