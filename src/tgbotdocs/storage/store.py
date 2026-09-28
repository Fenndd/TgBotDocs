"""Async boundary over synchronous SQLAlchemy/psycopg in a dedicated executor."""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Callable, TypeVar
from uuid import UUID

from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import URL, create_engine, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from tgbotdocs.recognition.contracts import ExtractionProfile
from .models import Profile, User

T = TypeVar("T")


class StorageUnavailable(RuntimeError):
    """A safe technical error; contains no SQL, parameters, URL, or profile content."""


class ProfileNotFound(LookupError):
    """Missing or not owned by the caller; these cases are indistinguishable."""


class ProfileConflict(RuntimeError):
    """Preview version/content is stale or draft IDs already belong to another save."""


def _owner(owner: int | str) -> int:
    if isinstance(owner, bool) or not str(owner).isdecimal():
        raise ValueError("owner must be a positive Telegram user ID")
    result = int(owner)
    if not 0 < result <= 2**63 - 1:
        raise ValueError("owner must fit PostgreSQL BIGINT")
    return result


def _values(profile: ExtractionProfile) -> dict:
    return {"name": profile.name, "description": profile.description,
            "original_instruction": profile.original_instruction,
            "fields": [field.model_dump(mode="json") for field in profile.fields],
            "guidance": profile.guidance}


def _snapshot(row: Profile) -> ExtractionProfile:
    # JSON-mode validation restores tuples inside the immutable recognition model.
    import json
    return ExtractionProfile.model_validate_json(json.dumps({
        "id": str(row.id), "owner": str(row.owner_id), "version": row.version,
        "name": row.name, "description": row.description,
        "original_instruction": row.original_instruction, "fields": row.fields, "guidance": row.guidance,
    }))


class ProfileStore:
    def __init__(self, url: str | URL, *, workers: int = 2, migration_root: Path | None = None,
                 schema: str | None = None):
        if workers < 1:
            raise ValueError("workers must be positive")
        if schema is not None and not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("schema must be a safe unquoted PostgreSQL identifier")
        options = "-c statement_timeout=10000 -c lock_timeout=5000"
        if schema is not None:
            options += f" -c search_path={schema}"
        self._engine = create_engine(url, pool_size=workers, max_overflow=0, pool_pre_ping=True,
                                     hide_parameters=True, connect_args={"connect_timeout": 5,
                                     "options": options})
        if self._engine.dialect.name != "postgresql" or self._engine.dialect.driver != "psycopg":
            self._engine.dispose()
            raise ValueError("storage requires postgresql+psycopg")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tgbotdocs-db")
        self._closed = False
        self._migration_root = migration_root or Path(__file__).resolve().parents[3] / "migrations"

    async def _run(self, operation: Callable[..., T], *args) -> T:
        if self._closed:
            raise StorageUnavailable("storage is closed")
        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, partial(operation, *args))
        except IntegrityError:
            raise ProfileConflict("profile save conflicts with an existing record") from None
        except (SQLAlchemyError, ValidationError):
            raise StorageUnavailable("database operation failed") from None

    async def health(self) -> None:
        def check():
            with self._engine.connect() as connection:
                connection.execute(select(1))
        await self._run(check)

    async def migrate(self) -> None:
        def upgrade():
            config = Config()
            config.set_main_option("script_location", str(self._migration_root))
            with self._engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        await self._run(upgrade)

    async def list_profiles(self, owner: int | str) -> tuple[ExtractionProfile, ...]:
        owner_id = _owner(owner)
        def read():
            with Session(self._engine) as session:
                rows = session.scalars(select(Profile).where(Profile.owner_id == owner_id)
                                       .order_by(Profile.created_at, Profile.id))
                return tuple(_snapshot(row) for row in rows)
        return await self._run(read)

    async def get_profile(self, owner: int | str, profile_id: str | UUID) -> ExtractionProfile:
        owner_id, identifier = _owner(owner), UUID(str(profile_id))
        def read():
            with Session(self._engine) as session:
                row = session.scalar(select(Profile).where(Profile.owner_id == owner_id, Profile.id == identifier))
                if row is None:
                    raise ProfileNotFound("profile not found")
                return _snapshot(row)
        return await self._run(read)

    async def save_drafts(self, owner: int | str,
                          drafts: tuple[ExtractionProfile, ...]) -> tuple[ExtractionProfile, ...]:
        """Save one confirmed preview atomically; retain its stable UUIDs for retries."""
        owner_id = _owner(owner)
        identifiers = tuple(UUID(draft.id) for draft in drafts)
        if not drafts or len(set(identifiers)) != len(identifiers):
            raise ValueError("drafts must have unique UUIDs and cannot be empty")
        if any(_owner(draft.owner) != owner_id or draft.version != 1 for draft in drafts):
            raise ValueError("new drafts must belong to owner and have version 1")
        def save():
            with Session(self._engine) as session, session.begin():
                session.execute(insert(User).values(telegram_id=owner_id).on_conflict_do_nothing())
                # Serialize confirmations for this owner, including concurrent repeated previews.
                session.execute(select(User.telegram_id).where(User.telegram_id == owner_id).with_for_update())
                existing = {row.id: row for row in session.scalars(select(Profile).where(
                    Profile.owner_id == owner_id, Profile.id.in_(identifiers)))}
                if existing:
                    if len(existing) != len(drafts) or any(
                        identifier not in existing or _snapshot(existing[identifier]) != draft
                        for identifier, draft in zip(identifiers, drafts, strict=True)
                    ):
                        raise ProfileConflict("draft preview conflicts with existing profiles")
                    return tuple(_snapshot(existing[identifier]) for identifier in identifiers)
                for identifier, draft in zip(identifiers, drafts, strict=True):
                    session.add(Profile(id=identifier, owner_id=owner_id, version=1, **_values(draft)))
                session.flush()
                return drafts
        return await self._run(save)

    async def update_profile(self, owner: int | str, profile: ExtractionProfile,
                             expected_version: int) -> ExtractionProfile:
        owner_id, identifier = _owner(owner), UUID(profile.id)
        if _owner(profile.owner) != owner_id or expected_version < 1 or profile.version != expected_version:
            raise ValueError("update must carry owner and previewed version")
        def save():
            with Session(self._engine) as session, session.begin():
                row = session.scalar(update(Profile).where(Profile.id == identifier, Profile.owner_id == owner_id,
                    Profile.version == expected_version).values(**_values(profile), version=expected_version + 1,
                    updated_at=func.now()).returning(Profile))
                if row is None:
                    if session.scalar(select(Profile.id).where(Profile.id == identifier, Profile.owner_id == owner_id)):
                        raise ProfileConflict("profile preview is stale")
                    raise ProfileNotFound("profile not found")
                return _snapshot(row)
        return await self._run(save)

    async def delete_profile(self, owner: int | str, profile_id: str | UUID, expected_version: int) -> None:
        owner_id, identifier = _owner(owner), UUID(str(profile_id))
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        def remove():
            with Session(self._engine) as session, session.begin():
                deleted = session.scalar(delete(Profile).where(Profile.id == identifier, Profile.owner_id == owner_id,
                    Profile.version == expected_version).returning(Profile.id))
                if deleted is None:
                    if session.scalar(select(Profile.id).where(Profile.id == identifier, Profile.owner_id == owner_id)):
                        raise ProfileConflict("profile preview is stale")
                    raise ProfileNotFound("profile not found")
        await self._run(remove)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            # Drain pending work before disposing. Shutdown itself never blocks the event loop.
            await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=False)
            await asyncio.to_thread(self._engine.dispose)
