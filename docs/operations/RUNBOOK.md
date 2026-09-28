# Operations Runbook

Status: T08 operator documentation, updated on 2026-09-28 against the current local implementation and delivery configuration. The design basis is [OPERATIONS](OPERATIONS.md), [STATE_MACHINE](../architecture/STATE_MACHINE.md), [ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md) and [SECURITY](../security/SECURITY.md). Every configuration key is described in [CONFIGURATION](CONFIGURATION.md).

What has been verified, and where: local checks and the current suite are recorded in [T08 local report](../testing/T08_LOCAL_REPORT.md); the product has also run with actual PostgreSQL and the CUDA runtime against a controlled Bot API session ([T06 report](../testing/T06_PROGRESS_REPORT.md)). These checks do not establish real-Telegram behavior or recognition quality. **Not yet verified:** the joint real-Telegram end-to-end test, the single required sealed 70-case T01c/T07 quality benchmark, the Windows scheduled-task installation and unattended restart behavior, the Linux container on a native Linux/NVIDIA host, native Linux backup/restore, and this runbook's procedures as a whole. Windows backup/fresh-target restore was checked against real PostgreSQL; see [BACKUP_RESTORE](BACKUP_RESTORE.md). Platform installation steps are in [INSTALL_WINDOWS](INSTALL_WINDOWS.md) and [INSTALL_LINUX](INSTALL_LINUX.md). A platform counts as working only after its own recorded run.

## Processes

| Process | Owner | Notes |
| --- | --- | --- |
| Bot (`python -m tgbotdocs run --config <file>`) | Windows Task Scheduler (direct Python invocation) or the Compose `app` service on Linux | One instance per data root. Long polling for `message` and `callback_query` updates. There is no HTTP server and no health endpoint |
| `llama-server` (pinned llama.cpp b11221) | Started and supervised by the bot | Listens on `127.0.0.1:RUNTIME_PORT` with a per-start API key. One slot and one active request. Its output is discarded (`stdout`/`stderr` go to the null device) |
| File-preparation workers | Started by the bot per file | Short-lived. They are terminated on timeout |
| PostgreSQL | Service manager (Windows service or the Compose `db` service) | Holds only users and profiles. Not supervised by the bot |

Children end with the bot: a Job Object with kill-on-close on Windows; a parent-death signal plus the container init on Linux. The bot also records its children's PID, start time and executable in `TEMPORARY_ROOT/.tgbotdocs-processes.json`, so that the next startup can terminate leftovers of a hard crash. A recycled PID never matches and is never terminated.

**Single instance.** A kernel lock on `<parent of TEMPORARY_ROOT>/.tgbotdocs-instance.lock` prevents a second bot on the same data. A second start fails with `application_already_running`. A crash releases the lock automatically. Do not delete the lock file to "unlock" the bot; if the lock is held, a bot is running.

## Network and Access

- At runtime, the bot's only remote application service is the Telegram Bot API over outbound HTTPS, for long polling, file transfer and message delivery. There is no inbound listener, webhook, published application port or application health endpoint. `check` makes no Telegram request. Software/model downloads during installation or maintenance are separate from bot runtime traffic.
- On Linux, Compose publishes no ports. The app has outbound access for Telegram and joins an internal `backend` network; PostgreSQL is reachable only as `db:5432` on that internal network and is not published to the host. The Compose `egress` network provides outbound connectivity; it is not a hostname allowlist.
- On Windows, keep PostgreSQL on loopback. The repository's local development cluster uses `127.0.0.1:55432`; a delivery installation must use the actual configured local port. Do not expose PostgreSQL beyond the host.
- `llama-server` listens only on `127.0.0.1:RUNTIME_PORT` (default `18081`) and uses a per-start API key. Do not publish that port. Document prompts cannot configure a remote model endpoint; the product has no cloud-recognition fallback.

## Startup Order

1. Validate the configuration path and data paths (`startup_temporary_root`).
2. Take the instance lock.
3. **Temporary cleanup first:** validate the ownership marker of `TEMPORARY_ROOT`, terminate recorded orphan children, recover interrupted creations and deletions, and delete every leftover job directory. Only then does the startup check the database or the model.
4. Prepare `runtime-temp/`, the owned directory for runtime key files.
5. Load the full configuration and the frozen configuration. Refuse on an identity mismatch or when `PROCESSING_S` differs from the frozen budget.
6. Start the minute cleanup sweep and child supervision.
7. Run PostgreSQL migrations and a health check.
8. Verify the runtime artifact hashes, then start `llama-server` and wait for its health check.
9. For `run`, queue `startup_completed` after local resources initialize, immediately before starting long polling. This does not confirm a successful Telegram GetMe or update fetch. `check` stops after the local startup checks and sends no startup alert.

