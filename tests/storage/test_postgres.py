import asyncio
import threading
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from tgbotdocs.recognition.contracts import ExtractionProfile, ListField, ScalarField
from tgbotdocs.storage import ProfileConflict, ProfileNotFound, ProfileStore, StorageUnavailable


def draft(owner=101, *, name="Synthetic invoice", identifier=None):
    return ExtractionProfile(id=identifier or str(uuid4()), owner=str(owner), version=1,
        name=name, description="Synthetic invoices only", original_instruction="Extract the invoice number",
        fields=(ScalarField(id="number", label="Number", description="Invoice identifier", type="text"),
                ListField(id="items", label="Items", description="Invoice lines", columns=(
                    ScalarField(id="item", label="Item", description="Line name", type="text"),))), guidance="")


async def test_migrate_idempotent_and_exact_schema(storage):
    store, schema, engine = storage
    await store.migrate()
    await store.health()
    with engine.connect() as connection:
        tables = connection.execute(text("SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=:schema"), {"schema": schema}).scalars().all()
        assert set(tables) == {"users", "extraction_profiles", "alembic_version"}
        assert connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one() == \
            "0001_profiles"


async def test_database_work_uses_dedicated_executor(storage):
    store, _, _ = storage
    threads = []
    def observe(*_):
        threads.append(threading.current_thread().name)
    event.listen(store._engine, "before_cursor_execute", observe)
    try:
        await store.health()
        await store.list_profiles(101)
    finally:
        event.remove(store._engine, "before_cursor_execute", observe)
    assert threads and all(name.startswith("tgbotdocs-db") for name in threads)


async def test_atomic_multi_draft_and_repeat_confirmation(storage):
    store, _, _ = storage
    drafts = (draft(), draft(name="Synthetic certificate"))
    saved = await store.save_drafts(101, drafts)
    assert saved == drafts
    assert await store.save_drafts(101, drafts) == drafts
    assert set(await store.list_profiles(101)) == set(drafts)


async def test_actual_database_failure_rolls_back_whole_preview(storage):
    store, schema, engine = storage
    with engine.begin() as connection:
        connection.execute(text(f'ALTER TABLE "{schema}".extraction_profiles '
            "ADD CONSTRAINT synthetic_failure CHECK (name <> '__reject__')"))
    with pytest.raises(ProfileConflict):
        await store.save_drafts(101, (draft(), draft(name="__reject__")))
    assert await store.list_profiles(101) == ()
    with engine.connect() as connection:
        assert connection.execute(text(f'SELECT count(*) FROM "{schema}".users')).scalar_one() == 0


async def test_two_owners_cannot_read_update_delete_or_reuse_ids(storage):
    store, _, _ = storage
    profile = draft()
    await store.save_drafts(101, (profile,))
    assert await store.list_profiles(202) == ()
    with pytest.raises(ProfileNotFound):
        await store.get_profile(202, profile.id)
    forged = profile.model_copy(update={"owner": "202"})
    with pytest.raises(ProfileNotFound):
        await store.update_profile(202, forged, 1)
    with pytest.raises(ProfileNotFound):
        await store.delete_profile(202, profile.id, 1)
    with pytest.raises(ProfileConflict):
        await store.save_drafts(202, (forged,))
    assert await store.get_profile(101, profile.id) == profile


async def test_optimistic_updates_snapshots_and_stale_delete(storage):
    store, _, _ = storage
    profile = draft()
    await store.save_drafts(101, (profile,))
    changed = profile.model_copy(update={"name": "Changed synthetic name"})
    result = await store.update_profile(101, changed, 1)
    assert result.version == 2
    assert profile.name == "Synthetic invoice" and profile.version == 1
    with pytest.raises(ProfileConflict):
        await store.update_profile(101, changed, 1)
    with pytest.raises(ProfileConflict):
        await store.delete_profile(101, profile.id, 1)
    await store.delete_profile(101, profile.id, 2)
    assert await store.list_profiles(101) == ()


async def test_concurrent_confirmations_and_compare_and_swap(storage):
    store, _, _ = storage
    profile = draft()
    results = await asyncio.gather(*(store.save_drafts(101, (profile,)) for _ in range(4)))
    assert all(result == (profile,) for result in results)
    assert len(await store.list_profiles(101)) == 1
    edits = (profile.model_copy(update={"name": "Edit A"}), profile.model_copy(update={"name": "Edit B"}))
    results = await asyncio.gather(*(store.update_profile(101, edit, 1) for edit in edits), return_exceptions=True)
    assert sum(isinstance(result, ExtractionProfile) for result in results) == 1
    assert sum(isinstance(result, ProfileConflict) for result in results) == 1
    assert (await store.get_profile(101, profile.id)).version == 2


async def test_partial_repeat_does_not_save_new_drafts(storage):
    store, _, _ = storage
    profile, new = draft(), draft()
    await store.save_drafts(101, (profile,))
    with pytest.raises(ProfileConflict):
        await store.save_drafts(101, (profile, new))
    assert await store.list_profiles(101) == (profile,)


async def test_reopen_retains_profiles_and_round_trips_list_schema(storage, database_url):
    store, schema, _ = storage
    profile = draft()
    await store.save_drafts(101, (profile,))
    await store.close()
    reopened = ProfileStore(database_url, schema=schema)
    try:
        assert await reopened.get_profile(101, profile.id) == profile
    finally:
        await reopened.close()


async def test_unavailable_database_and_closed_store_errors_are_safe():
    store = ProfileStore("postgresql+psycopg://unused:synthetic-secret@127.0.0.1:1/unused")
    try:
        with pytest.raises(StorageUnavailable) as captured:
            await store.health()
        assert str(captured.value) == "database operation failed"
        assert captured.value.__cause__ is None
    finally:
        await store.close()
    with pytest.raises(StorageUnavailable, match="closed"):
        await store.health()
