import asyncio
import json
import os
import subprocess
import sys

import psutil
import pytest

from tgbotdocs.application.lifecycle import TemporaryLifecycle
from tgbotdocs.application.supervision import supervise_children


async def test_supervised_child_stops_and_identity_is_cleared(tmp_path):
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await lifecycle.initialize()
    async with supervise_children(lifecycle):
        child = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")
        identity = json.loads((lifecycle.root / ".tgbotdocs-processes.json").read_text())
        assert str(child.pid) in identity
    assert not psutil.pid_exists(child.pid)
    assert json.loads((lifecycle.root / ".tgbotdocs-processes.json").read_text()) == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows kill-on-close verification")
def test_hard_parent_kill_stops_child_and_startup_cleans_leftovers(tmp_path):
    root = tmp_path / "temporary"
    code = '''
import asyncio,sys
from pathlib import Path
from tgbotdocs.application.lifecycle import TemporaryLifecycle
from tgbotdocs.application.supervision import supervise_children
async def main():
    lifecycle=TemporaryLifecycle(Path(sys.argv[1]),free_reserve_bytes=0)
    await lifecycle.initialize()
    directory=lifecycle.create_job('synthetic')
    (directory/'original').write_text('synthetic-temporary')
    async with supervise_children(lifecycle):
        child=await asyncio.create_subprocess_exec(sys.executable,'-c','import time; time.sleep(120)')
        print(child.pid,flush=True)
        await asyncio.sleep(120)
asyncio.run(main())
'''
    parent = subprocess.Popen([sys.executable, "-c", code, str(root)], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        child_pid = int(parent.stdout.readline().strip())
        child = psutil.Process(child_pid)
        parent.kill()
        parent.wait(timeout=10)
        child.wait(timeout=10)
        assert not psutil.pid_exists(child_pid)
        lifecycle = TemporaryLifecycle(root, free_reserve_bytes=0)
        asyncio.run(lifecycle.initialize())
        assert not list(root.glob("job-*"))
        assert json.loads((root / ".tgbotdocs-processes.json").read_text()) == {}
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=10)
        parent.stdout.close()
