"""Lazy page preparation in short-lived, cancellable parser processes.

Originals belong to the caller's retained job directory. Only child directories
created here are deleted. Exceptions expose fixed codes, never document content.
Crash/parent-death supervision is supplied by the application supervisor.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import AsyncIterator


class PreparationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreparationLimits:
    # Pillow's default warning threshold; a warning is a refusal in our worker.
    max_pixels: int = 89_478_485
    quota_bytes: int = 2 * 1024**3
    free_reserve_bytes: int = 2 * 1024**3

    def __post_init__(self):
        if any(type(x) is not int or x < 0 for x in
               (self.max_pixels, self.quota_bytes, self.free_reserve_bytes)) or not self.max_pixels:
            raise PreparationError("invalid_request")


@dataclass(frozen=True)
class PageInfo:
    page_id: int
    file_index: int
    file_page_index: int
    kind: str
    # PDF points or EXIF-oriented image pixels. No decoded raster is retained.
    width: float
    height: float

    def __post_init__(self):
        if (type(self.page_id) is not int or self.page_id <= 0
                or type(self.file_index) is not int or self.file_index < 0
                or type(self.file_page_index) is not int or self.file_page_index < 0
                or self.kind not in ("png", "jpeg", "pdf")
                or not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0
                           for x in (self.width, self.height))):
            raise PreparationError("invalid_request")


@dataclass(frozen=True)
class PreparedDocument:
    files: tuple[Path, ...]
    pages: tuple[PageInfo, ...]
    limits: PreparationLimits


@dataclass(frozen=True)
class PreparedPage:
    page_id: int
    path: Path
    width: int
    height: int


def _safe_path(path: Path, *, directory: bool = False) -> Path:
    """Reject links/junctions in every existing ancestor before resolving."""
    candidate = Path(os.path.abspath(path))
    try:
        for node in (candidate, *candidate.parents):
            info = node.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise PreparationError("invalid_path")
        info = candidate.stat()
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise PreparationError("invalid_path")
    except OSError:
        raise PreparationError("invalid_path") from None
    return candidate.resolve()


def _owned_directory(scratch: Path) -> tuple[Path, Path]:
    root = _safe_path(scratch, directory=True)
    try:
        owned = Path(tempfile.mkdtemp(prefix="prep-", dir=root))
    except OSError:
        raise PreparationError("storage_limit") from None
    return root, owned


def _remove_owned(root: Path, owned: Path) -> None:
    """Never pass a caller's directory to a recursive deletion operation."""
    if not owned.exists():
        return
    try:
        if _safe_path(root, directory=True) != root or owned.parent != root:
            raise PreparationError("cleanup_failed")
        if _safe_path(owned, directory=True).parent != root:
            raise PreparationError("cleanup_failed")

        def remove(directory: Path):
            for entry in directory.iterdir():
                info = entry.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise PreparationError("cleanup_failed")
                if stat.S_ISDIR(info.st_mode):
                    remove(entry)
                elif stat.S_ISREG(info.st_mode):
                    entry.unlink()
                else:
                    raise PreparationError("cleanup_failed")
            directory.rmdir()

        remove(owned)
    except (OSError, PreparationError):
        raise PreparationError("cleanup_failed") from None


def _worker_command() -> tuple[str, ...]:
    return (sys.executable, "-u", str(Path(__file__).with_name("preparation_worker.py")))


