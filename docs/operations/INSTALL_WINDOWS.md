# Windows x64 Installation (T08)

Status: prepared on 2026-09-28. **The Windows delivery is not verified end to end.** The scripts below were parsed and dry-run on the development PC. Scheduled-task registration, PostgreSQL service registration, start at boot, and restart after failure were **not executed**, by design. A clean-machine run is still required ([T08](../../specs/T08-delivery.md)). Basis: [ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md), [OPERATIONS](OPERATIONS.md), [SECURITY](../security/SECURITY.md), [POSTGRESQL_DEVELOPMENT](POSTGRESQL_DEVELOPMENT.md).

## What Gets Installed

| Component | Source | Pin |
| --- | --- | --- |
| Application | This repository at the delivered commit | Git commit; `uv.lock` |
| Python 3.14.5 | uv (`uv python install`) | `.python-version`; the frozen configuration checks the exact version |
| Python dependencies | PyPI through `uv sync --locked --no-dev` | `uv.lock` |
| llama.cpp b11221, Windows CUDA 12.4 | [Official release](https://github.com/ggml-org/llama.cpp/releases/tag/b11221): `llama-b11221-bin-win-cuda-12.4-x64.zip` and `cudart-llama-bin-win-cuda-12.4-x64.zip` | Archive SHA-256 in `tools/t01/download_artifacts.py`; `llama-server.exe` SHA-256 in `src/tgbotdocs/recognition/runtime.py` |
| Qwen3-VL-4B-Instruct Q4_K_M and F16 vision projector | [Official Qwen GGUF repository](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF), revision `1cd86afb9a95c410a6038ab3b40d8b578c892266` | SHA-256 in `runtime.py` |
| Frozen recognition configuration `frozen-t01b.json` | Delivered by the developer with the release (it is not in Git) | SHA-256 `dd1d01a0e8ff878a60b7b4bf61b6bcb20939cd5bd5695bed4eaa79a55ea633f6` ([T01B report](../testing/T01B_CALIBRATION_REPORT.md)) |
| PostgreSQL 18.6 | EDB Windows x64 binaries linked from postgresql.org, through `scripts/setup-postgres.ps1` | Archive SHA-256 in that script |
| Bot supervision | Windows Task Scheduler (built in) | `deploy/windows/install-bot-task.ps1` |

## Supervision Wrapper: Scheduled Task

ADR-0005 leaves the choice to T08: a service or a scheduled task that starts at boot and restarts on failure. **Selected: a Task Scheduler task.**

- It is part of Windows. No third-party binary is added to the delivery, so there is nothing more to pin, verify, or license. NSSM and WinSW are third-party service wrappers; a pywin32 service would add a dependency and service code to the product.
- It launches Python directly at startup with `--restart-on-failure`, no execution time limit, and at most one instance. The application retries failed startup or polling after 60 seconds, once the failed attempt has released its resources; a normal stop ends supervision. The application also holds its own kernel instance lock (`application_already_running`).
- With the S4U logon type, the task runs whether or not the account is signed in, and **no password is stored**. S4U has no network credentials. The bot does not need them: its outbound HTTPS to Telegram and its loopback connections to PostgreSQL and llama-server work without them.
- The bot already supervises its own children (a llama-server in a kill-on-close Job Object). The scheduled task owns that Python process directly; there is no intermediate PowerShell child. Scheduler restart settings are an additional fallback for action failures, while application errors are handled by the explicit retry loop.

Known limits, which must be checked on the target (see "Not verified"):

- Boot, Scheduler action-failure recovery and session-0 CUDA remain unverified. Application retry and cancellation were checked with controlled dependency failures; this does not substitute for an elevated boot test.
- `Stop-ScheduledTask` terminates the task's process without the bot's graceful shutdown. The next start cleans the temporary root. The task action is the bot Python process; llama-server and parser children belong to its kill-on-close Job Object. Actual Task Scheduler stop is still unverified on this PC. Check for leftovers with the command under "Operate".
- The task runs in the non-interactive session 0. CUDA from that session must be verified on the target.

## Layout (example)

Use your own drive and folder names. Every path must be absolute. Configuration and data must be **outside the checkout** and **not under `AppData` or `LocalCache`** (the application refuses them; see `src/tgbotdocs/application/config.py`).

| Purpose | Example |
| --- | --- |
| Checkout (read-only for the bot account) | `C:\TgBotDocs\app` |
| uv-managed Python | `C:\TgBotDocs\uv-python` |
| uv cache | `C:\TgBotDocs\uv-cache` |
| External configuration | `C:\TgBotDocs\config\tgbotdocs.env` |
| PostgreSQL root (`-DataRoot` of `setup-postgres.ps1`) | `C:\TgBotDocsData` |
| Application `DATA_ROOT` | `C:\TgBotDocsData\prod` |

By default uv installs Python under the installing user's profile. Set `UV_PYTHON_INSTALL_DIR` to a machine location instead, as shown in step 2. Otherwise the virtual environment's base interpreter may be unreadable by the account the task runs as.

## Clean-Machine Procedure

Run the steps in a PowerShell window in the checkout. Step 1 and the `-Apply` steps need an elevated window ("Run as administrator"). Registration, removal and directory-permission scripts are **dry runs** unless `-Apply` is given; `verify-artifacts.ps1` is read-only and `run-bot.ps1` starts the foreground bot. Run it once without `-Apply`, read the planned commands, and then repeat it with `-Apply`.

### 1. NVIDIA driver

Install the current NVIDIA driver for the GPU from [nvidia.com](https://www.nvidia.com/Download/index.aspx). The CUDA Toolkit is not needed: the llama.cpp archive and its `cudart` companion archive contain the CUDA 12.4 runtime DLLs. `nvidia-smi` must report a "CUDA Version" of 12.4 or later. The reference hardware is a GPU with 6 GiB of VRAM and 16 GiB of RAM (S-11-A1).

### 2. uv, Python and dependencies

Install uv from its [official installer](https://docs.astral.sh/uv/getting-started/installation/). The development PC used uv 0.12.19:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.12.19/install.ps1 | iex"
```

Get the delivered commit into the checkout folder, for example with `git clone` followed by `git checkout <commit>`, or by unpacking the delivered source archive. Then:

```powershell
$env:UV_PYTHON_INSTALL_DIR = 'C:\TgBotDocs\uv-python'
$env:UV_CACHE_DIR = 'C:\TgBotDocs\uv-cache'
uv python install 3.14.5
uv sync --locked --no-dev
.venv\Scripts\python.exe -m tgbotdocs --help
```

`--locked` refuses to run if `uv.lock` does not match `pyproject.toml`. `--no-dev` leaves out the test tools. The project is installed from the checkout. Migrations are read from `<checkout>\migrations`, so keep the checkout in place.

### 3. Model runtime and weights

Option A: use the repository tool. It needs about 4 GB of downloads. It resumes with `curl.exe`, verifies each SHA-256 before use, and extracts both llama.cpp archives into `<DATA_ROOT>\runtime-b11221`:

```powershell
.venv\Scripts\python.exe tools\t01\download_artifacts.py --root C:\TgBotDocsData\prod
```

Option B: download manually from the official URLs listed in `tools/t01/download_artifacts.py` (also recorded in `docs/testing/evidence/t01a/artifacts.json`). Check each file with `Get-FileHash -Algorithm SHA256` against the table below. Extract both ZIP archives into `<DATA_ROOT>\runtime-b11221`, and put the two GGUF files in `<DATA_ROOT>\models`.

| File | SHA-256 |
| --- | --- |
| `llama-b11221-bin-win-cuda-12.4-x64.zip` | `95e15aa4f9cdcf27ea8705b6857567215dc20117ce75ff3701c51f23f6a267d1` |
| `cudart-llama-bin-win-cuda-12.4-x64.zip` | `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` |
| `runtime-b11221\llama-server.exe` (extracted) | `32f5394d0bd75ce90bcc15edb7a638e05b659d0f532313c65dc3401d1f521575` |
| `models\Qwen3VL-4B-Instruct-Q4_K_M.gguf` | `66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a` |
| `models\mmproj-Qwen3VL-4B-Instruct-F16.gguf` | `256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331` |

The application never downloads artifacts while it is processing a document. At every start, it verifies the three runtime hashes again.

### 4. Frozen configuration

Copy the delivered `frozen-t01b.json` byte for byte to `<DATA_ROOT>\frozen\frozen-t01b.json`. Do not open it in an editor and save it. The file binds the recognition code, prompts, dependency versions, Python version, runtime artifacts and calibrated policy. `check` refuses to run with `frozen_recognition_identity_mismatch_recalibrate` if the checkout, dependencies or Python differ. Then verify everything read-only:

```powershell
.\deploy\windows\verify-artifacts.ps1 -DataRoot C:\TgBotDocsData\prod
```

It reads the expected runtime hashes from `runtime.py`. It also checks the frozen file's SHA-256 (override with `-FrozenConfigPath` and `-FrozenConfigSha256` for a different delivered file) and that the file names the same build and hashes. It exits with 0 when everything matches, 1 on a missing file or a mismatch, and 2 on invalid arguments.

### 5. PostgreSQL as a Windows service

`scripts/setup-postgres.ps1 -Action Initialize` requires **PowerShell 7** (`pwsh`), installed from [Microsoft](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows). It uses `[Convert]::ToHexString`, which Windows PowerShell 5.1 does not have (confirmed on the development PC). The `deploy/windows` scripts run under both versions. Always pass `-DataRoot`, because the script's default is a developer path.

```powershell
pwsh -File .\scripts\setup-postgres.ps1 -Action Initialize -DataRoot C:\TgBotDocsData
pwsh -File .\scripts\setup-postgres.ps1 -Action Stop -DataRoot C:\TgBotDocsData
.\deploy\windows\postgresql-service.ps1 -Action Register -DataRoot C:\TgBotDocsData
.\deploy\windows\postgresql-service.ps1 -Action Register -DataRoot C:\TgBotDocsData -Apply   # elevated
Start-Service -Name TgBotDocsPostgreSQL
```

`Initialize` downloads and verifies the pinned PostgreSQL archive and creates a cluster, an application role and its database. It writes random credentials to `C:\TgBotDocsData\postgresql-dev-credentials.json`, readable only by the installing account and SYSTEM. The names still contain `dev`; that does not affect how they work. `Initialize` leaves the server running as a hidden process, so stop it before you register the service.

`postgresql-service.ps1 -Apply` refuses to run while the cluster is running outside the service manager. It grants `NT AUTHORITY\NETWORK SERVICE` modify access to the cluster and read access to the binaries. It then runs `pg_ctl register -S auto` with the same safe launch options as `setup-postgres.ps1 Start`: loopback `127.0.0.1` only, port 55432 by default (`-Port`), no statement or parameter logging, and terse errors. From then on, control the database only with `Start-Service` and `Stop-Service`, not with `setup-postgres.ps1 Start` or `Stop`.

### 6. External configuration

Copy `.env.example` to the external configuration path, for example `C:\TgBotDocs\config\tgbotdocs.env`, and fill in every value. Restrict the file's access control list to the bot account and administrators: it contains secrets. The keys (validated in `src/tgbotdocs/application/config.py`):

| Key | Meaning |
| --- | --- |
| `DATA_ROOT` | Required. The absolute installation data folder: `runtime-b11221`, `models`, `frozen`, `logs`, `temporary`, `runtime-temp`, and the instance lock. Must be outside the checkout and not under AppData or LocalCache. |
| `FROZEN_CONFIG` | Required. The absolute path of the frozen configuration, for example `<DATA_ROOT>\frozen\frozen-t01b.json`. |
| `TEMPORARY_ROOT` | Optional; defaults to `<DATA_ROOT>\temporary`. Must be inside `DATA_ROOT` and not equal to it. Documents stay here only while they are processed; it is cleaned at startup. Do not put it in a synchronized, indexed or backed-up folder. |
| `BOT_TOKEN` | Required. The BotFather token (`<digits>:<secret>`). In BotFather, disable adding the bot to groups. |
| `SHARED_PASSWORD` | Required. The sign-in password shared with users: a random string of at least 16 characters. A change takes effect after a restart. |
| `DATABASE_URL` | Required; must start with `postgresql+psycopg://`. Build it as `postgresql+psycopg://<username>:<password>@<host>:<port>/<database>` from the application (non-admin) fields of the generated credentials file. The generated password is hexadecimal, so it needs no URL escaping. Never paste it into logs or chat. |
| `RUNTIME_PORT` | The loopback port for the supervised llama-server; default 18081. It must be free: the bot never reuses an existing listener. |
| `OPERATOR_TELEGRAM_IDS` | Optional. Comma-separated numeric Telegram user IDs that receive content-free alerts; each must have started a chat with the bot. When empty, alerts go only to the log. |
| `INACTIVITY_S` | Seconds to wait for pages or a clarification before a job ends; default 900. |
| `PROCESSING_S` | Cumulative processing budget per document; default 1800. **Must equal the frozen configuration's budget** or startup fails (`processing_budget_differs_from_frozen_configuration`). |
| `QUEUE_TIMEOUT_S` | Maximum wait in the GPU queue before a job's first model call; default 900. |
| `ALBUM_QUIET_S` | Seconds of silence that close an album; default 2. |
| `ADMITTED_JOBS` | Maximum number of non-terminal jobs at once; a new job is refused as Busy beyond it. Default 8. |
| `DOWNLOAD_LIMIT` | Concurrent Telegram file downloads; default 2. |
| `DELIVERY_S` | Result delivery window in seconds; default 60. |
| `DELIVERY_ATTEMPTS` | Delivery attempts for a retryable error; default 3. |
| `RUNTIME_EXECUTABLE`, `RUNTIME_EXECUTABLE_SHA256` | Optional relocation of the calibrated binary. A hash different from the frozen executable is refused and requires new calibration. Leave unset for the standard Windows layout; the Linux platform procedure is deferred (ED-017). |

Timers must be positive numbers, and capacities must be positive integers.

### 7. Access for the bot account

Run the task as a dedicated standard (non-administrator) local account, for example `MACHINE\tgbotdocs`. That account needs:

- read access to the checkout, `C:\TgBotDocs\uv-python`, and the configuration file;
- modify access to the dedicated application `DATA_ROOT`; do not grant the bot access to PostgreSQL administrative credentials or its cluster;
- the "Log on as a batch job" right, which S4U tasks require. If registering or starting the task fails with a logon error, the machine owner must grant this right. That is a system policy change.

After installing the files and creating the external configuration, close the bot and harden the four **dedicated, disjoint** delivery directories. Existing broad inherited/explicit access is replaced; SYSTEM and Administrators retain full control. App/Python become read-only for the bot, config readable only, and application data writable. Updating protected app files later requires elevation. Do not pass a profile/drive root, the shared development checkout, or the PostgreSQL parent directory. The script requires one enabled local user and rejects group/domain principals, overlapping roots and reparse points before changing anything. Use a dedicated standard account; broad Users/Authenticated Users principals are refused.

```powershell
.\deploy\windows\secure-directories.ps1 -AppRoot C:\TgBotDocs\app -PythonRoot C:\TgBotDocs\uv-python -ConfigDirectory C:\TgBotDocs\config -DataRoot C:\TgBotDocsData\prod -BotAccount "$env:COMPUTERNAME\tgbotdocs"
# Read the plan, then repeat with -Apply in an elevated session.
```

Check effective access as the dedicated account before registering the task; scripts do not grant the batch-logon right. Elevated ACL application and a dedicated-account launch are pending target-machine checks.

### 8. Check without Telegram

```powershell
.venv\Scripts\python.exe -m tgbotdocs check --config C:\TgBotDocs\config\tgbotdocs.env
```

The same check is available as `install-bot-task.ps1 -Apply -RunCheck`; `-RunCheck` is refused in a dry run. It cleans the temporary root, applies migrations, checks database health, verifies the frozen identity and the artifact hashes, and starts and stops llama-server on the GPU. It prints `local_startup_verified` and sends nothing to Telegram. It runs as the current user, so run it before you grant the permissions in step 7, or grant them again afterwards. Folders it creates belong to the user who ran it.

### 9. Register the bot task

```powershell
.\deploy\windows\install-bot-task.ps1 -ConfigPath C:\TgBotDocs\config\tgbotdocs.env -UserId "$env:COMPUTERNAME\tgbotdocs"
.\deploy\windows\install-bot-task.ps1 -ConfigPath C:\TgBotDocs\config\tgbotdocs.env -UserId "$env:COMPUTERNAME\tgbotdocs" -Apply   # elevated
Start-ScheduledTask -TaskPath '\TgBotDocs\' -TaskName 'TgBotDocs Bot'
```

The dry run prints the exact `Register-ScheduledTask` definition:

- the action is `<checkout>\.venv\Scripts\python.exe -m tgbotdocs run --config <file> --restart-on-failure`, with the checkout as working directory;
- the trigger is at startup;
- the principal is the given account with S4U logon and the limited run level;
- the settings are restart every 1 minute up to 999 times, no execution time limit, ignore a new instance, start when available, normal priority 5 (the default of 7 is below normal), and run on battery.

`-Apply` refuses to run outside an elevated session. It also refuses if the task already exists, unless you pass `-Replace`.

`run-bot.ps1` checks that the configuration path is absolute, external and exists, and that the virtual environment exists; it exits with 2 if either check fails. It runs `.venv\Scripts\python.exe -m tgbotdocs run --config <file>` from the checkout and exits with Python's exit code.

## Operate

```powershell
# Bot
Start-ScheduledTask -TaskPath '\TgBotDocs\' -TaskName 'TgBotDocs Bot'
Stop-ScheduledTask  -TaskPath '\TgBotDocs\' -TaskName 'TgBotDocs Bot'
Get-ScheduledTask   -TaskPath '\TgBotDocs\' -TaskName 'TgBotDocs Bot' | Get-ScheduledTaskInfo   # LastRunTime, LastTaskResult
# Leftover check after a stop (should print nothing)
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tgbotdocs run*' -or $_.Name -eq 'llama-server.exe' } |
    Select-Object ProcessId, Name
# Database
Get-Service TgBotDocsPostgreSQL
Start-Service TgBotDocsPostgreSQL
Stop-Service TgBotDocsPostgreSQL   # fast shutdown; stop the bot first
```

Logs (technical events only; no document content, tokens or passwords):

- `<DATA_ROOT>\logs\tgbotdocs.log`: the application log, rotated at midnight UTC and kept for 7 days.
- PostgreSQL running as a service is expected to write to the Windows Application event log. This is not verified.
- Task Scheduler history appears in Task Scheduler's own history view if the machine owner has enabled it.

Operator alerts go to `OPERATOR_TELEGRAM_IDS` (startup completed or failed, intake closed or reopened, runtime or database transitions, password surges, failed delivery).

## Upgrade

1. Stop the task, then check that no process is left (see "Operate").
2. Back up the permitted PostgreSQL profile data with [BACKUP_RESTORE](BACKUP_RESTORE.md).
3. Check out the new delivered commit, then run `uv sync --locked --no-dev`, with the same `UV_*` variables as in step 2.
4. If the release changes the llama.cpp build, the model, or the frozen configuration: install the new artifacts and the new frozen file, and update `FROZEN_CONFIG`.
5. Run `verify-artifacts.ps1`, then `python -m tgbotdocs check --config ...`. Migrations are applied automatically.
6. Start the task. The task definition does not change unless the checkout or configuration path moves; if one does, reinstall the task with `-Replace`.

## Uninstall

```powershell
.\deploy\windows\uninstall-bot-task.ps1            # dry run
.\deploy\windows\uninstall-bot-task.ps1 -Apply     # elevated: stops and unregisters the task
.\deploy\windows\postgresql-service.ps1 -Action Unregister -DataRoot C:\TgBotDocsData          # dry run
.\deploy\windows\postgresql-service.ps1 -Action Unregister -DataRoot C:\TgBotDocsData -Apply   # elevated
```

Neither script deletes data. The PostgreSQL cluster holds the user profiles, and the credentials file holds secrets. Deleting them, together with `DATA_ROOT`, the configuration file and the checkout, is a separate, deliberate decision by the machine owner.

## Verification Record

Earlier preparation checks on the development PC (Windows 11 Home, Windows PowerShell 5.1) on 2026-09-28; current remediation checks are recorded separately in the T08 report:

- The original five scripts in `deploy/windows` parsed with `[System.Management.Automation.Language.Parser]::ParseFile` with zero errors.
- `verify-artifacts.ps1 -DataRoot C:\Users\nikit\TgBotDocsData\dev`: all three runtime artifacts and `frozen-t01b.json` matched, and the frozen file names the pinned build and hashes; exit code 0. With a wrong expected frozen hash, the exit code was 1. With a missing data root, it reported four `MISSING` entries and exit code 1. With a relative path, the exit code was 2.
- `install-bot-task.ps1` dry run: printed the definition, and the resolved settings were `RestartCount=999 RestartInterval=PT1M ExecutionTimeLimit=PT0S MultipleInstances=IgnoreNew StartWhenAvailable=True Priority=5 LogonType=S4U RunLevel=Limited`; exit code 0; no task was registered. It rejects a relative path, a configuration inside the checkout, a missing `.venv`, and an unknown account. `-Apply` in a non-elevated session refused and registered nothing.
- `uninstall-bot-task.ps1` dry run: reported that the task is not registered; exit code 0.
- `postgresql-service.ps1 -Action Register` and `-Action Unregister` dry runs against the existing development cluster: printed the `icacls` and `pg_ctl register`/`unregister` commands; exit code 0; no change. The existing cluster was only queried with `pg_ctl status`. `-Apply` without elevation refused.
- `run-bot.ps1`: rejects a relative path, an AppData path and a missing virtual environment with exit code 2. With a file that is not a valid configuration, Python printed `local_application_failed: configuration_invalid_or_missing`, and the wrapper exited with Python's exit code 1.
- `uv sync --locked --no-dev` in a fresh checkout, with the existing python.org CPython 3.14.5 and without Python downloads: succeeded. The installed environment has no mismatches with `frozen-t01b.json`'s identity (empty `environment_mismatches`).

Not verified (not executed, or impossible on this PC):

- Registering the scheduled task, registering the PostgreSQL service, start at boot, and restart after failure. These were deliberately not executed on the developer's machine.
- Task Scheduler action-failure restart and stopping the directly owned Python action; there is no PowerShell child in the new definition.
- CUDA and llama-server in the task's non-interactive session 0 with S4U logon, and GPU access by the dedicated account.
- A PostgreSQL service running as NETWORK SERVICE on this cluster, and where its logs go.
- `uv python install 3.14.5` (uv-managed CPython, as opposed to the python.org build used here), the uv installer, a clean machine, and a second independent run of this procedure (T08 acceptance).
- Running `download_artifacts.py` on a clean machine in this task. The artifacts on this PC come from the T01a run recorded in `docs/testing/evidence/t01a/artifacts.json`.
- The real Telegram smoke test, which is deferred to the joint E2E with the developer.
