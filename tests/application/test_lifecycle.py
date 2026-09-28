import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tgbotdocs.application.lifecycle import LifecycleError, TemporaryLifecycle


async def test_capacity_io_failure_is_controlled_without_creating_a_partial_job(tmp_path, monkeypatch):
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await lifecycle.initialize()
    original = lifecycle._fits

    def unavailable(extra):
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(lifecycle, "_fits", unavailable)
    with pytest.raises(LifecycleError, match="storage_limit"):
        lifecycle.create_job("synthetic")
    assert not list(lifecycle.root.glob("job-*"))
    assert not (lifecycle.root / ".tgbotdocs-create.json").exists()
    monkeypatch.setattr(lifecycle, "_fits", original)
    job = lifecycle.create_job("synthetic")
    assert await lifecycle.cleanup_job(job)


async def test_restart_sweeps_only_owned_random_jobs_before_dependencies(tmp_path):
    root = tmp_path / "temporary"
    first = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await first.initialize()
    job_a = first.create_job("../../unsafe-name")
    job_b = first.create_job("same")
    assert job_a.parent == root and job_a.name != job_b.name
    (job_a / "original.png").write_bytes(b"synthetic-original")
    (job_b / "pages").mkdir()
    (job_b / "pages" / "page.png").write_bytes(b"synthetic-render")
    restarted = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await restarted.initialize()
    assert not job_a.exists() and not job_b.exists()
    assert restarted.intake_available


async def test_unowned_nonempty_root_and_foreign_job_fail_closed(tmp_path):
    root = tmp_path / "foreign"
    root.mkdir()
    evidence = root / "unowned.txt"
    evidence.write_text("preserve")
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await service.initialize()
    assert evidence.read_text() == "preserve" and not service.intake_available
    own = TemporaryLifecycle(tmp_path / "own", free_reserve_bytes=0)
    await own.initialize()
    assert not await own.cleanup_job(root)
    assert evidence.exists() and not own.intake_available


async def test_cleanup_retry_then_closure_then_reopen(tmp_path, monkeypatch):
    alerts = []

    async def alert(code):
        alerts.append(code)

    service = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0,
                                 attempts=2, backoff_s=0, alert=alert)
    await service.initialize()
    job = service.create_job("job")
    (job / "document").write_bytes(b"synthetic")
    remove = service._remove_job
    calls = []

    def locked(path):
        calls.append(path)
        raise PermissionError("synthetic-lock")

    monkeypatch.setattr(service, "_remove_job", locked)
    assert not await service.cleanup_job(job)
    assert len(calls) == 2 and job.exists() and not service.intake_available
    with pytest.raises(LifecycleError, match="temporary_unavailable"):
        service.create_job("new")
    monkeypatch.setattr(service, "_remove_job", remove)
    assert await service.retry_pending()
    assert not job.exists() and alerts == ["intake_closed", "intake_reopened"]
    assert await service.retry_pending()
    assert alerts == ["intake_closed", "intake_reopened"]


