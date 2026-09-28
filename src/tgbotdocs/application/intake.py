"""Temporary document resources; dialogue/timers remain in the user actor."""

import asyncio
from dataclasses import dataclass, field, replace
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from tgbotdocs.recognition.preparation import PageInfo, PreparationError, PreparationLimits, PreparedDocument

from .download_sink import DownloadError, DownloadSink, FILE_LIMIT, QuotaCoordinator
from .lifecycle import LifecycleError


class IntakeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class AcceptedFile:
    file_key: str
    path: Path
    message_id: int
    compressed: bool
    kind: str
    pages: tuple[PageInfo, ...]
    arrival_sequence: int
    album_id: str | None = None


@dataclass(repr=False)
class Submission:
    owner: int
    job_id: str
    generation: int
    admission_order: object
    admission_time: float
    mode: str
    album_id: str | None
    path: Path
    files: list[AcceptedFile] = field(default_factory=list)
    pending: set = field(default_factory=set)
    updates: dict = field(default_factory=dict)
    messages: dict = field(default_factory=dict)
    sequence: int = 0
    closed: bool = False
    draining: bool = False
    closing_task: asyncio.Task | None = None


@dataclass(frozen=True, repr=False)
class ReadySubmission:
    document: PreparedDocument
    files: tuple[AcceptedFile, ...]
    page_bindings: tuple[tuple[str, int], ...]
    generation: int
    estimate_s: float

    @property
    def paths(self):
        return self.document.files


