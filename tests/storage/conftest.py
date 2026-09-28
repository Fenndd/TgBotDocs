"""Real PostgreSQL checks opt in explicitly; every test owns a random schema."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import URL, create_engine, text

from tgbotdocs.storage import ProfileStore


@pytest.fixture
def database_url():
    url = os.environ.get("TGBOTDOCS_TEST_DATABASE_URL")
    credentials_path = os.environ.get("TGBOTDOCS_TEST_DATABASE_CREDENTIALS")
    if not url and credentials_path:
        # Only the caller-selected development credential file. Never print its contents.
        credentials = json.loads(Path(credentials_path).read_text(encoding="utf-8"))
        url = URL.create("postgresql+psycopg", username=credentials["username"],
            password=credentials["password"], host=credentials["host"], port=credentials["port"],
            database=credentials["database"])
    if not url:
        pytest.skip("set TGBOTDOCS_TEST_DATABASE_URL or TGBOTDOCS_TEST_DATABASE_CREDENTIALS")
    return url


@pytest.fixture
async def storage(database_url):
    schema = "test_" + uuid4().hex
    engine = create_engine(database_url, hide_parameters=True)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    store = ProfileStore(database_url, schema=schema)
    await store.migrate()
    try:
        yield store, schema, engine
    finally:
        await store.close()
        # Only the random schema created by this fixture, never the application schema.
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
