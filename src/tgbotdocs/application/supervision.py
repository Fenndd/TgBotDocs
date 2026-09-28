"""Bind subprocesses to the application and record safe crash identities."""

import asyncio
from contextlib import asynccontextmanager
import os

from tgbotdocs.recognition.runtime import WindowsJob


def _parent_death():
    """Executed before exec on Linux; kill the child if its parent has exited."""
    import ctypes
    import signal

    parent = os.getppid()
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL) != 0:
        os._exit(126)
    if os.getppid() != parent or parent == 1:
        os._exit(126)


@asynccontextmanager
async def supervise_children(lifecycle):
    """Application-scoped spawn seam; frozen recognition files stay unchanged."""
    original = asyncio.create_subprocess_exec
    job = WindowsJob() if os.name == "nt" else None
    children = set()
    watchers = set()

    async def watch(process):
        await process.wait()
        lifecycle.forget_process(process.pid)
        children.discard(process)

    async def spawn(*args, **kwargs):
        if os.name != "nt":
            kwargs["preexec_fn"] = _parent_death
        task = asyncio.create_task(original(*args, **kwargs))
        try:
            process = await asyncio.shield(task)
        except asyncio.CancelledError:
            process = await task
            process.kill()
            await process.wait()
            raise
        try:
            if job:
                job.assign(process.pid)
            lifecycle.register_process(process.pid)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        children.add(process)
        watcher = asyncio.create_task(watch(process))
        watchers.add(watcher)
        watcher.add_done_callback(watchers.discard)
        return process

    asyncio.create_subprocess_exec = spawn
    try:
        yield
    finally:
        asyncio.create_subprocess_exec = original
        if job:
            job.close()
        for process in tuple(children):
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
        await asyncio.gather(*tuple(watchers), return_exceptions=True)