async def _finish(task):
    """Termination/cleanup survives repeated caller cancellation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


class IntakeManager:
    def __init__(self, lifecycle, transport, frozen, *, admitted_jobs=8, download_limit=2,
                 healthy=lambda: True, fixed_overhead_s=0.0, clock=time.monotonic):
        if any(type(x) is not int or x <= 0 for x in (admitted_jobs, download_limit)) or (
            not math.isfinite(fixed_overhead_s) or fixed_overhead_s < 0
        ):
            raise ValueError("invalid_intake_limits")
        self.lifecycle, self.transport, self.frozen = lifecycle, transport, frozen
        self.admitted_jobs, self.healthy, self.clock = admitted_jobs, healthy, clock
        # Explicit initial engineering policy: zero overhead is unmeasured, not
        # a performance acceptance result. Per-kind p5 values remain frozen.
        self.fixed_overhead_s = fixed_overhead_s
        self.page_times = {entry.kind: entry.p5 for entry in frozen.page_times}
        if set(self.page_times) != {"png", "jpeg", "pdf"} or any(
            not math.isfinite(value) or value <= 0 for value in self.page_times.values()
        ):
            raise ValueError("invalid_admission_page_times")
        core = frozen.core
        self.processing_s, self.parser_timeout_s = core.processing_budget_s, min(30.0, core.call_timeout_s)
        self.limits = PreparationLimits(core.max_pixels, core.quota_bytes, core.free_reserve_bytes)
        self.downloads = asyncio.Semaphore(download_limit)
        self.quota = QuotaCoordinator(lifecycle)
        self.submissions = {}
        self.closing = False

    def reserve(self, owner, job_id, generation, admission_order, *, mode, album_id=None):
        if type(owner) is not int or owner <= 0 or type(generation) is not int or generation < 0 or (
            mode not in ("single", "album", "several")
        ):
            raise IntakeError("invalid_request")
        if self.closing or not self.lifecycle.intake_available or not self.healthy():
            raise IntakeError("temporarily_unavailable")
        if owner in self.submissions:
            raise IntakeError("active_document")
        if len(self.submissions) >= self.admitted_jobs:
            raise IntakeError("busy")
        try:
            path = self.lifecycle.create_job(job_id)
        except LifecycleError as error:
            raise IntakeError(error.code) from None
        submission = Submission(owner, job_id, generation, admission_order, self.clock(), mode, album_id, path)
        self.submissions[owner] = submission
        return submission

    def _valid(self, submission, generation=None):
        if self.submissions.get(submission.owner) is not submission or submission.closed or (
            generation is not None and submission.generation != generation
        ):
            raise asyncio.CancelledError

    async def receive(self, submission, upload, *, message_id, update_id):
        self._valid(submission)
        if submission.draining:
            raise IntakeError("operation_draining")
        if type(message_id) is not int or message_id <= 0 or type(update_id) is not int:
            raise IntakeError("invalid_request")
        existing = submission.updates.get(update_id) or submission.messages.get(message_id)
        if existing is not None:
            return await asyncio.shield(existing)
        generation = submission.generation
        sequence = submission.sequence
        submission.sequence += 1
        task = asyncio.create_task(self._receive(submission, upload, message_id, sequence, generation))
        submission.pending.add(task)
        submission.updates[update_id] = submission.messages[message_id] = task
        def completed(done):
            submission.pending.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(completed)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            try:
                await _finish(task)
            except (asyncio.CancelledError, IntakeError):
                pass
            raise

    async def _receive(self, submission, upload, message_id, sequence, generation):
        file_key = secrets.token_hex(16)
        path = submission.path / ("original-" + file_key)
        accepted = False
        try:
            size = upload.size
            if size is not None and (type(size) is not int or size < 0 or size > FILE_LIMIT):
                raise IntakeError("file_too_large")
            async with self.downloads:
                self._valid(submission, generation)
                with DownloadSink(path, self.quota) as sink:
                    await self.transport.download(upload, sink)
                self._valid(submission, generation)
            metadata = await self._inspect(path, submission.path)
            self._valid(submission, generation)
            result = AcceptedFile(file_key, path, message_id, upload.compressed,
                                  metadata["kind"], metadata["pages"], sequence, upload.media_group_id)
            submission.files.append(result)
            accepted = True
            return result
        except (DownloadError, LifecycleError) as error:
            raise IntakeError(error.code) from None
        except (IntakeError, asyncio.CancelledError):
            raise
        except Exception:
            raise IntakeError("download_failed") from None
        finally:
            if not accepted:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # Preserve the partial under the owned job for lifecycle cleanup.
                    raise IntakeError("storage_limit") from None

    async def _inspect(self, path, root):
        budget = self.processing_s
        response_limit = 1024 + math.floor(budget / min(self.page_times.values())) * 512
        request = {"path": str(path), "root": str(root), "max_pixels": self.limits.max_pixels,
                   "page_times": self.page_times, "budget_s": budget, "response_limit": response_limit}
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            sys.executable, "-u", "-m", "tgbotdocs.application.intake_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, **options))
        try:
            process = await asyncio.shield(spawn)
        except asyncio.CancelledError:
            process = await _finish(spawn)
            if process.returncode is None:
                process.kill()
            await _finish(asyncio.create_task(process.wait()))
            raise
        except OSError:
            raise IntakeError("parser_failed") from None

        async def communicate():
            process.stdin.write(json.dumps(request).encode())
            await process.stdin.drain()
            process.stdin.close()
            output = bytearray()
            while chunk := await process.stdout.read(min(65536, response_limit + 1 - len(output))):
                output.extend(chunk)
                if len(output) > response_limit:
                    raise IntakeError("parser_failed")
            await process.wait()
            return output
        communication = asyncio.create_task(communicate())
        try:
            output = await asyncio.wait_for(asyncio.shield(communication), self.parser_timeout_s)
        except BaseException as error:
            if process.returncode is None:
                process.kill()
            await _finish(asyncio.create_task(process.wait()))
            communication.cancel()
            try:
                await _finish(communication)
            except (asyncio.CancelledError, IntakeError, OSError, ConnectionError):
                pass
            if isinstance(error, asyncio.CancelledError):
                raise
            raise IntakeError("parser_timeout" if isinstance(error, TimeoutError) else "parser_failed") from None
        try:
            value = json.loads(output)
            if value.get("error"):
                allowed = {"invalid_path", "unsupported_format", "damaged_input", "encrypted_pdf", "pixel_limit",
                           "processing_limit"}
                raise IntakeError(value["error"] if value["error"] in allowed else "parser_failed")
            if process.returncode != 0 or set(value) != {"kind", "pages"}:
                raise ValueError
            pages = tuple(PageInfo(**page) for page in value["pages"])
            if not pages or value["kind"] not in self.page_times or any(
                p.page_id != index + 1 or p.file_index != 0 or p.file_page_index != index or p.kind != value["kind"]
                for index, p in enumerate(pages)
            ):
                raise ValueError
            return {"kind": value["kind"], "pages": pages}
        except IntakeError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, PreparationError):
            raise IntakeError("parser_failed") from None

    async def seal(self, submission, *, remaining_budget_s=None):
        self._valid(submission)
        generation = submission.generation
        if submission.pending:
            await asyncio.gather(*tuple(submission.pending))
        self._valid(submission, generation)
        files = tuple(sorted(submission.files, key=lambda item:
                             item.message_id if submission.mode == "album" else item.arrival_sequence))
        if submission.mode == "several":
            # Album members retain Telegram order even inside a manual set.
            # Fill only their existing positions; unrelated files stay in place.
            ordered, groups = list(files), {}
            for index, original in enumerate(files):
                if original.album_id is not None:
                    groups.setdefault(original.album_id, []).append(index)
            for positions in groups.values():
                members = sorted((files[index] for index in positions), key=lambda item: item.message_id)
                for index, member in zip(positions, members, strict=True):
                    ordered[index] = member
            files = tuple(ordered)
        if not files:
            raise IntakeError("no_document")
        budget = self.processing_s if remaining_budget_s is None else remaining_budget_s
        if not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
            raise IntakeError("processing_limit")
        estimate = self.fixed_overhead_s + sum(self.page_times[p.kind] for f in files for p in f.pages)
        if estimate > budget:
            raise IntakeError("processing_limit")
        pages, bindings = [], []
        for index, original in enumerate(files):
            for page in original.pages:
                pages.append(replace(page, page_id=len(pages) + 1, file_index=index))
                bindings.append((original.file_key, page.file_page_index))
        document = PreparedDocument(tuple(f.path for f in files), tuple(pages), self.limits)
        return ReadySubmission(document, files, tuple(bindings), generation, estimate)

    def cancel_now(self, submission):
        if submission.closed:
            return
        submission.generation += 1
        submission.draining = True
        for task in tuple(submission.pending):
            task.cancel()

    async def drain(self, submission):
        tasks = tuple(submission.pending)
        if tasks:
            await _finish(asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True)))
        submission.draining = False

    async def close_submission(self, submission):
        if submission.closing_task is None:
            self.cancel_now(submission)
            submission.closed = True
            async def cleanup():
                await self.drain(submission)
                result = await self.lifecycle.cleanup_job(submission.path)
                if self.submissions.get(submission.owner) is submission:
                    self.submissions.pop(submission.owner)
                submission.files.clear()
                submission.updates.clear()
                submission.messages.clear()
                return result
            submission.closing_task = asyncio.create_task(cleanup())
        return await _finish(submission.closing_task)

    async def close(self):
        self.closing = True
        await asyncio.gather(*(self.close_submission(s) for s in tuple(self.submissions.values())))
