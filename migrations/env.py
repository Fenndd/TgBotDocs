"""Migrations accept an injected connection or an explicit external environment URL."""
import os

from alembic import context
from sqlalchemy import create_engine

from tgbotdocs.storage.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    url = os.environ.get("TGBOTDOCS_DATABASE_URL")
    if not url:
        raise RuntimeError("TGBOTDOCS_DATABASE_URL is required")
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
