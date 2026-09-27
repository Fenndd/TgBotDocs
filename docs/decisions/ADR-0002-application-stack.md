# ADR-0002. Application, Database, and Message Retrieval

Date: 2026-09-27. Status: accepted. Basis: [S-06-A3, S-07-A1/A3](../requirements/SOURCES.md).

## Choice

The user was offered Python + aiogram with SQLite or PostgreSQL, as well as the option to discuss another language. **Python + aiogram + PostgreSQL** was selected. One application instance receives updates from the standard Telegram Bot API using long polling. Only private chats are allowed.

SQLite was a simpler proposal for a single process; the user preferred PostgreSQL. This adds a local database service and its maintenance. The database choice by itself does not make the application distributed: the queue and document states remain in one process.

The standard Bot API was selected instead of a local Bot API Server, with explicit acceptance of the 20 MB per-file download limit. No lower custom product limit is added.

## Implementation Composition

The planned library set for the selected architecture: Python 3.12, aiogram 3, SQLAlchemy 2 + psycopg 3, Alembic, Pydantic 2, httpx, Pillow, and pypdfium2. This clarifies the composition; it does not mean installation has been completed. Exact compatible versions and the lockfile will be fixed in T02 after verification; support for the selected APIs will be checked there as well.

- PostgreSQL stores personal profiles; files and results are not written to it.
- SQLAlchemy and migrations describe the schema and its changes.
- Pydantic validates model inputs/outputs in strict mode.
- pypdfium2 and Pillow prepare pages locally; network links in documents are not followed.
- httpx calls the local llama-server; there is no cloud client.
- A public application HTTP server is not required in the first phase.

Sources: [aiogram](https://docs.aiogram.dev/en/latest/), [long polling](https://docs.aiogram.dev/en/latest/dispatcher/long_polling.html), [SQLAlchemy](https://docs.sqlalchemy.org/en/20/intro.html), [Pydantic](https://pydantic.dev/docs/validation/latest/concepts/models/), [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/readme.html). These support the component choices; they do not prove compatibility of the final environment.

## Failures and Consequences

If the database is unavailable, a profile change cannot be accepted as saved. Inference must not block message reception. On restart, documents are not restored: the temporary directory is cleaned before new files are accepted. The user is told to start a new input and upload the files again.

Scaling the number of instances, an external queue, a webhook, and the customer's server are outside this decision. Separate justification and tasks are required if the workload demands them.

## Clarification, 2026-09-27

[ADR-0005](ADR-0005-runtime-supervision-and-packaging.md) refines the implementation composition. SQLAlchemy 2 and psycopg 3 run in synchronous mode in a thread pool, because psycopg's asynchronous mode conflicts with asyncio subprocesses on Windows. The Python line is chosen when T01b starts (3.14 target, 3.13 fallback) instead of 3.12, and uv manages the interpreter and the lockfile. The stack selected by the user — Python, aiogram, PostgreSQL — is unchanged.
