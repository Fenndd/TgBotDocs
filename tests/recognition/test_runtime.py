import asyncio
import os
from pathlib import Path
import sys

import pytest

from tgbotdocs.recognition.runtime import LocalRuntime, RuntimeFiles, RuntimeProfile, WindowsJob


def runtime():
    return LocalRuntime(RuntimeFiles(Path("unused"), Path("unused"), Path("unused")), RuntimeProfile())


async def test_stop_waits_for_concurrent_start_instead_of_leaving_late_child(monkeypatch):
    server = runtime()
    entered, finish = asyncio.Event(), asyncio.Event()
    events = []

    async def start():
        entered.set()
        await finish.wait()
        events.append("started")

    async def stop():
        events.append("stopped")

    monkeypatch.setattr(server, "_start", start)
    monkeypatch.setattr(server, "_stop", stop)
    starter = asyncio.create_task(server.start())
    await entered.wait()
    stopper = asyncio.create_task(server.stop())
    await asyncio.sleep(0)
    assert not stopper.done()
    finish.set()
    await asyncio.gather(starter, stopper)
    assert events == ["started", "stopped"]


async def test_cancelled_restart_finishes_stop_and_does_not_start_new_child(monkeypatch):
    server = runtime()
    entered, finish = asyncio.Event(), asyncio.Event()
    events = []

    async def stop():
        entered.set()
        await finish.wait()
        events.append("stopped")

    async def start():
        events.append("started")

    monkeypatch.setattr(server, "_start", start)
    monkeypatch.setattr(server, "_stop", stop)
    task = asyncio.create_task(server.restart())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["stopped"]


async def test_repeated_cancel_during_stop_waits_until_cleanup_finishes(monkeypatch):
    server = runtime()
    entered, finish, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stop():
        entered.set()
        await finish.wait()
        stopped.set()

    monkeypatch.setattr(server, "_stop", stop)
    task = asyncio.create_task(server.stop())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    assert not stopped.is_set()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel behavior")
async def test_windows_job_close_terminates_owned_process():
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")
    job = WindowsJob()
    try:
        job.assign(process.pid)
        job.close()
        await asyncio.wait_for(process.wait(), 5)
        assert process.returncode is not None
    finally:
        job.close()
        if process.returncode is None:
            process.kill()
            await process.wait()
