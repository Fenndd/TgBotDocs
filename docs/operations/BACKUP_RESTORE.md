# Backup and Restore of Persistent Data

Status: Windows procedure verified on 2026-09-28 against the development cluster from [POSTGRESQL_DEVELOPMENT](POSTGRESQL_DEVELOPMENT.md). The Linux Docker Compose commands are **not verified**: the Compose file does not exist yet, and Docker was not available on the development PC. Implements T08 delivery item 7 ([T08](../../specs/T08-delivery.md)); the data boundary comes from [DATA_MODEL](../architecture/DATA_MODEL.md) and [SECURITY](../security/SECURITY.md).

## What Is Included and Excluded

A backup contains exactly the three tables that PostgreSQL is permitted to hold:

| Table | Contents |
| --- | --- |
| `public.users` | Telegram user IDs of profile owners and creation times |
| `public.extraction_profiles` | Current personal profiles (no previous versions exist) |
| `public.alembic_version` | Schema migration version |

The table structure, keys, the owner index, and the `users.telegram_id` sequence come with them. Roles, passwords and grants are not included (`--no-owner --no-privileges`).

Never included: temporary job directories, originals, prepared pages, OCR, extracted values, results, evidence, logs, the external `.env`, the credential file, model weights, and the llama.cpp runtime. These either never enter PostgreSQL or are not backup material. A database backup is not a document archive.

Backup refuses to run when the application's `public` schema holds any table other than the three above, and checks the archive listing after the dump; a dump with any other table, schema, or object type is deleted and reported as a failure. A future migration that adds a table must first be reviewed against DATA_MODEL, then added to the list in the script.

## What a Restore Does Not Revive

Jobs, queues, uploaded files, dialogue state, unconfirmed drafts and authenticated sessions live only in memory or in the temporary directory and are never in the database. After a restore, users must log in again with the shared password and resubmit documents, exactly as after a restart. The restore also returns profiles to the state at backup time: later changes and deletions are lost, and deleted profiles reappear.

## Windows Commands

Run from the repository root in PowerShell (Windows PowerShell 5.1 or later). The script reuses the PostgreSQL 18.6 binaries under `C:\Users\nikit\TgBotDocsData\postgresql-18.6` and reads `C:\Users\nikit\TgBotDocsData\postgresql-dev-credentials.json` by default; `-DataRoot` and `-CredentialFile` select other locations. Credentials are passed to the tools only through the `PGPASSWORD` variable of the script process and are never printed.

```powershell
# Back up into a new file. The path must be absolute, outside the repository and outside AppData.
./scripts/backup-postgres.ps1 -Action Backup -DumpPath D:\TgBotDocsBackup\profiles-2026-09-28.dump

# Check the dump: restore it into a random scratch database, compare, then drop the scratch database.
./scripts/backup-postgres.ps1 -Action Verify -DumpPath D:\TgBotDocsBackup\profiles-2026-09-28.dump

# Restore into an explicit existing database owned by the application role.
./scripts/backup-postgres.ps1 -Action Restore -DumpPath D:\TgBotDocsBackup\profiles-2026-09-28.dump -TargetDatabase tgbotdocs_restored
```

- **Backup** writes a PostgreSQL custom-format archive with `pg_dump` as the application role. It refuses an existing file instead of replacing it. The file is created first and restricted to the current Windows account (inheritance removed) before any data is written. The script prints the file size and SHA-256; record the hash with the backup.
- **Verify** needs the admin role from the credential file, because the application role has no `CREATEDB` privilege. The admin role creates `tgbotdocs_verify_<random>` owned by the application role; the application role restores into it exactly as Restore does. The check compares the full table set of the scratch database with the permitted set and, for each permitted table, row count and an MD5 checksum of all rows in key order against the **current** source database. Run it right after Backup; a source change in between is reported as a difference. The scratch database is dropped even when the check fails.
- **Restore** runs `pg_restore --single-transaction --exit-on-error --clean --if-exists --no-owner --no-privileges` as the application role: any error rolls the whole restore back. `--clean` replaces only the three permitted tables in the target. The target must exist and be owned by the application role; create one as the admin role, for example `createdb.exe -h 127.0.0.1 -p 55432 -U tgbotdocs_dev_admin -O tgbotdocs_dev tgbotdocs_restored` (the tool prompts for the admin password). The live application database is refused unless `-Force` is added. Before restoring into the live database, stop the bot; after restoring, start it normally so startup cleanup and migrations run.

