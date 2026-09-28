"""Development migrations using an explicitly selected credential file outside Git."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy import URL

from .store import ProfileStore, StorageUnavailable


async def execute(action: str, credential_file: Path):
    credentials = json.loads(await asyncio.to_thread(credential_file.read_text, encoding="utf-8"))
    url = URL.create("postgresql+psycopg", username=credentials["username"], password=credentials["password"],
                     host=credentials["host"], port=credentials["port"], database=credentials["database"])
    store = ProfileStore(url)
    try:
        if action == "migrate":
            await store.migrate()
        await store.health()
    finally:
        await store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("migrate", "health"))
    parser.add_argument("--credentials", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(execute(args.action, args.credentials))
    except (OSError, KeyError, ValueError, StorageUnavailable):
        print("Database command failed; check local configuration and PostgreSQL availability.", file=sys.stderr)
        return 1
    print(f"Database {args.action} verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
