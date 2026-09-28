import asyncio
from uuid import uuid4

import pytest

from tgbotdocs.application.compiler import CompileResult
from tgbotdocs.application.profiles import PreviewExpired, PreviewService
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField
from tgbotdocs.storage import ProfileConflict, ProfileNotFound, StorageUnavailable


def profile(owner=101, version=1):
    return ExtractionProfile(id=str(uuid4()), owner=str(owner), version=version, name="Synthetic",
        description="Synthetic test", original_instruction="Read identifier",
        fields=(ScalarField(id="identifier", label="Identifier", description="Requested ID", type="text"),))


class Store:
    def __init__(self):
        self.rows, self.calls = {}, []
        self.failure = None
        self.gate = None
        self.started = asyncio.Event()

    async def get_profile(self, owner, identifier):
        record = self.rows.get(identifier)
        if record is None or record.owner != str(owner):
            raise ProfileNotFound("profile not found")
        return record

    async def save_drafts(self, owner, drafts):
        self.calls.append(("create", owner, tuple(p.id for p in drafts)))
        self.started.set()
        if self.gate:
            await self.gate.wait()
        if self.failure:
            raise self.failure
        self.rows.update((p.id, p) for p in drafts)
        return drafts

    async def update_profile(self, owner, edited, expected_version):
        self.calls.append(("update", owner, expected_version))
        if self.failure:
            raise self.failure
        current = await self.get_profile(owner, edited.id)
        if current.version != expected_version:
            raise ProfileConflict("profile preview is stale")
        saved = edited.model_copy(update={"version": expected_version + 1})
        self.rows[edited.id] = saved
        return saved

    async def delete_profile(self, owner, identifier, expected_version):
        self.calls.append(("delete", owner, expected_version))
        if self.failure:
            raise self.failure
        record = await self.get_profile(owner, identifier)
        if record.version != expected_version:
            raise ProfileConflict("profile preview is stale")
        self.rows.pop(identifier)


async def test_atomic_preview_input_two_profiles_and_double_confirmation():
    store = Store()
    service = PreviewService(store)
    drafts = (profile(), profile())
    preview = service.stage(101, CompileResult(drafts=drafts))
    assert service.get(101, preview.nonce).drafts == drafts
    assert not store.rows
    first, second = await asyncio.gather(service.confirm(101, preview.nonce), service.confirm(101, preview.nonce))
    assert first == second == drafts and len(store.calls) == 1
    assert len(store.rows) == 2


async def test_foreign_nonce_cannot_view_save_cancel_or_delete():
    store, service = Store(), None
    service = PreviewService(store)
    preview = service.stage(101, CompileResult(drafts=(profile(),)))
    for operation in (lambda: service.get(202, preview.nonce), lambda: service.cancel(202, preview.nonce)):
        with pytest.raises(PreviewExpired):
            operation()
    with pytest.raises(PreviewExpired):
        await service.confirm(202, preview.nonce)
    assert not store.calls
    saved = await service.confirm(101, preview.nonce)
    with pytest.raises(ProfileNotFound):
        await service.begin_delete(202, saved[0].id)
    deletion = await service.begin_delete(101, saved[0].id)
    with pytest.raises(PreviewExpired):
        await service.confirm_delete(202, deletion.nonce)
    assert saved[0].id in store.rows


async def test_invalid_or_partial_results_never_create_preview():
    service = PreviewService(Store())
    for result in (CompileResult(questions=("Clarify",)),
                   CompileResult(drafts=(profile(),), questions=("Unsupported calculation",)),
                   CompileResult(drafts=(profile(202),))):
        with pytest.raises(ValueError):
            service.stage(101, result)


