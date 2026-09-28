# Backup and Restore of Persistent Data

Status: the revised Windows procedure was verified on 2026-09-28 against disposable databases on the local PostgreSQL 18.6 cluster, using PowerShell 7.6.5 and Windows PowerShell 5.1.26100.9444. The checks covered backup, verification, fresh-target restore, unexpected tables/archives and cleanup failures. A clean installation, the delivered Windows service and every Linux command below remain **unverified**. No existing application rows were changed by these checks.

This implements T08 delivery item 7 ([T08](../../specs/T08-delivery.md)); the persistence boundary comes from [DATA_MODEL](../architecture/DATA_MODEL.md) and [SECURITY](../security/SECURITY.md). Installation-specific configuration is described in [CONFIGURATION](CONFIGURATION.md), [INSTALL_WINDOWS](INSTALL_WINDOWS.md) and [INSTALL_LINUX](INSTALL_LINUX.md).

## Included Data and Guard Conditions

A backup contains exactly these tables:

| Table | Contents |
| --- | --- |
| `public.users` | Telegram IDs of profile owners and creation times |
| `public.extraction_profiles` | Current personal profiles; no previous revisions |
| `public.alembic_version` | Schema migration version |

The table structure, keys, owner index and `users.telegram_id` sequence are included. Roles, passwords and grants are excluded by `--no-owner --no-privileges`. Configuration, originals, prepared pages, OCR, extracted values, results, evidence, temporary jobs, logs, model weights and runtime binaries are excluded.

The Windows script checks **all ordinary and partitioned tables outside PostgreSQL's system schemas**, including tables outside `public`. It refuses any source table set other than the three above. It then checks the custom archive listing against the permitted tables, their keys/defaults, the known owner index and the known identity sequence. An unexpected table, schema or archive object type is refused. A future migration that changes these objects requires review of DATA_MODEL and the script's allowlist.

Restore only accepts trusted archives produced by the reviewed backup process. A permitted table listing does not audit arbitrary SQL embedded inside an attacker-created archive. The SHA-256 identifies the saved file; retain it through an independently trusted channel if using it to check provenance.

## Windows Prerequisites and Connection Files

Run the script from the installed source/package checkout. Supply both `-DataRoot` and `-PgBin`; there are no personal-machine defaults. `DataRoot` must be an existing absolute directory outside the checkout and AppData. `PgBin` is the absolute directory containing the installed `psql.exe`, `pg_dump.exe`, `pg_restore.exe`, `createdb.exe` and `dropdb.exe`. Match the tools to the supported PostgreSQL installation. Dump and connection-file paths must also be absolute and outside the checkout and AppData.

Supply exactly one connection source:

- `-ConfigPath`: an external application `.env` containing `DATABASE_URL`. The script uses the installed application's Python, python-dotenv with interpolation disabled and SQLAlchemy's URL parser. Supply `-PythonExe` when its path differs from `<package>\.venv\Scripts\python.exe`. The parser supports `postgresql` and `postgresql+psycopg` URLs and an optional `sslmode` query parameter; other URL query parameters are refused rather than silently ignored.
- `-CredentialFile`: an external private JSON file with `host`, `port`, `database`, `username` and `password`, plus optional `sslmode` (default `prefer`). Existing explicitly selected development JSON files with `admin_username` and `admin_password` remain supported.

Backup uses the application connection. Verify and Restore additionally need a role that can create a database owned by the application role and subsequently drop that database. Supply `-AdminCredentialFile` using the same JSON shape, host, port and SSL mode; its `database` may be `postgres`. Without it, the legacy admin keys are used when present, otherwise the application role is used and must already have the necessary privileges. The script grants no privileges and changes no existing role.

Protect the connection files before use; the script does not modify their ACLs. Passwords and the full connection URL are not printed or supplied as command arguments. Native PostgreSQL diagnostics are suppressed because they can contain SQL or data. Connection passwords pass through the child tools' `PGPASSWORD` environment, and the script restores the affected process environment in `finally`.

For a locally reviewed script, an operator may open a session with a process-only execution policy; this does not change the machine policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass
# Alternatively: pwsh.exe -NoProfile -ExecutionPolicy Bypass
```

In that session, from the package/checkout root, set the actual external paths. The paths below are examples and must already exist:

```powershell
$common = @{
    DataRoot = 'D:\TgBotDocsData'
    PgBin = 'C:\PostgreSQL\18.6\bin'
    ConfigPath = 'D:\TgBotDocsConfig\tgbotdocs.env'
    PythonExe = 'C:\TgBotDocs\.venv\Scripts\python.exe'
    AdminCredentialFile = 'D:\TgBotDocsConfig\postgres-admin.json'
}
$dump = 'D:\TgBotDocsBackup\profiles-2026-09-28.dump'