## Linux Docker Compose Equivalent (not verified)

ADR-0005 names the PostgreSQL service `db`. Replace `<db_user>` and `<db_name>` with the values of the delivered Compose configuration. Writing the archive inside the container and copying it avoids streaming a custom-format archive through a non-seekable pipe, which `pg_restore` cannot always reorder.

```sh
umask 077
docker compose exec db pg_dump -U <db_user> -d <db_name> --format=custom --no-owner --no-privileges \
  --table=public.users --table=public.extraction_profiles --table=public.alembic_version -f /tmp/profiles.dump
# Check that only the three tables (and their keys, index and sequence) are listed.
docker compose exec db pg_restore --list /tmp/profiles.dump
docker compose cp db:/tmp/profiles.dump /srv/tgbotdocs-backup/profiles-2026-09-28.dump
docker compose exec db rm /tmp/profiles.dump
chmod 600 /srv/tgbotdocs-backup/profiles-2026-09-28.dump

# Restore: stop the bot first, copy the dump in, restore in one transaction, remove the copy.
docker compose stop app
docker compose cp /srv/tgbotdocs-backup/profiles-2026-09-28.dump db:/tmp/profiles.dump
docker compose exec db pg_restore -U <db_user> -d <db_name> --single-transaction --exit-on-error \
  --clean --if-exists --no-owner --no-privileges /tmp/profiles.dump
docker compose exec db rm /tmp/profiles.dump
docker compose start app
```

These commands have not been executed. A separate Verify equivalent for Linux is not provided; until one is checked on the Linux host, restore into a separate database and compare the table set and row counts manually.

## Protecting Dumps and Secrets

- A dump contains the text users typed into their profiles, which may be sensitive. Treat it like the database: keep it outside Git, outside the repository, outside AppData and outside any folder synchronized to a cloud service unless the owner has decided otherwise.
- The script restricts each new dump to the current Windows account. Copying or moving a file can apply the destination's inherited permissions; check the permissions of copies.
- The credential file, the external `.env`, the Telegram token and the shared password are never part of a dump. Back them up, if at all, separately and in a secret store chosen by the environment owner (see [OPERATIONS](OPERATIONS.md)).
- Do not paste dump contents, `pg_restore` output containing row data, or credentials into reports or issue trackers.

## Retention

The script does not schedule backups, rotate files, or delete old dumps. How often to back up, how many dumps to keep, where to keep them, and when to destroy them are the responsibility of the environment owner. Deleting a file does not guarantee physical erasure from an SSD or from backup media.

## Verification Record (2026-09-28, Windows)

Run on the development cluster at 127.0.0.1:55432 with PostgreSQL 18.6, without stopping or starting it:

- The credential file contains `host`, `port`, `database`, `username`, `password`, `admin_username` and `admin_password`. The application role `tgbotdocs_dev` is not a superuser and has no `CREATEDB`; `tgbotdocs_dev_admin` has both. Verify therefore uses the admin role only to create and drop the scratch database.
- Two synthetic profiles for a random synthetic owner ID (at least 10^15) were saved through `tgbotdocs.storage.ProfileStore`.
- Backup produced a 6,282-byte archive; the file ACL listed only the current account with full control. A second Backup to the same path was refused. Relative, in-repository and AppData paths were refused.
- The first run rejected the archive because the listing check did not yet allow the `users.telegram_id` sequence entries; the dump was deleted automatically. After the check accepted sequences that belong to the permitted tables, `pg_restore --list` showed only `alembic_version`, `extraction_profiles` and `users` (tables, data, keys, owner index and that sequence).
- Verify created a random scratch database, matched the table set and the row counts/checksums of all three tables, and dropped the scratch database.
- Restore refused the live database without `-Force` and a missing `-TargetDatabase`; a restore into a nonexistent database failed without changes. Two consecutive restores into a throwaway database created by the admin role succeeded and left the expected row counts; the database was then dropped.
- The synthetic profiles and the synthetic user row were deleted, the dump files were deleted, and the cluster's database list was back to `postgres`, `template0`, `template1` and `tgbotdocs_dev`.

Not verified: Restore with `-Force` into the live application database, the Backup refusal for an unexpected table in the application schema, and every Linux command above.
