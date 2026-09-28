# Linux x86-64/NVIDIA Installation (Docker Compose)

Status: **packaging prepared; Linux delivery is not accepted**. The recipe follows [ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md). Static checks run on Windows do not verify an image build, Docker Engine, Linux supervision, CUDA, or recognition quality. Native Linux x86-64/NVIDIA acceptance remains required by [T08](../../specs/T08-delivery.md) and ED-008.

There are two services. `app` contains the bot and its supervised llama-server child; `db` contains PostgreSQL. See [OPERATIONS](OPERATIONS.md) for lifecycle and recovery and [SECURITY](../security/SECURITY.md) for data handling.

## Runtime and Application Image Gates

The frozen runtime uses llama.cpp b11221. The registry inspection recorded on 2026-09-28 found no official CUDA server image for that build; the nearest published builds were b11206 and b11223. **No Linux runtime image has been selected or accepted.** A source build of b11221 remains a candidate, not a verified substitute.

The runtime executable's configured SHA-256 must match both the actual file and the calibrated frozen artifact hash. A relocated executable with the same hash is allowed; a distinct Linux executable is refused with `runtime_executable_differs_from_frozen_recalibrate`, even if `RUNTIME_EXECUTABLE_SHA256` correctly describes that file. Copying the Windows freeze and supplying a Linux hash cannot authorize startup. Linux calibration and platform acceptance are deferred; ED-017 is a developer proposal, not permission to transfer Windows calibration. Do not change frozen identities to bypass this gate.