& .\scripts\backup-postgres.ps1 @common -Action Backup -DumpPath $dump
& .\scripts\backup-postgres.ps1 @common -Action Verify -DumpPath $dump
& .\scripts\backup-postgres.ps1 @common -Action Restore -DumpPath $dump `
    -TargetDatabase tgbotdocs_restored_20260928
```

For JSON-only operation, replace `ConfigPath` and `PythonExe` with `CredentialFile`; do not supply both connection sources. The hashtable is splatted into the script in the current session, not into a second native `powershell.exe` process.

## Backup, Verify and Fresh-Target Restore

**Backup** writes a custom-format archive as the application role. It refuses an existing path, atomically creates a new file and removes inherited permissions/grants the current Windows account full control before writing data. A failed dump/listing check removes only that newly created archive. The script prints its path, size and SHA-256. It does not delete older backups.

**Verify** creates a random `tgbotdocs_verify_<random>` database owned by the application role and restores into it in one transaction. It compares the complete restored table set and each permitted table's row count and MD5 of all rows in primary-key order with the **current source**. UTC/ISO session formatting is fixed for the comparison. Verify immediately after Backup with writes paused for a stable comparison: changes after the dump legitimately cause a difference. This comparison is a data consistency check, not archive authentication.

Verify drops only the scratch database created by that invocation. A restore/comparison error remains the primary error if cleanup also fails; the warning identifies the owned scratch name for manual cleanup. If comparison succeeds but cleanup fails, Verify returns a failure rather than reporting complete success. Record the exact leftover name and have the authorized database administrator remove that owned database; do not drop other databases.

**Restore** creates a fresh database named by `-TargetDatabase`, using `template0` and UTF-8 and making the application role its owner. The source/live name and every existing database are refused. There is no `-Force` or in-place replacement path. `pg_restore --single-transaction --exit-on-error --no-owner --no-privileges` commits all permitted objects together; it does not use `--clean`. If restore fails, the script attempts to drop only the target it just created and preserves the original error if cleanup also fails. A successful Restore leaves the new database available for inspection.

Inspect the new database before changing application configuration. Switching the external `DATABASE_URL` to it, stopping/starting the bot and retiring the old database are separate deliberate operator actions; follow [OPERATIONS](OPERATIONS.md). Keep the previous database until the replacement is accepted. Restored profiles reflect the backup time: subsequent edits disappear and subsequently deleted profiles can reappear. Jobs, queues, uploads, drafts and authenticated sessions do not resume; users must sign in and resubmit documents after restart.

## Linux Docker Compose Procedure — Not Executed

The delivered Compose files now exist, but native Linux backup/restore has not been run. Follow [INSTALL_LINUX](INSTALL_LINUX.md) for the reviewed image references, exported paths and Compose wrapper. The examples use the container's local PostgreSQL socket, the `tgbotdocs` application role and the `tgbotdocs_admin` bootstrap admin from that recipe. Do not substitute an unreviewed image to make backup commands start. The Windows script's source/archive guard is not automatically supplied by these manual commands.

First check the complete non-system table set and require exactly the three approved names. This prints table names only:

```sh
dc() { sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" "$@"; }
dc exec -T db psql -X -A -t -v ON_ERROR_STOP=1 -U tgbotdocs -d tgbotdocs <<'SQL'
select n.nspname || '.' || c.relname
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind in ('r', 'p')
  and n.nspname not in ('pg_catalog', 'information_schema')
  and n.nspname not like 'pg_toast%'
order by 1;
SQL
```

The host directory must be owned by the operator and mode `0700` **before** copying a dump into it. A host `umask` does not propagate into a container command: set `077` inside the container as well. `exec -T` disables pseudo-terminal transformation. Create a private random container directory and a new host archive path:

```sh
umask 077
# If this is a new operator-owned directory; review an existing directory's owner/mode first.
install -d -m 0700 /srv/tgbotdocs-backup
backup=/srv/tgbotdocs-backup/profiles-2026-09-28.dump
test ! -e "$backup" || exit 1
container_dir=$(dc exec -T db sh -eu -c '
  umask 077
  directory=$(mktemp -d /tmp/tgbotdocs-backup.XXXXXX)
  pg_dump --no-password -U tgbotdocs -d tgbotdocs --format=custom --no-owner --no-privileges \
    --table=public.users --table=public.extraction_profiles --table=public.alembic_version \
    -f "$directory/profiles.dump"
  printf "%s\n" "$directory"
')
# Inspect metadata and refuse unapproved tables, schemas or object types before copying/restoring.
dc exec -T db pg_restore --list "$container_dir/profiles.dump"
dc cp "db:$container_dir/profiles.dump" "$backup"
chmod 0600 "$backup"
sha256sum "$backup"
dc exec -T db rm -- "$container_dir/profiles.dump"
dc exec -T db rmdir -- "$container_dir"
```

