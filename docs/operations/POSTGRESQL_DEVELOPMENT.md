# Native PostgreSQL Development

Status: verified on Windows on 2026-09-28 for the T02 database slice. This is an isolated development cluster, not the Windows service installation required for delivery by [ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md). The service wrapper and clean-machine installation remain T08 work.

## Installation and Control

Run from the repository root in PowerShell after the locked Python environment has been installed:

```powershell
./scripts/setup-postgres.ps1 -Action Initialize
./scripts/setup-postgres.ps1 -Action Status
.venv/Scripts/python.exe -m tgbotdocs.storage migrate --credentials C:/Users/nikit/TgBotDocsData/postgresql-dev-credentials.json
.venv/Scripts/python.exe -m tgbotdocs.storage health --credentials C:/Users/nikit/TgBotDocsData/postgresql-dev-credentials.json
```

`Initialize` creates a new cluster, random credentials, a non-superuser application role, and its database. It refuses to replace an existing cluster or credential file. The credential file is restricted to the current Windows account and SYSTEM. The default root is `C:\Users\nikit\TgBotDocsData`; `-DataRoot` can choose another location outside Git and outside LOCALAPPDATA. The distribution, cluster, credentials and technical logs stay there. Port 55432 and IPv4 loopback are used; `-Port` selects a different port at initialization. Supply that same port when subsequently starting this cluster. An occupied port causes an explicit failure.

The process starts with `Start-Process -WindowStyle Hidden`, without administrator access, service registration, a registry change, or boot startup. Control the existing process with:

```powershell
./scripts/setup-postgres.ps1 -Action Stop
./scripts/setup-postgres.ps1 -Action Start
```

`Stop` uses PostgreSQL's fast shutdown, which rolls back active transactions and flushes the cluster. It does not remove files. `Start` preserves the cluster and checks readiness. There is no reset/delete command. If initialization fails after creating the cluster, preserve its files and resolve the reported stage; rerunning initialization deliberately refuses to overwrite it.

The launch disables SQL statement and parameter logging and uses terse error verbosity so failed-row details do not copy profile settings into the technical log. Do not enable SQL echo or verbose error logging. A cluster restart is required after changing these launch options. PostgreSQL remains a separate development process when the bot exits; the delivery service lifecycle is separate from the bot's supervised inference children.

## Artifact Evidence

The [PostgreSQL Windows page](https://www.postgresql.org/download/windows/) links to the [EDB binary archive page](https://www.enterprisedb.com/download-postgresql-binaries). Its Windows x64 PostgreSQL 18.6 link resolved to [EDB file 1260566](https://sbp.enterprisedb.com/getfile.jsp?fileid=1260566).

The downloaded ZIP is 382,815,572 bytes, with SHA-256 `1df55002afe95b945d934c078b13e82c1603fa546731e511d068aa983b4ead28`. The setup script checks this pinned hash before extraction. `postgres.exe --version` returned `postgres (PostgreSQL) 18.6`; extracting the selected ZIP contents completed successfully. `Get-AuthenticodeSignature postgres.exe` returned `NotSigned`. A vendor-published or signed checksum for this exact ZIP was not established: the recorded hash is the local fingerprint of an artifact obtained through EDB's HTTPS link, not independent publisher authentication.

The script extracts `bin`, `lib`, `share`, the server license and command-line-tool notices. pgAdmin and StackBuilder are not installed. Data page checksums, UTF-8 and SCRAM-SHA-256 authentication are enabled. The default shared buffer allocation reported by `initdb` was 128 MB.

## Storage API and Verification

`tgbotdocs.storage.ProfileStore` uses SQLAlchemy 2 and synchronous psycopg 3 exclusively through a dedicated small executor. Each operation owns its connection/session/transaction. API methods are `migrate`, `health`, `list_profiles(owner)`, `get_profile(owner, id)`, `save_drafts(owner, drafts)`, `update_profile(owner, profile, expected_version)`, `delete_profile(owner, id, expected_version)` and `close`.

Owners are positive Telegram IDs; profile IDs are UUID strings. `save_drafts` takes a nonempty tuple of immutable recognition `ExtractionProfile` objects with that owner and version 1. Generate IDs once for the preview and reuse them on retries. All new drafts save in one transaction. An exact repeated confirmation returns the existing profiles; a partial/colliding/stale preview raises `ProfileConflict` without adding anything. An update carries the previewed version and increments it transactionally. Missing and foreign-owned profiles produce the same `ProfileNotFound` outcome. The database schema has only users, current profiles, and Alembic's version table; document contents and authenticated sessions have no table.

The optional `schema` parameter exists for disposable development/test schemas. Deployment must retain the migrations directory alongside the application or pass its actual path as `migration_root`; migrations are currently repository artifacts, not embedded wheel data. Alembic CLI usage accepts `TGBOTDOCS_DATABASE_URL`; never print that environment variable or paste it into logs. The development module command above builds the URL internally without displaying credentials.

Cancelling an awaiting coroutine does not cancel a PostgreSQL transaction already executing in its worker. Reuse the stable preview UUIDs when the confirmation outcome is uncertain. Close the store during shutdown to drain submitted work and dispose connections. Statement and lock timeouts bound normal operations; configuration/connection errors surface as content-free `StorageUnavailable` errors.

Run real database checks explicitly:

```powershell
$env:TGBOTDOCS_TEST_DATABASE_CREDENTIALS = 'C:/Users/nikit/TgBotDocsData/postgresql-dev-credentials.json'
.venv/Scripts/python.exe -m pytest tests/storage -q
.venv/Scripts/python.exe -m ruff check src/tgbotdocs/storage migrations tests/storage
```

Tests create a random schema for each case and drop only that generated schema. They never clear the application schema. Without an explicitly supplied test URL or test credential path, database cases skip; the unavailable-database check still runs. Verified checks cover migration idempotence/exact tables, transactional failure rollback, repeated and concurrent confirmation, cross-owner read/update/delete/ID reuse, optimistic competing updates/stale deletion, partial-preview collision, immutable list-schema snapshots, store reopening and safe connection failure. PostgreSQL process restart and retained synthetic profiles were also checked separately; these checks do not establish Windows-service, Linux, real Telegram, backup/restore, or T02 completion.