If a `run` startup fails, it exits that attempt with a nonzero status and reports the specific content-free code where available. After the configuration has loaded, `run` also tries to send `startup_failed` to configured operators. The `check` command sends no Telegram alerts and writes no application log; some initialization failures are summarized as `local_startup_failed` (see [Startup Refusals](#startup-refusals)).

## Start, Stop and Check

- **Check without Telegram:** `python -m tgbotdocs check --config <file>` performs the local startup checks and stops. It prints `local_startup_verified` on success. It needs the GPU and starts `llama-server`; do not run it next to a running bot on the same data root, because the instance lock refuses it. `check` does not accept `--restart-on-failure`.
- **Start:** `python -m tgbotdocs run --config <file>`. For an unattended scheduled run, `python -m tgbotdocs run --restart-on-failure --config <file>` waits 60 seconds and retries an unexpected failure in the same Python process. A clean stop or cancellation exits the retry loop. It prints `tgbotdocs_starting` at startup.
- **Stop:** send an interrupt (Ctrl+C in a console) or stop the task/container. On Linux, aiogram handles SIGINT and SIGTERM; after a clean signal-handled stop, it prints `tgbotdocs_stopped`. On Windows, Ctrl+C still runs cleanup and exits with status 0, but does not print `tgbotdocs_stopped`. On a clean stop, the bot cancels all jobs, waits for cleanup and sends nothing more. The platform-specific setup steps are in [INSTALL_WINDOWS](INSTALL_WINDOWS.md) and [INSTALL_LINUX](INSTALL_LINUX.md); unattended Windows task behavior has not yet been verified on a clean installation.
- A **hard kill** is safe by design. The next startup terminates recorded orphans and deletes job leftovers before it accepts anything.

## Technical Log

- Location: `DATA_ROOT/logs/tgbotdocs.log`, UTF-8, written only by `run` (`configure_logging` in `service.py`). `check` writes no log file.
- Rotation: at **UTC midnight**. **7** previous files are kept (`tgbotdocs.log.YYYY-MM-DD`); older files are deleted automatically.
- The file handler accepts only structured `tgbotdocs.events` alerts and `job_finished` records. Dependency/root records, arbitrary messages, exception tracebacks and stack information are rejected at every level; WARNING/ERROR records can contain sensitive values too. Do not add another unfiltered persistent handler.
- Contents: event codes such as the alert codes below, `startup_failed` and `service_failed`, with timestamps. By design, the log holds no document content, passwords, tokens, file IDs, original filenames or full updates. Do not raise dependency loggers to INFO or DEBUG in production.
- Process output includes `tgbotdocs_starting` and startup failure text. `tgbotdocs_stopped` is printed only after a handled clean signal on Linux; Windows Ctrl+C does not print that line. `run --restart-on-failure` retries in-process and does not depend on a captured console-log file.
- PostgreSQL and the service manager keep their own logs. `llama-server` output is discarded.

## Operator Alerts

`OPERATOR_TELEGRAM_IDS` lists the operators. Telegram alerts are sent by `run`, not by `check`. An alert is a single line `<code> <UTC ISO time>`, with ` <random job ID>` appended only for `delivery_failed`. It never contains document content or user data. Alerts raised by `run` are also written to the technical log. Without operators, alerts go only to the log; `check` writes no application log.

**Delivery caveat:** before long polling starts, the Telegram sender does not exist yet. Alerts raised during startup (`temporary_startup_failed`, `intake_closed`, `intake_reopened` and `temporary_ownership_failed` from the startup cleanup) therefore go **only to the log**. A failed `run` startup still reaches operators through `startup_failed`, sent directly and best effort if configuration loaded and operators are configured. `check` sends no alerts.

The table lists every code the application can emit (found by searching `src/` for `alert(`, `_alert(` and `Alerts`).

| Code | Source | Meaning | Operator action |
| --- | --- | --- | --- |
| `startup_completed` | `application/service.py:93` | Local resources initialized; long polling is about to start | None. It confirms a (re)start. Unexpected repeats mean `run --restart-on-failure` retried or the task/container restarted the bot; check for `service_failed` |
| `startup_failed` | `application/service.py:172-173` (log and `_notify_failure`) | A `run` startup failed before the product was composed | Read the printed startup error (see [Startup Refusals](#startup-refusals)). This alert is sent only if configuration loaded and operators are configured; `check` sends none |
| `service_failed` | `application/service.py:172-173` | A `run` attempt stopped on an unexpected error | Check the log and process output. With `--restart-on-failure`, the same process waits 60 seconds and retries; otherwise follow the configured task/container policy |
| `temporary_startup_failed` | `application/lifecycle.py:240` | Startup cleanup of `TEMPORARY_ROOT` failed: the root is unsafe or unowned, a marker or manifest is invalid, or orphan termination failed. Startup refuses. Log only | See [Closed Intake and Failed Cleanup](#closed-intake-and-failed-cleanup). Do not delete markers |
| `intake_closed` | `application/lifecycle.py:243`, `:429` | A job directory could not be deleted after 5 attempts with backoff. New documents are refused as temporarily unavailable for **all** users; retries continue every minute. At startup (`:243`) the bot refuses to start with `temporary_cleanup_incomplete` | Find what holds the files: an antivirus scan, a backup or indexing tool, a user shell, permissions or a failing disk. Remove the cause; do not delete files by hand. Wait for `intake_reopened` |
| `intake_reopened` | `application/lifecycle.py:418`, `:449` | All pending deletions succeeded; intake is open again | None |
| `temporary_ownership_failed` | `application/lifecycle.py:422` | During cleanup, a job directory failed the ownership checks: it is not a `job-` directory under the root, its marker does not match, or it contains a symlink or junction. Intake stays **closed until restart** (fail-closed) | Stop the bot and inspect `TEMPORARY_ROOT`. Find who created or changed files there. Escalate to the developer before restarting |
| `database_available` / `database_unavailable` | `application/health.py:66` | PostgreSQL health check (every 30 s, 10 s timeout) changed state. While unavailable, new documents are refused before download; admitted jobs keep their deadlines | Check the PostgreSQL service, the disk and credentials. Recovery is automatic |
| `runtime_unavailable` / `runtime_available` | `application/health.py:90` | `llama-server` health changed state. While unavailable, new documents are refused before download | Automatic restarts follow (next row). If it stays unavailable, see [Runtime Unavailable](#runtime-unavailable) |
| `runtime_restarted` | `application/health.py:82` | The bot restarted `llama-server` inside the GPU scheduler slot, because it had exited, did not release its slot, or failed 3 health checks. The restart succeeded | None if it is rare. If it repeats, check GPU memory pressure from other programs and the driver |
| `password_attempt_surge` | `application/product.py:184` | 30 failed password attempts across all users within 15 minutes; at most one alert per 15 minutes. There is deliberately no global lock | If the attempts are not explained, rotate `SHARED_PASSWORD` (a restart is required and signs everyone out) and tell users the new password through a separate channel |
| `password_message_deletion_failed` | `application/product.py:105` | The bot could not delete a user's password message in Telegram | The password may remain visible in that user's chat history. Consider rotating the password if the risk matters |
| `delivery_failed` (+ job ID) | `application/documents.py:517` | A result could not be delivered completely: Telegram refused a part, or delivery was uncertain within `DELIVERY_S`. The user was told to resend. A user who blocked the bot does not trigger it | Occasional events are expected with network trouble. Repeats point to Telegram or network problems |

## Startup Refusals

A foreground single-attempt `run` reports a specific startup code where available. `run --restart-on-failure` records fixed `startup_failed`/`service_failed` and `service_retry_scheduled` events without raw exception text; use the no-Telegram `check` command to diagnose local configuration/dependencies. `check` preserves ordinary configuration and model errors but wraps several initialization failures as `local_application_failed: local_startup_failed`; this includes temporary cleanup, invalid frozen configuration and database initialization failures. `check` sends no alerts and writes no application log, so its summary does not reveal the underlying code. The codes below are the underlying `run` codes unless marked as `check` behavior.

| Code | Cause |
| --- | --- |
| `configuration_must_be_external_absolute_file` | `--config`/`TGBOTDOCS_CONFIG` missing, relative, or inside the checkout |
| `configuration_invalid_or_missing` | The file cannot be read, a required key is missing, or a number does not parse |
| `data_path_must_be_external_absolute`, `data_path_must_not_use_virtualized_appdata`, `temporary_root_must_be_inside_data_root` | Path rules ([CONFIGURATION](CONFIGURATION.md#paths)) |
| `bot_token_required`, `shared_password_minimum_16_characters`, `postgresql_psycopg_url_required`, `invalid_runtime_port`, `invalid_timer_setting`, `invalid_capacity_setting`, `runtime_executable_and_sha256_required_together`, `invalid_runtime_executable_override` | Invalid values |
| `application_already_running`, `unsafe_instance_lock` | Another instance holds the lock, or the lock path is a link |
| `temporary_startup_failed`, `temporary_cleanup_incomplete` | Temporary cleanup failed or left pending deletions ([below](#closed-intake-and-failed-cleanup)) |
| `unsafe_runtime_temporary_root`, `unowned_runtime_temporary_root`, `unowned_runtime_temporary_file` | `runtime-temp/` is a link, lacks its marker while not empty, or holds foreign files |
| `invalid_frozen_configuration` | `FROZEN_CONFIG` is unreadable or invalid |
| `frozen_recognition_identity_mismatch_recalibrate` | The installation differs from the frozen identity ([Upgrades](#upgrading-dependencies-or-llamacpp)) |
| `processing_budget_differs_from_frozen_configuration` | `PROCESSING_S` differs from the frozen budget |
| `runtime_artifact_hash_mismatch`, `runtime_executable_missing` | A runtime file is missing or does not match its pinned SHA-256 |
| `runtime_executable_differs_from_frozen_recalibrate` | The override executable's SHA-256 differs from the frozen runtime identity; startup refuses until the frozen identity is legitimately rechecked and updated |
| `runtime_port_in_use`, `runtime_start_failed` | Another program uses `RUNTIME_PORT`, or `llama-server` exited or never became healthy |
| `database operation failed` | `run`: PostgreSQL was unreachable or a database operation/migration failed. `check` reports `local_startup_failed` for this initialization failure |
| `local_startup_failed` | `check` wrapper for temporary cleanup, invalid frozen configuration, or database initialization failures; `check` does not report the underlying code |
| `local_application_failed; check configuration and local dependencies` | `run`: another unexpected error without a more specific content-free code |

## Closed Intake and Failed Cleanup

Deletion is fail-closed: the bot never reports a deletion that did not happen, and it never deletes a directory it cannot prove it owns.

**What is in `TEMPORARY_ROOT`**

| Entry | Purpose |
| --- | --- |
| `.tgbotdocs-owner.json` | Ownership marker: application `tgbotdocs-temporary-v1`, a random owner ID and the root path. It is the proof that this root and its jobs belong to the bot |
| `.tgbotdocs-processes.json` | Identities of the bot's child processes, used after a crash |
| `.tgbotdocs-create.json`, `.tgbotdocs-delete.json` | Short-lived intents that make job creation and deletion recoverable after a crash |
| `*.writing` | Atomic-write sidecars of the files above |
| `job-<32 hex>/` with `.tgbotdocs-job.json` | One document job: originals and prepared pages. The marker is removed last |

In the parent directory: `.tgbotdocs-instance.lock`, and `runtime-temp/` with `.tgbotdocs-runtime-temp.json` and, while the runtime runs, one `tgbotdocs-runtime-key-*` file.

**Never delete or edit by hand:** the owner marker, job markers, intent files, `*.writing` sidecars, the process manifest, the runtime-temp marker, or the instance lock. Deleting a marker does not "fix" cleanup. It removes the ownership proof, and the next startup then refuses the root as unowned (fail-closed). Never place other files in `TEMPORARY_ROOT` or `runtime-temp/`; never make them, or anything inside them, a symlink or junction.

**Procedure while running (`intake_closed`)**

1. Users get "Temporarily unavailable". Admitted jobs continue.
2. Find the process holding the files: antivirus, backup, search indexing, an open Explorer or shell window, or permissions. The pending paths are retried every minute.
3. Remove the cause. `intake_reopened` follows automatically. No restart is needed.

**Procedure at startup (`temporary_startup_failed` or `temporary_cleanup_incomplete`)**

1. Read the service output for the code. The log records the alert codes.
2. Check that the path in `.tgbotdocs-owner.json` equals the configured `TEMPORARY_ROOT`. A moved or renamed root does not match its marker.
3. Check for links and junctions anywhere under the root, foreign files, and files locked by other programs.
4. Restart once the cause is removed. Startup repeats the whole cleanup.
5. Never use a broad recursive deletion as recovery. First confirm that the configured `TEMPORARY_ROOT` is the intended dedicated directory (normally `DATA_ROOT/temporary`), not `DATA_ROOT/models`, `logs`, `frozen`, or another directory containing persistent files. List its exact contents. Expected names alone do not prove ownership: only a valid owner marker does. If the path is misconfigured or contains any unexpected file, correct the configuration and preserve the data; do not delete the path. If isolation is necessary, stop the bot and all its children, verify the exact source and a non-existing quarantine destination, then move the dedicated temporary directory aside for review. Unknown or unmarked contents require escalation; this manual recovery has **not been verified**.

## Runtime Unavailable

- A dead, unreleased or repeatedly failing runtime is restarted automatically within the GPU slot. While it stays unavailable, a restart is retried about every 10 failed checks (about 5 minutes).
- Check the GPU and driver (`nvidia-smi`), other programs using VRAM, whether another program took `RUNTIME_PORT` on `127.0.0.1`, and that the runtime files still match their hashes. `check` reports hash and port problems, but only with the bot stopped.
- `llama-server` output is discarded by design, so the runtime has no separate log. Reproduce problems with the T01 tooling ([T01_PROCEDURE](../testing/T01_PROCEDURE.md)), not by enabling request logging in production.

## Database Unavailable

- The bot keeps running and refuses new documents until the health check passes. Profiles cannot be listed or saved meanwhile; users see "Storage is temporarily unavailable" or "Your profiles could not be read".
- Check the PostgreSQL service or container, the disk space, and the role and password in `DATABASE_URL`. The Windows development cluster is described in [POSTGRESQL_DEVELOPMENT](POSTGRESQL_DEVELOPMENT.md).
- Do not enable SQL statement or parameter logging. It would copy profile text into the PostgreSQL log.

## Restarts and Stale Updates

- Nothing about jobs survives a restart: sign-ins, documents, queue, previews and drafts live only in memory. Profiles persist.
- Telegram keeps undelivered updates, and long polling receives them after the restart. Messages dated before the start second are handled in **stale mode**: they are not processed, and a stale message that equals the password is deleted. Each affected user gets one notice: "The bot restarted. Send /start to sign in and resend your document." Buttons from the previous process answer "Session expired".
- Exactly-once processing across a crash is not promised. A result part already sent before a crash is not recalled.
- Changing `SHARED_PASSWORD` or any other configuration takes effect only after a restart.

## Backup and Restore

These are principles; no backup tooling is provided yet, and backup and restore have **not been verified**.

- **Back up only PostgreSQL:** the application database, which holds the tables `users` and `extraction_profiles` and Alembic's version table. Use the PostgreSQL tools of the installed major version (`pg_dump`/`pg_restore`) with credentials kept outside the backup file.
- **Never back up** `TEMPORARY_ROOT`, `runtime-temp/`, the logs, documents, results or evidence. Exclude `DATA_ROOT/temporary` from host-level backup and antivirus quarantine rules as well. A backup is not a document archive (DATA_MODEL).
- The configuration file and secrets are the environment owner's responsibility. Store them separately from the database backup, encrypted.
- The model, projector and runtime files are re-downloadable pinned artifacts; they are verified by hash rather than backed up.
- **Restore** brings back users and profiles only. It does not revive document jobs, queues, sign-ins or drafts. After a restore, start the bot normally; migrations run automatically, and startup cleans any temporary leftovers.
- A profile deleted after the backup reappears after a restore. Tell users if that matters.

## Upgrading Dependencies or llama.cpp

- The frozen configuration pins the recognition code hash, the prompt, the llama.cpp build `b11221` with the hashes of the executable, model and projector, the launch profile, the core settings, and the Python, `httpx`, `Pillow`, `pypdfium2`, `pydantic` and `pydantic-core` versions. Any change refuses startup with `frozen_recognition_identity_mismatch_recalibrate`. This is intended.
- An upgrade of llama.cpp, the model or any identity dependency requires the T01 re-checks: streaming cancellation and slot release, the runtime profile, and restart. If recognition output can change, the calibration and the benchmark must be repeated, and a new frozen configuration must be produced ([T01_PROCEDURE](../testing/T01_PROCEDURE.md), ADR-0005). Never edit the frozen file to match a new version.
- Other Python dependencies, such as `aiogram`, `SQLAlchemy`, `psycopg` or `alembic`, are outside the identity. They still change only through `uv.lock` (`uv sync --locked`) followed by the full test suite and a `check` run.
- Keep the Python installation, the lockfile and the frozen configuration together per release.

## Secrets Handling

- The secrets are `BOT_TOKEN`, `SHARED_PASSWORD` and the credentials in `DATABASE_URL`. The llama-server API key is generated per start and never configured.
- Keep the configuration file outside the source tree, readable only by the service account and administrators. Never commit it, paste it into tickets, or print it. Validation messages never echo values.
- Do not put secrets in environment variables that other processes log. `llama-server` receives its key through a file in `runtime-temp/`, not on its command line.
- Rotate the bot token through BotFather and the password by editing the file, then restart. Tell users the new password through a separate channel.
- Operators receive alerts only. The product has no feature to read users' documents or profiles.
- Disable adding the bot to groups in BotFather.