async def test_save_unavailable_keeps_exact_preview_for_retry():
    store = Store()
    service = PreviewService(store)
    preview = service.stage(101, CompileResult(drafts=(profile(), profile())))
    store.failure = StorageUnavailable("database operation failed")
    with pytest.raises(StorageUnavailable):
        await service.confirm(101, preview.nonce)
    assert service.get(101, preview.nonce) is preview and not store.rows
    store.failure = None
    assert await service.confirm(101, preview.nonce) == preview.drafts
    assert store.calls[0][2] == store.calls[1][2]


async def test_edit_is_previewed_once_and_stale_edit_cannot_overwrite_newer():
    store = Store()
    existing = profile(version=2)
    store.rows[existing.id] = existing
    service = PreviewService(store)
    changed = existing.model_copy(update={"name": "Changed synthetic name"})
    preview = service.stage(101, CompileResult(drafts=(changed,)), editing=existing)
    saved = await service.confirm(101, preview.nonce)
    assert saved[0].version == 3
    assert await service.confirm(101, preview.nonce) == saved
    assert len(store.calls) == 1
    stale = service.stage(101, CompileResult(drafts=(changed,)), editing=existing)
    with pytest.raises(ProfileConflict):
        await service.confirm(101, stale.nonce)
    assert store.rows[existing.id] == saved[0]


async def test_deletion_requires_nonce_confirmation_and_current_version():
    store = Store()
    existing = profile()
    store.rows[existing.id] = existing
    service = PreviewService(store)
    deletion = await service.begin_delete(101, existing.id)
    assert existing.id in store.rows
    store.rows[existing.id] = existing.model_copy(update={"version": 2})
    with pytest.raises(ProfileConflict):
        await service.confirm_delete(101, deletion.nonce)
    assert existing.id in store.rows
    deletion = await service.begin_delete(101, existing.id)
    await service.confirm_delete(101, deletion.nonce)
    count = len(store.calls)
    await service.confirm_delete(101, deletion.nonce)
    assert len(store.calls) == count and existing.id not in store.rows


async def test_revisions_cancel_expiry_logout_job_end_and_restart_discard_drafts():
    now = [0]
    service = PreviewService(Store(), clock=lambda: now[0])
    first = service.stage(101, CompileResult(drafts=(profile(),)))
    replacement = service.stage(101, CompileResult(drafts=(profile(),)))
    assert replacement.revision == first.revision + 1 and replacement.nonce != first.nonce
    with pytest.raises(PreviewExpired):
        service.get(101, first.nonce)
    service.cancel(101, replacement.nonce)
    with pytest.raises(PreviewExpired):
        await service.confirm(101, replacement.nonce)
    preview = service.stage(101, CompileResult(drafts=(profile(),)), job_id="job-a")
    service.discard_job(101, "job-other")
    assert service.get(101, preview.nonce) is preview
    service.discard_job(101, "job-a")
    with pytest.raises(PreviewExpired):
        service.get(101, preview.nonce)
    preview = service.stage(101, CompileResult(drafts=(profile(),)))
    service.discard_owner(202)
    service.discard_owner(101)
    with pytest.raises(PreviewExpired):
        service.get(101, preview.nonce)
    preview = service.stage(101, CompileResult(drafts=(profile(),)))
    now[0] = 899
    assert service.get(101, preview.nonce) is preview
    now[0] = 1799
    assert service.expire() == 1
    with pytest.raises(PreviewExpired):
        service.get(101, preview.nonce)
    restarted = PreviewService(service.store)
    with pytest.raises(PreviewExpired):
        restarted.get(101, preview.nonce)


async def test_cancelled_confirmation_drains_approved_write_and_retains_idempotent_outcome():
    store = Store()
    store.gate = asyncio.Event()
    service = PreviewService(store)
    preview = service.stage(101, CompileResult(drafts=(profile(),)))
    confirming = asyncio.create_task(service.confirm(101, preview.nonce))
    await store.started.wait()
    confirming.cancel()
    await asyncio.sleep(0)
    confirming.cancel()
    store.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await confirming
    assert await service.confirm(101, preview.nonce) == preview.drafts
    assert len(store.calls) == 1