async def test_partial_deletion_preserves_ownership_and_retries(tmp_path, monkeypatch):
    service = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0, attempts=1)
    await service.initialize()
    job = service.create_job("job")
    first, locked = job / "a", job / "b"
    first.write_bytes(b"one")
    locked.write_bytes(b"two")
    original_unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path == locked:
            raise PermissionError("locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    assert not await service.cleanup_job(job)
    assert (job / ".tgbotdocs-job.json").is_file()
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert await service.retry_pending()
    assert not job.exists()


async def test_total_quota_and_free_disk_reserve(tmp_path, monkeypatch):
    service = TemporaryLifecycle(tmp_path / "temporary", quota_bytes=1000, free_reserve_bytes=0)
    await service.initialize()
    job = service.create_job("job")
    (job / "file").write_bytes(b"x" * 800)
    with pytest.raises(LifecycleError, match="storage_limit"):
        service.check_capacity(400)
    service.free_reserve_bytes = 100
    monkeypatch.setattr("tgbotdocs.application.lifecycle.shutil.disk_usage",
                        lambda _: type("Usage", (), {"free": 105})())
    with pytest.raises(LifecycleError, match="storage_limit"):
        service.check_capacity(6)


async def test_registered_orphan_is_terminated_and_recycled_pid_is_preserved(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = await asyncio.to_thread(subprocess.Popen,
                                     [sys.executable, "-c", "import time; time.sleep(60)"], **options)
    try:
        service.register_process(process.pid)
        restarted = TemporaryLifecycle(root, free_reserve_bytes=0)
        assert await restarted.initialize()
        assert await asyncio.to_thread(process.wait, 5) is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    other = await asyncio.to_thread(subprocess.Popen,
                                   [sys.executable, "-c", "import time; time.sleep(60)"], **options)
    try:
        restarted.register_process(other.pid)
        manifest = root / ".tgbotdocs-processes.json"
        data = json.loads(manifest.read_text())
        data[str(other.pid)]["created"] += 1
        manifest.write_text(json.dumps(data))
        next_start = TemporaryLifecycle(root, free_reserve_bytes=0)
        assert await next_start.initialize()
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


async def test_process_registration_rejects_nonchild_and_forget_persists(tmp_path):
    service = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await service.initialize()
    with pytest.raises(LifecycleError, match="process_not_owned"):
        service.register_process(os.getpid())
    service.forget_process(123456)
    assert json.loads((service.root / ".tgbotdocs-processes.json").read_text()) == {}


async def test_job_marker_tampering_preserves_data_and_alerts(tmp_path):
    alerts = []

    async def alert(code):
        alerts.append(code)

    service = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0, alert=alert)
    await service.initialize()
    job = service.create_job("job")
    (job / ".tgbotdocs-job.json").write_text('{"owner":"other"}')
    content = job / "file"
    content.write_text("keep")
    assert not await service.cleanup_job(job)
    assert content.exists() and not service.intake_available
    assert alerts == ["temporary_ownership_failed"]


async def test_root_symlink_is_rejected_without_following(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    with pytest.raises(LifecycleError, match="unsafe_temporary_root"):
        TemporaryLifecycle(link)


async def test_dangling_job_symlink_is_not_reported_as_removed(tmp_path):
    service = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await service.initialize()
    link = service.root / "job-dangling"
    try:
        link.symlink_to(tmp_path / "absent", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    assert not await service.cleanup_job(link)
    assert link.is_symlink() and not service.intake_available


async def test_process_atomic_sidecar_recovers_and_does_not_block_job_cleanup(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    job = service.create_job("job")
    (job / "document").write_text("synthetic")
    staged = root / ".tgbotdocs-processes.json.writing"
    staged.write_text("{}")
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await restart.initialize()
    assert not staged.exists() and not job.exists()
    assert json.loads((root / ".tgbotdocs-processes.json").read_text()) == {}


async def test_staged_process_identity_is_preserved_alongside_committed_identity(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    children = []
    try:
        for _ in range(2):
            child = await asyncio.to_thread(subprocess.Popen,
                                            [sys.executable, "-c", "import time; time.sleep(60)"], **options)
            children.append(child)
            service.register_process(child.pid)
        records = service._processes
        (root / ".tgbotdocs-processes.json").write_text(json.dumps(
            {str(children[0].pid): records[str(children[0].pid)]}))
        (root / ".tgbotdocs-processes.json.writing").write_text(json.dumps(
            {str(children[1].pid): records[str(children[1].pid)]}))
        restart = TemporaryLifecycle(root, free_reserve_bytes=0)
        assert await restart.initialize()
        for child in children:
            assert await asyncio.to_thread(child.wait, 5) is not None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


async def test_invalid_staged_manifest_is_preserved_and_no_process_is_terminated(tmp_path, monkeypatch):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    valid = {"pid": 999999, "created": 1.0, "executable": sys.executable}
    (root / ".tgbotdocs-processes.json").write_text(json.dumps({"999999": valid}))
    staged = root / ".tgbotdocs-processes.json.writing"
    staged.write_text('{"invalid":{"pid":-1}}')
    calls = []
    monkeypatch.setattr("tgbotdocs.application.lifecycle.psutil.Process", lambda pid: calls.append(pid))
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await restart.initialize()
    assert not calls and staged.exists() and not restart.intake_available


async def test_entire_committed_manifest_is_validated_before_termination(tmp_path, monkeypatch):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    records = {"999999": {"pid": 999999, "created": 1.0,
                          "executable": sys.executable}, "invalid": {"pid": -1}}
    (root / ".tgbotdocs-processes.json").write_text(json.dumps(records))
    calls = []
    monkeypatch.setattr("tgbotdocs.application.lifecycle.psutil.Process", lambda pid: calls.append(pid))
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await TemporaryLifecycle(root, free_reserve_bytes=0).initialize()
    assert not calls


async def test_interrupted_initial_root_marker_and_job_marker_are_recovered(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    job = service.create_job("job")
    (job / "document").write_text("synthetic")
    for marker in [root / ".tgbotdocs-owner.json", job / ".tgbotdocs-job.json"]:
        marker.replace(marker.with_name(marker.name + ".writing"))
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await restart.initialize()
    assert not job.exists() and (root / ".tgbotdocs-owner.json").exists()
    assert not (root / ".tgbotdocs-owner.json.writing").exists()


async def test_job_creation_intent_recovers_crash_after_mkdir(tmp_path, monkeypatch):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    write = service._write

    def interrupted(path, data):
        if path.name == ".tgbotdocs-job.json":
            path.with_name(path.name + ".writing").write_text('{"owner":')
            raise OSError("synthetic_crash")
        write(path, data)

    monkeypatch.setattr(service, "_write", interrupted)
    with pytest.raises(LifecycleError, match="job_creation_failed"):
        service.create_job("job")
    assert not service.intake_available
    job = next(root.glob("job-*"))
    (job / "document").write_text("synthetic")
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await restart.initialize()
    assert not job.exists() and not (root / ".tgbotdocs-create.json").exists()


async def test_job_creation_intent_sidecar_recovers_before_mkdir(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    staged = root / ".tgbotdocs-create.json.writing"
    staged.write_text(json.dumps({"owner": service._owner, "directory": "job-" + "a" * 32}))
    assert await TemporaryLifecycle(root, free_reserve_bytes=0).initialize()
    assert not staged.exists() and not (root / ".tgbotdocs-create.json").exists()


async def test_unmarked_directory_without_creation_intent_is_preserved(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    unknown = root / ("job-" + "b" * 32)
    unknown.mkdir()
    content = unknown / "preserve"
    content.write_text("foreign")
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await TemporaryLifecycle(root, free_reserve_bytes=0).initialize()
    assert content.read_text() == "foreign"


async def test_conflicting_owner_sidecar_is_preserved(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    data = json.loads((root / ".tgbotdocs-owner.json").read_text())
    data["owner"] = "0" * 32 if data["owner"] != "0" * 32 else "1" * 32
    staged = root / ".tgbotdocs-owner.json.writing"
    staged.write_text(json.dumps(data))
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await TemporaryLifecycle(root, free_reserve_bytes=0).initialize()
    assert staged.exists()


async def test_deletion_intent_recovers_crash_between_marker_removal_and_rmdir(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    job = service.create_job("job")
    (root / ".tgbotdocs-delete.json.writing").write_text(json.dumps(
        {"owner": service._owner, "directory": job.name}))
    (job / ".tgbotdocs-job.json").unlink()
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await restart.initialize()
    assert not job.exists() and not (root / ".tgbotdocs-delete.json").exists()
    assert not (root / ".tgbotdocs-delete.json.writing").exists()


@pytest.mark.parametrize("partial", ["", "{", '{"999999":', '{"999999":{"executable":"C:\\'])
async def test_partial_process_sidecar_under_committed_ownership_does_not_leak_jobs(tmp_path, partial):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    service.forget_process(123456)  # a valid committed empty process manifest
    job = service.create_job("job")
    (job / "original").write_text("synthetic-private-content")
    staged = root / ".tgbotdocs-processes.json.writing"
    staged.write_text(partial)
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    assert await restart.initialize()
    assert not job.exists() and not staged.exists()
    assert json.loads((root / ".tgbotdocs-processes.json").read_text()) == {}


@pytest.mark.parametrize("committed", [None, '{"bad":{"pid":-1}}'])
async def test_partial_process_sidecar_without_valid_committed_manifest_remains_closed(tmp_path, committed):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    if committed is not None:
        (root / ".tgbotdocs-processes.json").write_text(committed)
    staged = root / ".tgbotdocs-processes.json.writing"
    staged.write_text("{")
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await restart.initialize()
    assert staged.exists() and not restart.intake_available


async def test_initial_partial_owner_marker_has_no_ownership_proof_and_is_preserved(tmp_path):
    root = tmp_path / "temporary"
    root.mkdir()
    staged = root / ".tgbotdocs-owner.json.writing"
    staged.write_text("{")
    restart = TemporaryLifecycle(root, free_reserve_bytes=0)
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await restart.initialize()
    assert staged.exists() and not restart.intake_available


async def test_nontruncated_process_sidecar_syntax_corruption_is_preserved(tmp_path):
    root = tmp_path / "temporary"
    service = TemporaryLifecycle(root, free_reserve_bytes=0)
    await service.initialize()
    service.forget_process(123456)
    staged = root / ".tgbotdocs-processes.json.writing"
    staged.write_text('{"bad": @}')
    with pytest.raises(LifecycleError, match="temporary_startup_failed"):
        await TemporaryLifecycle(root, free_reserve_bytes=0).initialize()
    assert staged.exists()
