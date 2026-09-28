# Configuration Reference

Status: T08 operator reference, updated on 2026-09-28 from the current configuration and startup behavior. [`.env.example`](../../.env.example) is the safe template. When this document and the code disagree, the code wins; report the discrepancy.

## The Configuration File

The application reads one dotenv file:

```text
python -m tgbotdocs run   --config <absolute path to the external .env>
python -m tgbotdocs run --restart-on-failure --config <same external .env>
python -m tgbotdocs check --config <same path>
```

- `--config` is optional. Without it, the application reads the path from the environment variable **`TGBOTDOCS_CONFIG`**. With neither, startup fails with `configuration_must_be_external_absolute_file`.
- The path must be **absolute** and **outside the source checkout**, the directory that contains `src/tgbotdocs`. A relative path or a file inside the checkout is refused. The tracked `.env.example` is never read.
- The file is parsed with `python-dotenv` and **no variable interpolation**, so `$` in a password is literal. Process environment variables do **not** override keys in the file.
- A key whose value is empty, such as `OPERATOR_TELEGRAM_IDS=`, uses its default.
- `run` reports configuration validation failures as short content-free codes, printed as `local_application_failed: <code>`. It never echoes a value. `check` wraps some initialization failures (temporary cleanup, invalid frozen configuration and database startup failures) as `local_application_failed: local_startup_failed`; see [Startup Refusals](RUNBOOK.md#startup-refusals).
- The file contains secrets. See [Secrets](RUNBOOK.md#secrets-handling).

`check` runs the local startup without contacting Telegram: temporary cleanup, configuration, migrations, and a start and stop of the pinned model runtime. It needs the GPU and starts `llama-server`; it sends no Telegram alerts and writes no application log. Do not use `--restart-on-failure` with `check`.

`run --restart-on-failure` waits 60 seconds and retries an unexpected failure in the same Python process. A clean stop or cancellation ends the retry loop. The flag is for unattended `run`, such as the Windows scheduled task; installation and unattended stop behavior remain subject to platform verification.

## Paths

| Key | Type | Default | Validation | Meaning |
| --- | --- | --- | --- | --- |
| `DATA_ROOT` | absolute path | required | Absolute; outside the checkout; no path component named `AppData` or `LocalCache` (case-insensitive) | Root of the installed runtime and model files and the technical logs. The frozen runtime files are expected at `DATA_ROOT/runtime-b11221/llama-server.exe`, `DATA_ROOT/models/Qwen3VL-4B-Instruct-Q4_K_M.gguf` and `DATA_ROOT/models/mmproj-Qwen3VL-4B-Instruct-F16.gguf` (`recognition/runner.py`, `runtime_files`). The logs go to `DATA_ROOT/logs/` |
| `TEMPORARY_ROOT` | absolute path | `DATA_ROOT/temporary` | Same rules as `DATA_ROOT`. It must be strictly **inside** `DATA_ROOT` and must not equal it (`temporary_root_must_be_inside_data_root`) | Owned working directory for document jobs (originals, prepared pages) and the process manifest. Its **parent** directory also holds the instance lock `.tgbotdocs-instance.lock` and the runtime key directory `runtime-temp/` |
| `FROZEN_CONFIG` | absolute path | required | Absolute; outside the checkout; not under `AppData`/`LocalCache`. It must parse as a frozen recognition configuration (`invalid_frozen_configuration`) | The frozen T01b recognition configuration: prompt, runtime launch profile, core settings and policy, and admission page times. See [Values That Must Match the Frozen Configuration](#values-that-must-match-the-frozen-configuration) |

The `AppData`/`LocalCache` rule exists because some desktop apps on Windows redirect `%LOCALAPPDATA%` into a private virtualized folder. Data placed there becomes invisible to other programs. Use a plain location such as `C:\TgBotDocsData\...` or a user folder outside `AppData`.

## Secrets and Connections

| Key | Type | Default | Validation | Meaning |
| --- | --- | --- | --- | --- |
| `BOT_TOKEN` | string, secret | required | Nonempty. It must contain `:`, and the part before the first `:` must be digits (`bot_token_required`) | Telegram Bot API token from BotFather |
| `SHARED_PASSWORD` | string, secret | required | At least 16 characters (`shared_password_minimum_16_characters`) | The shared sign-in password. Use a random string. A change takes effect only after a restart; sign-ins do not survive a restart |
| `DATABASE_URL` | SQLAlchemy URL, secret | required | Must start with `postgresql+psycopg://` (`postgresql_psycopg_url_required`) | PostgreSQL connection for profiles. The Windows development setup uses `postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/tgbotdocs_dev`; Linux Compose uses `db:5432` on its internal network, without a published port. Match the URL to the actual local installation, keep PostgreSQL unexposed, and use a non-superuser application role. Migrations run automatically at startup |

The llama-server API key is **not** configured. Each application start generates a new random key and passes it to `llama-server` through a key file in `runtime-temp/`. The application removes the file when the runtime stops, and startup removes any key file a crash left behind. The runtime listens only on `127.0.0.1`.

## Runtime Selection

| Key | Type | Default | Validation | Meaning |
| --- | --- | --- | --- | --- |
| `RUNTIME_PORT` | integer | `18081` | 1–65535 (`invalid_runtime_port`). The port must be free on `127.0.0.1` at start (`runtime_port_in_use`) | Loopback port for the supervised `llama-server` |
| `RUNTIME_EXECUTABLE` | absolute path | unset | Set together with `RUNTIME_EXECUTABLE_SHA256` or not at all (`runtime_executable_and_sha256_required_together`). The path must be absolute (`invalid_runtime_executable_override`) | **Linux image only.** Selects another platform's build of the pinned llama.cpp release b11221 instead of `DATA_ROOT/runtime-b11221/llama-server.exe`. Leave it unset on Windows |
| `RUNTIME_EXECUTABLE_SHA256` | 64 lowercase hex characters | unset | Exactly 64 characters, `0-9a-f` only (`invalid_runtime_executable_override`) | The expected SHA-256 of `RUNTIME_EXECUTABLE`. The file is hashed at start; a mismatch refuses startup with `runtime_artifact_hash_mismatch`. Its hash must also match the frozen runtime identity |

The override replaces only the executable. The model and projector are still read from `DATA_ROOT/models/` and checked against their pinned hashes. A runtime executable whose SHA-256 differs from the frozen identity is refused with `runtime_executable_differs_from_frozen_recalibrate`; it does not start with an alert or silently change the frozen identity. Relocating the identical executable is allowed when both hashes match. This hash check does not verify the Linux image on a native Linux/NVIDIA host; that platform remains unverified.

## Timers and Capacity

The timer keys are read as floating-point seconds; each must be finite and greater than 0 (`invalid_timer_setting`). The capacity keys are integers of at least 1 (`invalid_capacity_setting`). A value that does not parse as a number fails with `configuration_invalid_or_missing`.

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `INACTIVITY_S` | seconds | `900` | Inactivity limit for page collection (Several pages), waiting for a user's answer, open profile drafts and previews. An album's absolute collection wait is measured from its admission. It also sets how long a finished album group is remembered for late parts |
| `PROCESSING_S` | seconds | `1800` | Cumulative processing budget per document. It **must equal** the frozen configuration's `core.processing_budget_s`, otherwise startup fails with `processing_budget_differs_from_frozen_configuration` |
| `QUEUE_TIMEOUT_S` | seconds | `900` | Maximum wait of a queue entry for the GPU before the job's first model call |
| `ALBUM_QUIET_S` | seconds | `2` | Quiet window after the last album part before the album counts as complete |
| `DELIVERY_S` | seconds | `60` | Window for sending all result parts |
| `ADMITTED_JOBS` | integer | `8` | Maximum number of non-terminal documents across all users. Above it, new documents are refused as Busy before any download |
| `DOWNLOAD_LIMIT` | integer | `2` | Concurrent Telegram file downloads across all users |
| `DELIVERY_ATTEMPTS` | integer | `3` | Attempts per result part. Only an explicit Telegram `retry_after` refusal is retried |

## Operators

| Key | Type | Default | Validation | Meaning |
| --- | --- | --- | --- | --- |
| `OPERATOR_TELEGRAM_IDS` | comma-separated integers | empty | Each item must parse as an integer; blank items are ignored | Telegram user IDs that receive content-free alerts. Each operator must have started a chat with the bot. Without operators, alerts go only to the technical log. See [RUNBOOK](RUNBOOK.md#operator-alerts) |

## Values That Are Not Configurable

These values are fixed in the code and listed here for reference: the per-user password limit (5 failures in 15 minutes; `access.py`); the global surge alert (30 failures in 15 minutes); the temporary quota (2 GiB) and free-disk reserve (2 GiB) (`lifecycle.py` defaults); cleanup retries (5 attempts with exponential backoff from 4 s, then a retry every minute); health checks (every 30 s, 10 s timeout; `health.py`); the 20 MB file limit (`download_sink.py`); up to 10 profile drafts per instruction (`compiler.py`); and log rotation at UTC midnight with 7 files kept (`service.py`).

## Values That Must Match the Frozen Configuration

Before it opens the database, startup compares the frozen configuration at `FROZEN_CONFIG` with the running installation. A mismatch refuses startup with `frozen_recognition_identity_mismatch_recalibrate`. The compared identity (`recognition/config.py`, `environment_mismatches`) covers:

- the SHA-256 of the recognition code (`src/tgbotdocs/recognition/*.py`);
- the prompt identity;
- the runtime artifacts: llama.cpp build `b11221` and the pinned SHA-256 values of `llama-server.exe`, the model and the projector;
- the runtime launch profile and core settings;
- the Python version and the installed versions of `httpx`, `Pillow`, `pypdfium2`, `pydantic` and `pydantic-core`.

In addition, `PROCESSING_S` must equal the frozen processing budget. Admission page times, quotas and the pixel limit come from the frozen file itself. They are not in `.env`.

Changing anything in this identity requires the T01 re-checks and possibly recalibration ([T01_PROCEDURE](../testing/T01_PROCEDURE.md)). Do not edit the frozen file by hand to make startup pass.

## Example

Illustrative Windows development configuration. Replace the paths and placeholders, and match the database URL to the PostgreSQL installation; the port and database below match the repository's Windows development setup. Never commit the real configuration.

```dotenv
DATA_ROOT=C:\TgBotDocsData\dev
FROZEN_CONFIG=C:\TgBotDocsData\dev\frozen\frozen-t01b.json
TEMPORARY_ROOT=C:\TgBotDocsData\dev\temporary
BOT_TOKEN=REPLACE_WITH_BOTFATHER_TOKEN
SHARED_PASSWORD=REPLACE_WITH_RANDOM_PASSWORD
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/tgbotdocs_dev
RUNTIME_PORT=18081
OPERATOR_TELEGRAM_IDS=
INACTIVITY_S=900
PROCESSING_S=1800
QUEUE_TIMEOUT_S=900
ALBUM_QUIET_S=2
ADMITTED_JOBS=8
DOWNLOAD_LIMIT=2
DELIVERY_S=60
DELIVERY_ATTEMPTS=3
# Linux image only:
# RUNTIME_EXECUTABLE=/opt/llama/llama-server
# RUNTIME_EXECUTABLE_SHA256=<64 lowercase hex characters>
```
