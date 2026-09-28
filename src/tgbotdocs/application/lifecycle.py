"""Owned temporary storage, crash cleanup, and content-free process identity."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import secrets
import shutil

import psutil


class LifecycleError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _safe_path(path):
    path = Path(path)
    if not path.is_absolute() or len(path.parts) < 3:
        raise LifecycleError("unsafe_temporary_root")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise LifecycleError("unsafe_temporary_root")
    if path.resolve() != path.absolute():
        raise LifecycleError("unsafe_temporary_root")
    return path


class TemporaryLifecycle:
    """Never deletes an unmarked root or a job owned by another root.

    initialize runs before database/model checks and long polling. Deletion
    exhaustion closes intake; retry_pending is called by the minute sweep and
    reopens it only after every owned leftover is removed.

    An interrupted initial ownership marker has no committed ownership proof.
    It is preserved fail-closed and requires operator inspection/manual recovery;
    the service never assumes an unmarked directory is disposable.
    """

    def __init__(self, root, *, quota_bytes=2 * 1024**3, free_reserve_bytes=2 * 1024**3,
                 alert=None, attempts=5, backoff_s=4):
        self.root = _safe_path(root)
        if type(quota_bytes) is not int or quota_bytes < 1 or type(free_reserve_bytes) is not int or (
            free_reserve_bytes < 0
        ) or type(attempts) is not int or attempts < 1 or backoff_s < 0:
            raise ValueError("invalid_temporary_limits")
        self.quota_bytes, self.free_reserve_bytes = quota_bytes, free_reserve_bytes
        self.alert, self.attempts, self.backoff_s = alert, attempts, backoff_s
        self._owner = None
        self._pending: set[Path] = set()
        self._unsafe = False
        self._processes: dict[str, dict] = {}
        self._reserved: dict[object, int] = {}
        self._cleanup_lock = asyncio.Lock()

    @property
    def intake_available(self):
        return self._owner is not None and not self._pending and not self._unsafe

    async def _alert(self, code):
        if self.alert is not None:
            try:
                await self.alert(code)
            except Exception:
                # Alert delivery cannot undo the fail-closed cleanup outcome.
                pass

    def _read(self, path):
        _safe_path(path)
        if not path.is_file() or path.stat().st_size > 65536:
            raise LifecycleError("invalid_ownership_marker")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise LifecycleError("invalid_json_marker") from None
        except (OSError, ValueError):
            raise LifecycleError("invalid_ownership_marker") from None

    def _write(self, path, data):
        _safe_path(path)
        temporary = path.with_name(path.name + ".writing")
        _safe_path(temporary)
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, separators=(",", ":"))
        temporary.replace(path)

    def _truncated_json(self, path):
        text = path.read_text(encoding="utf-8").rstrip()
        if not text:
            return True
        # A manifest dump always starts an object. Preserve unrelated syntax
        # corruption rather than treating every JSON error as an interruption.
        if not text.startswith("{"):
            return False
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            if error.pos >= len(text) or error.msg.startswith("Unterminated string"):
                return True
            if error.msg == "Invalid \\uXXXX escape":
                tail = text[error.pos:]
                return tail.startswith("u") and len(tail) < 5 and all(
                    c in "0123456789abcdefABCDEF" for c in tail[1:])
        return False

    def _recover_atomic(self, path, validate, *, merge=False, allow_truncated=False):
        """Recover recognized atomic sidecars without losing newer identities.

        A process sidecar can contain a newly started child absent from the
        committed file. Merge both sets before termination; a staged removal
        may preserve an already dead identity, which is harmless after matching.
        """
        staged = path.with_name(path.name + ".writing")
        _safe_path(path)
        _safe_path(staged)
        committed_data = validate(self._read(path)) if path.exists() else None
        try:
            staged_data = validate(self._read(staged)) if staged.exists() else None
        except LifecycleError as error:
            if not (allow_truncated and self._owner is not None and committed_data is not None
                    and error.code == "invalid_json_marker" and self._truncated_json(staged)):
                raise
            # Root ownership and the committed manifest are already proven.
            # Kernel parent-death supervision ends children after a bot crash,
            # including a child whose first identity write was interrupted.
            # Retain the validated committed identities; discard only this
            # recognized incomplete sidecar so document cleanup can proceed.
            staged.unlink()
            return committed_data
        if staged_data is None:
            return committed_data
        if merge:
            recovered = {**(committed_data or {}), **staged_data}
            self._write(path, recovered)
            return recovered
        if committed_data is not None:
            if committed_data != staged_data:
                raise LifecycleError("ownership_sidecar_conflict")
            staged.unlink()
            return committed_data
        staged.replace(path)
        return staged_data

    def _validate_owner(self, data):
        if not isinstance(data, dict) or set(data) != {"application", "owner", "root"} or (
            data["application"] != "tgbotdocs-temporary-v1" or data["root"] != str(self.root)
            or not isinstance(data["owner"], str) or len(data["owner"]) != 32
            or any(c not in "0123456789abcdef" for c in data["owner"])
        ):
            raise LifecycleError("invalid_ownership_marker")
        return data

    def _validate_processes(self, records):
        if not isinstance(records, dict):
            raise LifecycleError("invalid_process_manifest")
        for key, record in records.items():
            if not isinstance(record, dict) or set(record) != {"pid", "created", "executable"} or (
                type(record["pid"]) is not int or record["pid"] <= 1 or str(record["pid"]) != key
                or record["pid"] == os.getpid() or type(record["created"]) not in (float, int)
                or not math.isfinite(record["created"]) or record["created"] <= 0
                or not isinstance(record["executable"], str)
                or not Path(record["executable"]).is_absolute()
            ):
                raise LifecycleError("invalid_process_manifest")
        return records

    def _validate_job_marker(self, marker):
        if marker != {"owner": self._owner}:
            raise LifecycleError("unowned_job_directory")
        return marker

    def _validate_intent(self, data):
        if not isinstance(data, dict) or set(data) != {"owner", "directory"} or (
            data["owner"] != self._owner or not isinstance(data["directory"], str)
            or len(data["directory"]) != 36 or not data["directory"].startswith("job-")
            or any(c not in "0123456789abcdef" for c in data["directory"][4:])
        ):
            raise LifecycleError("invalid_creation_intent")
        return data

    def _recover_creation(self, intent_name=".tgbotdocs-create.json"):
        intent = self.root / intent_name
        data = self._recover_atomic(intent, self._validate_intent)
        if data is None:
            return
        directory = _safe_path(self.root / data["directory"])
        if directory.exists():
            if not directory.is_dir():
                raise LifecycleError("unowned_job_directory")
            marker = directory / ".tgbotdocs-job.json"
            # A committed intent proves this exact directory belongs to this
            # root, even if mkdir succeeded but writing its marker did not.
            _safe_path(marker)
            _safe_path(marker.with_name(marker.name + ".writing"))
            if marker.exists():
                self._validate_job_marker(self._read(marker))
            else:
                self._write(marker, {"owner": self._owner})
        intent.unlink()

    async def initialize(self):
        """Validate ownership, terminate matching orphans, sweep jobs first."""
        try:
            _safe_path(self.root)
            self.root.mkdir(parents=True, exist_ok=True)
            marker = self.root / ".tgbotdocs-owner.json"
            data = self._recover_atomic(marker, self._validate_owner)
            if data is not None:
                self._owner = data["owner"]
            else:
                if any(self.root.iterdir()):
                    raise LifecycleError("unowned_temporary_root")
                self._owner = secrets.token_hex(16)
                self._write(marker, {"application": "tgbotdocs-temporary-v1",
                                     "owner": self._owner, "root": str(self.root)})
            manifest = self.root / ".tgbotdocs-processes.json"
            records = self._recover_atomic(manifest, self._validate_processes, merge=True,
                                           allow_truncated=True)
            if records is not None:
                self._processes = records
                await asyncio.to_thread(self._terminate_orphans)
                self._processes = {}
                self._write(manifest, {})
            self._recover_creation()
            self._recover_creation(".tgbotdocs-delete.json")
            for child in self.root.iterdir():
                if child.name in {marker.name, manifest.name}:
                    continue
                self._validate_job(child)
                await self.cleanup_job(child)
        except (LifecycleError, OSError):
            self._unsafe = True
            await self._alert("temporary_startup_failed")
            raise LifecycleError("temporary_startup_failed") from None
        if not self.intake_available:
            await self._alert("intake_closed")
        return self.intake_available

    def _terminate_orphans(self):
        # Validate the entire set first; malformed later rows must not cause
        # partial termination of otherwise valid earlier records.
        self._validate_processes(self._processes)
        for record in self._processes.values():
            try:
                process = psutil.Process(record["pid"])
                if process.create_time() != record["created"] or os.path.normcase(process.exe()) != (
                    os.path.normcase(record["executable"])
                ):
                    continue  # recycled PID: never terminate it
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            except psutil.NoSuchProcess:
                continue
            except (psutil.Error, OSError):
                raise LifecycleError("orphan_termination_failed") from None

    def register_process(self, pid):
        """Synchronous; record only a child actually started by this process."""
        if not self.intake_available:
            raise LifecycleError("temporary_unavailable")
        process = psutil.Process(pid)
        if process.ppid() != os.getpid():
            raise LifecycleError("process_not_owned")
        self._processes[str(pid)] = {"pid": pid, "created": process.create_time(),
                                    "executable": process.exe()}
        self._write(self.root / ".tgbotdocs-processes.json", self._processes)

    def forget_process(self, pid):
        self._processes.pop(str(pid), None)
        self._write(self.root / ".tgbotdocs-processes.json", self._processes)

    def _validate_job(self, path):
        path = _safe_path(path)
        if path.parent != self.root or not path.name.startswith("job-") or not path.is_dir():
            raise LifecycleError("unowned_job_directory")
        marker = self._recover_atomic(path / ".tgbotdocs-job.json", self._validate_job_marker)
        if marker is None:
            raise LifecycleError("unowned_job_directory")
        # shutil refuses directory symlinks; reject reparse points at every depth
        # too, so quota accounting and cleanup never follow external contents.
        for directory, folders, files in os.walk(path, followlinks=False):
            for name in folders + files:
                _safe_path(Path(directory) / name)
        return path

    @staticmethod
    def _usage(root):
        total = 0
        for directory, folders, files in os.walk(root, followlinks=False):
            for name in folders + files:
                path = _safe_path(Path(directory) / name)
                if path.is_file():
                    total += path.stat().st_size
        return total

    def _fits(self, extra_bytes):
        """Existing files plus outstanding render reservations plus the new bytes."""
        reserved = sum(self._reserved.values())
        return self._usage(self.root) + reserved + extra_bytes <= self.quota_bytes and (
            shutil.disk_usage(self.root).free - reserved - extra_bytes >= self.free_reserve_bytes)

    def check_capacity(self, extra_bytes=0):
        if not self.intake_available:
            raise LifecycleError("temporary_unavailable")
        if type(extra_bytes) is not int or extra_bytes < 0:
            raise ValueError("invalid_capacity_request")
        if not self._fits(extra_bytes):
            raise LifecycleError("storage_limit")

    def job_usage(self, path):
        """Bytes already held by one owned job directory (originals and derived files)."""
        return self._usage(self._validate_job(path))

    @contextmanager
    def reserve(self, nbytes):
        """Hold global quota for derived renders the frozen core may write into a job.

        Admitted jobs keep processing while intake is closed for new documents,
        so a reservation needs initialized ownership, not open intake. Existing
        renders are counted twice while held, which only errs on the safe side.
        """
        if type(nbytes) is not int or nbytes < 0:
            raise ValueError("invalid_capacity_request")
        if self._owner is None or self._unsafe:
            raise LifecycleError("temporary_unavailable")
        try:
            fits = self._fits(nbytes)
        except OSError:
            raise LifecycleError("storage_limit") from None
        if not fits:
            raise LifecycleError("storage_limit")
        key = object()
        self._reserved[key] = nbytes
        try:
            yield
        finally:
            self._reserved.pop(key, None)

    def create_job(self, job_id):
        """job_id is intentionally not used as a filesystem name or stored."""
        self.check_capacity()
        path = self.root / ("job-" + secrets.token_hex(16))
        intent = self.root / ".tgbotdocs-create.json"
        if intent.exists() or intent.with_name(intent.name + ".writing").exists():
            self._unsafe = True
            raise LifecycleError("creation_recovery_required")
        try:
            self._write(intent, {"owner": self._owner, "directory": path.name})
            path.mkdir()
            self._write(path / ".tgbotdocs-job.json", {"owner": self._owner})
            intent.unlink()
        except (OSError, LifecycleError):
            self._unsafe = True
            raise LifecycleError("job_creation_failed") from None
        return path

    def _remove_job(self, path):
        # Keep the ownership marker until all content has gone. A partial
        # deletion must remain identifiable on the next retry or crash restart.
        marker = path / ".tgbotdocs-job.json"
        for directory, folders, files in os.walk(path, topdown=False, followlinks=False):
            for name in files:
                candidate = Path(directory) / name
                if candidate != marker:
                    candidate.unlink()
            for name in folders:
                (Path(directory) / name).rmdir()
        # This intent also covers the tiny crash window between removing the
        # last marker and removing the now-empty directory itself.
        intent = self.root / ".tgbotdocs-delete.json"
        self._write(intent, {"owner": self._owner, "directory": path.name})
        marker.unlink()
        try:
            path.rmdir()
        except OSError:
            self._write(marker, {"owner": self._owner})
            intent.unlink()
            raise
        intent.unlink()

    async def _delete(self, path):
        task = asyncio.create_task(asyncio.to_thread(self._remove_job, path))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def cleanup_job(self, path):
        async with self._cleanup_lock:
            path = Path(path)
            was_open = self.intake_available
            for attempt in range(self.attempts):
                try:
                    _safe_path(path)
                    if path.exists():
                        self._validate_job(path)
                        await self._delete(path)
                    elif path.parent != self.root or not path.name.startswith("job-"):
                        raise LifecycleError("unowned_job_directory")
                    self._pending.discard(path)
                    if self.intake_available and not was_open:
                        await self._alert("intake_reopened")
                    return True
                except LifecycleError:
                    self._unsafe = True
                    await self._alert("temporary_ownership_failed")
                    return False
                except OSError:
                    if attempt + 1 < self.attempts:
                        await asyncio.sleep(self.backoff_s * 2**attempt)
            self._pending.add(path)
            if was_open:
                await self._alert("intake_closed")
            return False

    async def retry_pending(self):
        was_open = self.intake_available
        for path in tuple(self._pending):
            # A minute sweep makes one further attempt; startup/terminal calls
            # already performed the initial bounded exponential backoff.
            async with self._cleanup_lock:
                try:
                    _safe_path(path)
                    if path.exists():
                        self._validate_job(path)
                        await self._delete(path)
                    self._pending.discard(path)
                except LifecycleError:
                    self._unsafe = True
                except OSError:
                    pass
        if self.intake_available and not was_open:
            await self._alert("intake_reopened")
        return self.intake_available
