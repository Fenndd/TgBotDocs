"""RAM-only owner-scoped previews; persistence starts only at explicit confirmation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import secrets
import time

from tgbotdocs.recognition.contracts import ExtractionProfile

from .compiler import CompileResult, _owner


class PreviewExpired(LookupError):
    """Expired, unknown, cancelled or foreign-owned callback, with no data disclosure."""


@dataclass(frozen=True, repr=False)
class ProfilePreview:
    nonce: str
    owner: int
    revision: int
    drafts: tuple[ExtractionProfile, ...]
    editing: ExtractionProfile | None = None
    job_id: str | None = None


@dataclass(frozen=True, repr=False)
class DeletePreview:
    nonce: str
    owner: int
    revision: int
    profile: ExtractionProfile


@dataclass(repr=False)
class _Entry:
    preview: ProfilePreview | DeletePreview
    activity_at: float
    lock: asyncio.Lock
    saved: tuple[ExtractionProfile, ...] | None = None
    deleted: bool = False
    saving: bool = False


class PreviewService:
    def __init__(self, store, *, ttl_s=900, clock=time.monotonic):
        if not math.isfinite(ttl_s) or ttl_s <= 0:
            raise ValueError("invalid preview lifetime")
        self.store, self.ttl_s, self.clock = store, ttl_s, clock
        self._entries: dict[tuple[int, str], _Entry] = {}
        self._revision: dict[int, int] = {}

    def _next(self, owner):
        self.discard_owner(owner)
        revision = self._revision.get(owner, 0) + 1
        self._revision[owner] = revision
        return secrets.token_hex(8), revision

    def _lookup(self, owner, nonce):
        _owner(owner)
        entry = self._entries.get((owner, nonce))
        if entry is None or (not entry.saving and self.clock() - entry.activity_at >= self.ttl_s):
            self._entries.pop((owner, nonce), None)
            raise PreviewExpired("profile preview expired")
        return entry

    def stage(self, owner, result: CompileResult, *, editing=None, job_id=None) -> ProfilePreview:
        _owner(owner)
        if not result.drafts or result.questions or any(profile.owner != str(owner) for profile in result.drafts):
            raise ValueError("preview needs complete drafts owned by the caller")
        if editing is None and any(profile.version != 1 for profile in result.drafts):
            raise ValueError("new profile drafts must have version 1")
        if editing is not None and (editing.owner != str(owner) or len(result.drafts) != 1
            or result.drafts[0].id != editing.id or result.drafts[0].version != editing.version):
            raise ValueError("edit preview must retain the owned profile identity and previewed version")
        nonce, revision = self._next(owner)
        preview = ProfilePreview(nonce, owner, revision, result.drafts, editing, job_id)
        self._entries[(owner, nonce)] = _Entry(preview, self.clock(), asyncio.Lock())
        return preview

    def get(self, owner, nonce) -> ProfilePreview | DeletePreview:
        entry = self._lookup(owner, nonce)
        entry.activity_at = self.clock()
        return entry.preview

    async def _complete(self, operation):
        # Cancellation cannot make an approved committed write look like a new preview.
        task = asyncio.create_task(operation)
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
            except Exception:
                break
        return task.result(), interrupted

    async def confirm(self, owner, nonce) -> tuple[ExtractionProfile, ...]:
        entry = self._lookup(owner, nonce)
        async with entry.lock:
            if self._lookup(owner, nonce) is not entry or not isinstance(entry.preview, ProfilePreview):
                raise PreviewExpired("profile preview expired")
            entry.activity_at = self.clock()
            if entry.saved is not None:
                return entry.saved
            preview = entry.preview
            operation = (self.store.save_drafts(owner, preview.drafts) if preview.editing is None else
                         self.store.update_profile(owner, preview.drafts[0], preview.editing.version))
            entry.saving = True
            try:
                result, interrupted = await self._complete(operation)
                entry.saved = result if preview.editing is None else (result,)
            finally:
                entry.saving = False
            if interrupted:
                raise asyncio.CancelledError
            return entry.saved

    async def begin_delete(self, owner, profile_id) -> DeletePreview:
        _owner(owner)
        profile = await self.store.get_profile(owner, profile_id)
        nonce, revision = self._next(owner)
        preview = DeletePreview(nonce, owner, revision, profile)
        self._entries[(owner, nonce)] = _Entry(preview, self.clock(), asyncio.Lock())
        return preview

    async def confirm_delete(self, owner, nonce) -> None:
        entry = self._lookup(owner, nonce)
        async with entry.lock:
            if self._lookup(owner, nonce) is not entry or not isinstance(entry.preview, DeletePreview):
                raise PreviewExpired("profile preview expired")
            entry.activity_at = self.clock()
            if entry.deleted:
                return
            entry.saving = True
            try:
                _, interrupted = await self._complete(self.store.delete_profile(
                    owner, entry.preview.profile.id, entry.preview.profile.version))
                entry.deleted = True
            finally:
                entry.saving = False
            if interrupted:
                raise asyncio.CancelledError

    def cancel(self, owner, nonce) -> None:
        self._lookup(owner, nonce)
        self._entries.pop((owner, nonce))

    def discard_owner(self, owner) -> None:
        _owner(owner)
        for key in tuple(self._entries):
            if key[0] == owner:
                self._entries.pop(key)

    def discard_job(self, owner, job_id) -> None:
        _owner(owner)
        for key, entry in tuple(self._entries.items()):
            if key[0] == owner and isinstance(entry.preview, ProfilePreview) and entry.preview.job_id == job_id:
                self._entries.pop(key)

    def expire(self) -> int:
        expired = [key for key, entry in self._entries.items() if not entry.saving
                   and self.clock() - entry.activity_at >= self.ttl_s]
        for key in expired:
            self._entries.pop(key)
        return len(expired)