These manual steps do not supply automatic failure cleanup. Record the exact random directory immediately and remove only that attempt's file/directory if a later command fails. A failure before the shell returns the directory can leave a private `/tmp/tgbotdocs-backup.*` directory; identify its ownership and contents privately before cleanup. Do not use a broad recursive delete or paste profile data into reports.

For verification or recovery, use a new, explicit disposable database. Copy the trusted dump into a private container directory and inspect its listing before creating the database. Each line below depends on the preceding line succeeding; stop on any error:

```sh
restore_dir=$(dc exec -T db sh -eu -c 'umask 077; mktemp -d /tmp/tgbotdocs-restore.XXXXXX')
dc cp "$backup" "db:$restore_dir/profiles.dump"
dc exec -T db chmod 0600 "$restore_dir/profiles.dump"
dc exec -T db pg_restore --list "$restore_dir/profiles.dump"
# This name must be new. createdb refuses an existing database.
target=tgbotdocs_restore_check_20260928
dc exec -T db createdb --no-password -U tgbotdocs_admin -O tgbotdocs -T template0 -E UTF8 "$target"
dc exec -T db pg_restore --no-password -U tgbotdocs -d "$target" \
  --single-transaction --exit-on-error --no-owner --no-privileges "$restore_dir/profiles.dump"
```

Compare the complete non-system table set and, for each approved table, row count and checksum of all rows ordered by `telegram_id`, `id` or `version_num`, respectively, against the stable source. Use identical UTC/ISO formatting. This manual Linux comparison has not been validated as equivalent to Windows Verify; retain that gap in the operational record.

After a verification attempt, drop only the database whose successful creation was recorded for that attempt, using `dc exec -T db dropdb --no-password -U tgbotdocs_admin "$target"`. Never run that cleanup after a failed `createdb`, which could mean the name already belonged to someone else. Remove only the copied file and its recorded directory with `rm` and `rmdir`. For a successful recovery, keep the newly restored database for inspection instead of dropping it; an application configuration switch requires a separate operator decision. No live `--clean` restore is part of this procedure.

## Protection and Retention

A dump contains profile instructions and owner identifiers. Keep it outside Git, the checkout, AppData and cloud-synchronized folders unless the environment owner has expressly selected that storage. Check copied files' permissions because destination inheritance can change access. Keep `.env`, PostgreSQL credential files, the Telegram token and shared password separate in the owner's chosen secret store. Never paste dump contents, secret files or data-bearing restore diagnostics into reports.

Backup scheduling, frequency, retention and eventual destruction are operator decisions. This script does not schedule, rotate or delete old dumps. File deletion does not guarantee physical erasure from SSDs or backup media.

## Verification Record — 2026-09-28

The revised script was exercised on the already-running local PostgreSQL **18.6** cluster with its 18.6 tools, using **PowerShell 7.6.5** and **Windows PowerShell 5.1.26100.9444**. All fixtures and temporary files were under the approved external data root. Tests created random owned source/target databases, migrated the source through the application store and saved two synthetic profiles for a recorded synthetic owner. They did not test against or delete preexisting application rows.

Verified:

- Both hosts: external `DATABASE_URL` configuration parsing, Backup, Verify, repeat-path refusal and source/live-name refusal.
- Fresh-target Restore: expected rows were restored; a second attempt targeting the existing restored database failed and preserved its row counts.
- Explicit legacy development JSON compatibility for Verify.
- An extra source table in `public` and an extra table in another schema each caused Backup refusal without an archive. A real custom archive containing an extra table was refused by Verify and Restore. A malformed archive was refused.
- Fault-injected scratch cleanup failure preserved the original data-mismatch error; successful comparison followed by cleanup failure returned an explicit incomplete-verification error. The test harness then dropped only its recorded leftover databases.
- Captured output was checked for the fixture passwords. Synthetic rows were deleted only by their recorded owner IDs in the owned fixture database; all owned fixture/scratch databases and credential/dump files were removed. Content-free result records remain outside the checkout.

The checks exposed and fixed Windows PowerShell 5.1 stdin/quote handling, process environment removal and hash calculation without a PowerShell module dependency. They are operational correctness checks, not recognition quality acceptance.

Not verified: clean-host installation, delivered-service execution/account permissions, unattended scheduling, a live configuration switch, other PostgreSQL/PowerShell versions, malicious archive SQL analysis, native Linux/container backup/restore or an accepted Linux runtime/image. Historical fixture rows from other sessions cannot be attributed by these tests and were left untouched; no claim is made that the live database contains no synthetic data.