async def _finish_even_if_cancelled(task: asyncio.Task):
    """Wait for termination even if a second cancel arrives during cleanup."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def _run_worker(request: dict, timeout_s: float) -> dict:
    if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise PreparationError("invalid_request")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *_worker_command(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, **options))
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        process = await _finish_even_if_cancelled(spawn)
        if process.returncode is None:
            process.kill()
        await _finish_even_if_cancelled(asyncio.create_task(process.wait()))
        raise
    except OSError:
        raise PreparationError("worker_failed") from None
    communication = asyncio.create_task(process.communicate(json.dumps(request).encode("utf-8")))
    try:
        stdout, _ = await asyncio.wait_for(asyncio.shield(communication), timeout_s)
    except (TimeoutError, asyncio.CancelledError) as error:
        if process.returncode is None:
            process.kill()
        await _finish_even_if_cancelled(asyncio.create_task(process.wait()))
        try:
            await _finish_even_if_cancelled(communication)
        except (OSError, ConnectionError):
            pass
        if isinstance(error, asyncio.CancelledError):
            raise
        raise PreparationError("worker_timeout") from None
    except (OSError, ConnectionError):
        if process.returncode is None:
            process.kill()
        await _finish_even_if_cancelled(asyncio.create_task(process.wait()))
        raise PreparationError("worker_failed") from None
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise PreparationError("worker_failed") from None
    codes = {"unsupported_format", "damaged_input", "encrypted_pdf", "pixel_limit",
             "storage_limit", "invalid_path", "invalid_request", "worker_failed"}
    if not isinstance(result, dict):
        raise PreparationError("worker_failed")
    if result.get("error"):
        raise PreparationError(result["error"] if result["error"] in codes else "worker_failed")
    if process.returncode != 0:
        raise PreparationError("worker_failed")
    return result


async def inspect_document(files: tuple[Path, ...], scratch: Path,
                           limits: PreparationLimits, timeout_s: float) -> PreparedDocument:
    """Index every page in file order without rasterizing a PDF or image."""
    if not files:
        raise PreparationError("invalid_request")
    originals = tuple(_safe_path(path) for path in files)
    root, owned = _owned_directory(scratch)
    try:
        result = await _run_worker({"operation": "inspect", "files": [str(p) for p in originals],
                                    "scratch": str(root), "owned": str(owned),
                                    "limits": asdict(limits)}, timeout_s)
        try:
            pages = tuple(PageInfo(**page) for page in result["pages"])
            if not pages or tuple(p.page_id for p in pages) != tuple(range(1, len(pages) + 1)):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise PreparationError("worker_failed") from None
        return PreparedDocument(originals, pages, limits)
    finally:
        _remove_owned(root, owned)


@asynccontextmanager
async def render_batch(document: PreparedDocument, page_ids: tuple[int, ...], dpi: int,
                       max_long_side: int | None = None, *, scratch: Path,
                       timeout_s: float) -> AsyncIterator[tuple[PreparedPage, ...]]:
    """Render only requested pages and delete all derived files on context exit.

    PNG outputs are oriented/downscaled whole pages. Original job files are never
    deleted or copied. Keep the context open while consumers read these paths.
    """
    by_id = {p.page_id: p for p in document.pages}
    if (not page_ids or any(type(p) is not int or p not in by_id for p in page_ids)
            or len(set(page_ids)) != len(page_ids) or type(dpi) is not int or dpi <= 0
            or max_long_side is not None and (type(max_long_side) is not int or max_long_side <= 0)):
        raise PreparationError("invalid_request")
    originals = tuple(_safe_path(path) for path in document.files)
    root, owned = _owned_directory(scratch)
    try:
        result = await _run_worker({"operation": "render", "files": [str(p) for p in originals],
                                    "pages": [asdict(by_id[p]) for p in page_ids],
                                    "dpi": dpi, "max_long_side": max_long_side,
                                    "scratch": str(root), "owned": str(owned),
                                    "limits": asdict(document.limits)}, timeout_s)
        try:
            prepared = tuple(PreparedPage(page["page_id"], owned / f"page-{page['page_id']}.png",
                                           page["width"], page["height"]) for page in result["pages"])
            if tuple(p.page_id for p in prepared) != page_ids:
                raise ValueError
            for page in prepared:
                if _safe_path(page.path).parent != owned or page.width <= 0 or page.height <= 0:
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            raise PreparationError("worker_failed") from None
        yield prepared
    finally:
        _remove_owned(root, owned)