Production requires a **verified application registry manifest digest**. None has been built or recorded. This is an explicit **unperformed required T08 item**. An image ID from `docker image inspect --format '{{.Id}}'` identifies the image configuration; it is not a registry manifest digest and cannot replace this item. An authorized release process must record the verified `RepoDigests` entry and source commit before production use. [Docker image inspect](https://docs.docker.com/reference/cli/docker/image/inspect/).

The Dockerfile has no default runtime image. Export reviewed full references before each Compose session:

```sh
export TGBOTDOCS_CHECKOUT=/srv/tgbotdocs/source
# Replace each placeholder with an actually verified registry reference.
export LLAMA_CPP_IMAGE='<reviewed-runtime-repository>@sha256:<64-lowercase-hex-digest>'
export TGBOTDOCS_APP_IMAGE='<reviewed-application-repository>@sha256:<64-lowercase-hex-digest>'
unset ALLOW_UNPINNED_LLAMA_CPP_IMAGE ALLOW_LOCAL_APP_IMAGE
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" config --quiet
```

These placeholders deliberately fail validation. Use the supplied wrapper for every command. It requires complete SHA-256 references in production, resolves paths from its own directory, and uses an explicit public `compose.env` so an unrelated working-directory `.env` is not loaded. Production applies [compose.production.yaml](../../deploy/linux/compose.production.yaml), which removes `build` to prevent fallback source builds. Use Compose 2.24.4 or later with support for the `!reset` merge tag. [Compose merge specification](https://docs.docker.com/reference/compose-file/merge/).

For local builds, Compose forwards `LLAMA_CPP_IMAGE` and `ALLOW_UNPINNED_LLAMA_CPP_IMAGE` as Docker build arguments; shell variables alone do not supply Dockerfile `ARG` values. [Compose build specification](https://docs.docker.com/reference/compose-file/build/).

For a **reviewed local build experiment only**, tags under `local/` require both explicit opt-ins. Runtime and calibration gates still apply:

```sh
export LLAMA_CPP_IMAGE=local/llama.cpp:server-cuda-b11221
export ALLOW_UNPINNED_LLAMA_CPP_IMAGE=1
export TGBOTDOCS_APP_IMAGE=local/tgbotdocs:validation
export ALLOW_LOCAL_APP_IMAGE=1
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" build app
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" config --quiet
```

Keep these exports for each command in that session; the wrapper validates every command. The Dockerfile also refuses an incomplete runtime digest unless the explicit local-tag opt-in is present. No local build has been performed. The wrapper is an operational guard, not an access-control boundary around Docker.

Building the upstream CUDA Dockerfile at b11221 requires reviewing its source and transitive base images. Adopting b11223 changes the runtime and requires T01a lifecycle checks and applicable calibration/benchmark. Neither choice is made by this recipe.

## Pinned Inputs

These public digests come from the registry inspection recorded on 2026-09-28. They are provenance, not application runtime evidence. Runtime candidates are **not selected**.

| Component | Recorded reference or identity |
| --- | --- |
| llama.cpp b11221 | No published CUDA server image found; unresolved |
| b11223 candidate, index | `ghcr.io/ggml-org/llama.cpp:server-cuda-b11223@sha256:5d0812fe45cb5dcb4ac5c588148a601aca63b6b224601f8d1f6f01fdfb07a111` |
| b11206 candidate, index | `ghcr.io/ggml-org/llama.cpp:server-cuda-b11206@sha256:3e7673cce183a55f97a1bc3c80817f3c61452483c13bc088a6766388af4775fe` |
| uv 0.12.19 | `ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424` |
| Python | CPython 3.14.5 from `.python-version`, installed by checksum-verifying pinned uv |
| Dependencies | `uv.lock`, `uv sync --locked --no-dev`; build backend `hatchling==1.30.1` version-pinned only |
| PostgreSQL 18.6, index | `postgres:18.6-trixie@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722` |
| Model/projector | Pinned revision and SHA-256 in [artifacts.json](../testing/evidence/t01a/artifacts.json) |
| Production app image | **Required digest not recorded; build and release unperformed** |

The candidate b11223 image uses CUDA 12.8.1/Ubuntu 24.04 and `/app/llama-server`. The application overrides its inherited entrypoint and port-8080 health check. Any selected image must provide the executable and compatible dependencies. Dockerfile checks are not a completed build.

## Host Requirements and Layout

The target is native Linux x86-64 with an NVIDIA GPU, approximately 6 GiB VRAM and 16 GiB RAM, a driver compatible with the reviewed CUDA base, Docker Engine/BuildKit and Compose, and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Host installation and GPU checks are unperformed. No WSL, daemon, driver, service, or administrator installation was performed on the development PC.

Allow outbound HTTPS to Telegram during authorized operation; no inbound service ports are needed. Model downloads are a separate preparation step. Compose provides outbound connectivity; it does **not** enforce a Telegram-domain allowlist. Enforce and verify a required allowlist through host/network policy. The internal database network has no external route, and llama-server uses container loopback.

Reserve space for models (about 3.4 GB), images, the database and at least 4 GiB free on the temporary filesystem: 2 GiB quota plus 2 GiB free-space reserve.

| Default host path | Container destination | Access |
| --- | --- | --- |
| `/srv/tgbotdocs/config/tgbotdocs.env` | `app:/config/tgbotdocs.env` | Read-only, `root:10001`, `0640` |
| `/srv/tgbotdocs/config/db-password` | `db:/run/secrets/db_password` | Read-only application-role secret, `root:999`, `0640` |
| `/srv/tgbotdocs/config/db-admin-password` | `db:/run/secrets/db_admin_password` | Read-only admin secret, `root:999`, `0640` |
| `/srv/tgbotdocs/data` | `app:/data` | Read-write logs, runtime keys and lock, `10001:10001`, `0700` |
| `/srv/tgbotdocs/temporary` | `app:/data/temporary` | Dedicated read-write job mount, `10001:10001`, `0700` |
| `/srv/tgbotdocs/models` | `app:/data/models` | Read-only artifacts |
| `/srv/tgbotdocs/frozen` | `app:/data/frozen` | Read-only calibrated configuration |
| Compose `db-data` volume | `db:/var/lib/postgresql` | Persistent PostgreSQL 18 cluster |

Export public path overrides if required: `TGBOTDOCS_ENV_FILE`, `TGBOTDOCS_DATA_DIR`, `TGBOTDOCS_TEMP_DIR`, `TGBOTDOCS_MODELS_DIR`, `TGBOTDOCS_FROZEN_DIR`, `TGBOTDOCS_DB_PASSWORD_FILE`, `TGBOTDOCS_DB_ADMIN_PASSWORD_FILE`. Keep all host data/configuration outside the checkout. Bind mounts refuse to create missing host paths.

Commands use absolute paths or the absolute `TGBOTDOCS_CHECKOUT` and work from any directory:

```sh
sudo install -d -m 0755 /srv/tgbotdocs /srv/tgbotdocs/models /srv/tgbotdocs/frozen
sudo install -d -m 0750 -o root -g 10001 /srv/tgbotdocs/config
sudo install -d -m 0700 -o 10001 -g 10001 /srv/tgbotdocs/data /srv/tgbotdocs/temporary
sudo cp "$TGBOTDOCS_CHECKOUT/deploy/linux/tgbotdocs.env.example" /srv/tgbotdocs/config/tgbotdocs.env
sudo chown root:10001 /srv/tgbotdocs/config/tgbotdocs.env
sudo chmod 0640 /srv/tgbotdocs/config/tgbotdocs.env
( umask 077; openssl rand -hex 32 | sudo tee /srv/tgbotdocs/config/db-password >/dev/null )
( umask 077; openssl rand -hex 32 | sudo tee /srv/tgbotdocs/config/db-admin-password >/dev/null )
sudo chown root:999 /srv/tgbotdocs/config/db-password /srv/tgbotdocs/config/db-admin-password
sudo chmod 0640 /srv/tgbotdocs/config/db-password /srv/tgbotdocs/config/db-admin-password
```

Secret-generation commands are for a new installation: do not overwrite existing passwords. Edit configuration privately. Set `BOT_TOKEN`, a random `SHARED_PASSWORD` of at least 16 characters and `DATABASE_URL` using the **application** password and user `tgbotdocs`. Hexadecimal passwords avoid URL-encoding ambiguity. Set the reviewed runtime path/hash and accepted freeze when Linux calibration becomes available. Never copy secrets into source, logs, tickets or chat.

Configuration is a read-only file the app reads, not a Compose `env_file`; values do not become container environment variables. Container paths are `DATA_ROOT=/data`, `TEMPORARY_ROOT=/data/temporary` and `FROZEN_CONFIG=/data/frozen/frozen-t01b.json`. The temporary mount remains inside `DATA_ROOT` even though its host directory is separate.

## Model Preparation

Download pinned artifacts without changing the shell's working directory:

```sh
model_base=https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/1cd86afb9a95c410a6038ab3b40d8b578c892266
sudo curl -fL --retry 3 -o /srv/tgbotdocs/models/Qwen3VL-4B-Instruct-Q4_K_M.gguf "$model_base/Qwen3VL-4B-Instruct-Q4_K_M.gguf"
sudo curl -fL --retry 3 -o /srv/tgbotdocs/models/mmproj-Qwen3VL-4B-Instruct-F16.gguf "$model_base/mmproj-Qwen3VL-4B-Instruct-F16.gguf"
sha256sum -c <<'EOF'
66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a  /srv/tgbotdocs/models/Qwen3VL-4B-Instruct-Q4_K_M.gguf
256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331  /srv/tgbotdocs/models/mmproj-Qwen3VL-4B-Instruct-F16.gguf
EOF
```

Place the **accepted Linux calibration** in the frozen directory with mode `0644` when available. Code, prompts, dependency versions, Python and runtime artifacts must match it. A mismatch stops startup. The Windows freeze is not an accepted Linux calibration.

## Database Initialization

The official image bootstraps `tgbotdocs_admin` with the separate admin secret. On an **empty** volume, [init-app-role.sh](../../deploy/linux/init-app-role.sh) creates `tgbotdocs` with `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION` and transfers ownership of the app database to it. This permits migrations without cluster-administration privileges. Passwords are read from files and psql environment interpolation, not command arguments. The script confines shell options and password environment to a subshell because the entrypoint may source it. [Official entrypoint](https://github.com/docker-library/postgres/blob/master/docker-entrypoint.sh), [psql variables](https://www.postgresql.org/docs/18/app-psql.html).

Initialization scripts and password files take effect only on the first start of an empty volume. Existing volumes are **not** converted from the old bootstrap-app superuser or given new passwords. Back up and plan an explicit role/password migration before upgrading an existing installation. Do not delete the volume to force initialization.

## Local Check and Authorized First Start

These are future operator procedures, **not executed verification**. They remain blocked until runtime calibration and verified image references are available. Production uses `--no-build`; a local validation build is separate.

```sh
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" pull --policy always
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" up -d --no-build db
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" stop app
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" run --rm --no-deps --pull never app check
# Only after check and separately authorized Telegram setup:
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" up -d --no-build
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" ps
```

`check` makes no Telegram request. It cleans owned leftovers, validates configuration, applies migrations, verifies artifacts and starts/stops llama-server on the GPU. It prints `local_startup_verified` or `local_application_failed: <code>`. It uses the same instance lock as `run`; stop the app first to avoid `application_already_running`.

`run` repeats startup checks then starts long polling. With operators configured, successful startup sends `startup_completed`. Runtime identity failure occurs before the Telegram alert target is attached: it is a technical startup failure, not a promised Telegram mismatch alert. Disable adding the bot to groups in BotFather before authorized operation.

## Logs, Stop and Recovery

Technical event codes are in `/srv/tgbotdocs/data/logs/tgbotdocs.log`, with UTC daily rotation and seven retained files. Container output and PostgreSQL logs are bounded; statement and parameter logging are disabled. llama-server output is discarded. Follow [operator/privacy rules](OPERATIONS.md).

```sh
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" logs app
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" stop
```

The 60-second stop grace period lets the bot stop polling, cancel jobs, close readers, clean jobs and stop its runtime. Docker kills it after the deadline; the next startup cleans owned leftovers. Linux lifecycle behavior still requires actual testing.

`restart: unless-stopped` retries startup failures. Persistent failures can repeat `startup_failed` operator notifications once the service error handler can send them. Stop the app while correcting configuration/calibration/image problems:

```sh
sh "$TGBOTDOCS_CHECKOUT/deploy/linux/compose.sh" stop app
```

`down` preserves the database volume; **never use `down -v`** for routine shutdown. Jobs and sign-ins do not resume.

For upgrades, select a reviewed application **manifest digest**, review migrations/calibration compatibility, stop the app, pull, check then start with `--no-build`. A changed runtime needs calibrated artifacts. PostgreSQL patch upgrades require a reviewed digest; major upgrades need planned dump/restore or `pg_upgrade`.

## Backup and Restore

Use [BACKUP_RESTORE](BACKUP_RESTORE.md) for the explicit three-table allowlist, private host/container archive handling and fresh-target restore/verification. Do not dump arbitrary tables or run an in-place `pg_restore --clean` against the live database. Restoring does not revive jobs or authorization. Native Linux backup/restore is unperformed; protect configuration/admin credentials separately from permitted profile backups.

## Packaging Boundaries and Verification

- `init: true` reaps children and forwards signals. The bot must not be PID 1; supervised workers use parent-death handling.
- Temporary jobs have a **dedicated disk bind mount** inside `/data`. Disk is provisional; tmpfs needs measured RAM/swap and enough quota/reserve space. No native Linux full-quota measurement exists.
- Models, frozen calibration and app configuration are read-only. App data/jobs are separate writable mounts. The app uses UID/GID 10001, drops all capabilities and sets `no-new-privileges`.
- `db` joins only the internal network; `app` also joins the outbound network. No published host ports or Docker socket.
- Migrations run on `check`/`run`; the editable installation stays beside migrations.
- Sources: [Dockerfile](../../deploy/linux/Dockerfile), [Compose](../../deploy/linux/compose.yaml), [wrapper](../../deploy/linux/compose.sh), [public Compose env](../../deploy/linux/compose.env), [app example](../../deploy/linux/tgbotdocs.env.example), [context allowlist](../../.dockerignore).

| Check | Status |
| --- | --- |
| Docker CLI/Compose parsing on Windows without engine | Static validation only; exact commands/results in current T08 report |
| Shell syntax and reference guards on Git Bash | Static portability checks, not native Linux execution |
| hadolint | Static lint only; exact results in current T08 report |
| Runtime image choice and application manifest digest | **Unperformed required release items** |
| Build, in-image interpreter/dependencies, first-volume app role/migrations | **Unperformed** |
| Native Linux GPU, no-Telegram check, supervision/kill/cleanup, alerts/logs | **Unperformed** |
| Stop/restart/upgrade, backup/restore, quota/RAM/tmpfs | **Unperformed** |
| Linux calibration and recognition acceptance | **Deferred; ED-017 has no approval** |

Tool provenance belongs in the engineering T08 report, not customer-specific filesystem paths. Static checks do not close unperformed platform/image requirements.
