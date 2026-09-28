# Linux x86-64/NVIDIA Installation (Docker Compose)

Status: prepared on 2026-09-28 for T08; **nothing here has been built or run.** The Compose file and Dockerfile were written on the Windows development PC, which has no Docker daemon and no WSL. There, `docker compose config` accepted the Compose file and hadolint reported no findings in the Dockerfile. No image was built, no container ran, and no Linux or GPU behaviour has been checked. **The build cannot succeed yet:** no official llama.cpp image exists for the pinned build b11221 (see [Runtime image](#runtime-image-unresolved)). Linux remains an unchecked platform ([T08](../../specs/T08-delivery.md), ED-008). The first real run must take place on a native Linux x86-64 host with an NVIDIA GPU.

Packaging follows [ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md). It uses two services. `app` is built on the llama.cpp CUDA server image and adds a pinned Python runtime and the application. The bot starts and supervises `llama-server` inside the container. `db` runs the official PostgreSQL image with a named volume. The operating model is described in [OPERATIONS](OPERATIONS.md), and data handling rules are in [SECURITY](../security/SECURITY.md).

## Files

| File | Purpose |
| --- | --- |
| [`deploy/linux/Dockerfile`](../../deploy/linux/Dockerfile) | `app` image: llama.cpp base pinned by digest, uv 0.12.19 by digest, Python from `.python-version` (3.14.5), `uv sync --locked --no-dev`, non-root UID/GID 10001 |
| [`deploy/linux/compose.yaml`](../../deploy/linux/compose.yaml) | `app` and `db` services, GPU reservation, mounts, networks, database secret |
| [`deploy/linux/tgbotdocs.env.example`](../../deploy/linux/tgbotdocs.env.example) | Application configuration with container paths and no secrets |
| [`.dockerignore`](../../.dockerignore) | Build-context allowlist: `pyproject.toml`, `uv.lock`, `.python-version`, `alembic.ini`, `src/`, `migrations/` |

## Pinned Components

The digests below were resolved on 2026-09-28 through the public registry HTTP APIs, using anonymous pull tokens. "Index" is the multi-platform manifest list. `docker compose` resolves it to the `linux/amd64` entry.

| Component | Reference | Digest |
| --- | --- | --- |
| llama.cpp CUDA server b11221 | **none published** | — (placeholder; the build fails) |
| llama.cpp `server-cuda-b11223` (nearest newer) | `ghcr.io/ggml-org/llama.cpp:server-cuda-b11223` | index `sha256:5d0812fe45cb5dcb4ac5c588148a601aca63b6b224601f8d1f6f01fdfb07a111`; amd64 `sha256:25ff2a10503093f0aa801a6776c268d996dc1ee882e533eb660d83390dec5aab` |
| llama.cpp `server-cuda-b11206` (nearest older) | `ghcr.io/ggml-org/llama.cpp:server-cuda-b11206` | index `sha256:3e7673cce183a55f97a1bc3c80817f3c61452483c13bc088a6766388af4775fe`; amd64 `sha256:e2f285f5b208ea5940a28f1573ae4791a8735dd1c41aa0e4f4836aab211bb734` |
| uv 0.12.19 | `ghcr.io/astral-sh/uv:0.12.19` | index `sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424` |
| Python | CPython 3.14.5 installed by uv (`.python-version`) | uv verifies its managed downloads against checksums embedded in the pinned uv release |
| Python dependencies | `uv.lock` (`uv sync --locked --no-dev`) | Hashes in the lockfile; the build backend `hatchling==1.30.1` is pinned by version only |
| PostgreSQL 18.6 | `postgres:18.6-trixie` (same index as `postgres:18.6`) | index `sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722`; amd64 `sha256:0377e72c5289ed2f98cf61b1a9c2db9eb9d300317fe14244492fbc94343b3d04` |
| Model and projector | Hugging Face `Qwen/Qwen3-VL-4B-Instruct-GGUF` at revision `1cd86afb9a95c410a6038ab3b40d8b578c892266` | SHA-256 as in [artifacts.json](../testing/evidence/t01a/artifacts.json) and `recognition/runtime.py` |

The llama.cpp images use the tag scheme `server-cuda-b<build>`, with `server-cuda12-b<build>` and `server-cuda13-b<build>` variants. In `server-cuda-b11223`, the image labels show `org.opencontainers.image.version=b11223` and revision `4da6337767f973e2b4d0797e5b323d77d8565e4a`. The image uses CUDA 12.8.1 on Ubuntu 24.04, places `/app/llama-server` as its entrypoint, requires `NVIDIA_REQUIRE_CUDA=cuda>=12.8`, sets `LLAMA_ARG_HOST=0.0.0.0`, and has a health check on port 8080. The application image overrides the health check and the entrypoint. The runtime also removes `LLAMA_*` variables from the child's environment and passes `--host 127.0.0.1`.

## Runtime Image (Unresolved)

The frozen recognition configuration pins llama.cpp **b11221**. Upstream publishes Docker images from a daily scheduled workflow (`.github/workflows/docker.yml`: `schedule` plus manual dispatch), not for every release. Among the 12,042 tags of `ghcr.io/ggml-org/llama.cpp`, none contains `11221`: the CUDA server images jump from b11206 to b11223. The Dockerfile's default `LLAMA_CPP_IMAGE` is therefore an uppercase placeholder, and Docker rejects it as an invalid reference before pulling anything. A base referenced without `@sha256:` is also refused unless `ALLOW_UNPINNED_LLAMA_CPP_IMAGE=1`.

Choosing a base is **the developer's decision**. The options are:

1. **Adopt a published image, such as `server-cuda-b11223` pinned by digest.** This counts as a llama.cpp update. ADR-0005 requires repeating the T01a runtime checks (streaming cancellation, slot release, restart, memory envelope) and, if recognition output changes, the benchmark. Note that the executable override does not check the build number. The frozen identity would still state `b11221` while the container runs b11223, so this step must not be taken silently.
2. **Build the official CUDA Dockerfile at tag b11221 on the Linux host**, then use the local image:

   ```sh
   git clone --depth 1 --branch b11221 https://github.com/ggml-org/llama.cpp.git /srv/build/llama.cpp
   docker build -f /srv/build/llama.cpp/.devops/cuda.Dockerfile --target server \
     -t local/llama.cpp:server-cuda-b11221 /srv/build/llama.cpp
   docker compose -f deploy/linux/compose.yaml build \
     --build-arg LLAMA_CPP_IMAGE=local/llama.cpp:server-cuda-b11221 \
     --build-arg ALLOW_UNPINNED_LLAMA_CPP_IMAGE=1 app
   ```

   This keeps the pinned source release. However, the upstream Dockerfile pulls `node:24` and `nvidia/cuda:12.8.1-*-ubuntu24.04` by tag, and the result is not bit-for-bit reproducible. The executable SHA-256 you pin in the configuration is the only integrity check of such a build (not verified).

After the decision, commit the chosen reference as the Dockerfile's `LLAMA_CPP_IMAGE` default, for example `ghcr.io/ggml-org/llama.cpp:server-cuda-b11223@sha256:5d08…a111`. Then record it in STATUS, and in the decision register if it changes the pinned build.

## Host Requirements

- Linux x86-64 with an NVIDIA GPU. The reference class is 6 GiB VRAM and 16 GiB RAM (T08).
- An NVIDIA driver that supports CUDA 12.8 (`nvidia-smi` shows the supported CUDA version). The image's `NVIDIA_REQUIRE_CUDA` accepts older driver branches only on data-centre products.
- Docker Engine with BuildKit and the Compose v2 plugin, plus the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) configured for Docker. These are administrator actions on the Linux host.
- Outbound HTTPS to the Telegram Bot API. Inbound ports are not needed.
- Disk: 3.4 GB for the model files, room for the images (the CUDA runtime base alone takes several GB) and the database volume, plus at least 4 GiB free for the temporary area (2 GiB quota plus a 2 GiB free-space reserve, see OPERATIONS).

The commands below use `LLAMA_CPP_IMAGE` for the chosen base reference, for example `export LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda-b11223@sha256:<index digest>`. Check GPU access from a container with that image: `docker run --rm --gpus all --entrypoint nvidia-smi "$LLAMA_CPP_IMAGE"`.

## Host Layout

Compose defaults to the paths below. You can change them with `TGBOTDOCS_ENV_FILE`, `TGBOTDOCS_DATA_DIR`, `TGBOTDOCS_MODELS_DIR`, `TGBOTDOCS_FROZEN_DIR`, and `TGBOTDOCS_DB_PASSWORD_FILE`, set in the shell or passed with `docker compose --env-file <file outside the checkout>`. Keep all of them outside the checkout.

| Host path | Container | Mode | Contents |
| --- | --- | --- | --- |
| `/srv/tgbotdocs/config/tgbotdocs.env` | `app:/config/tgbotdocs.env` | read-only | Application configuration with secrets; `root:10001`, `0640` |
| `/srv/tgbotdocs/config/db-password` | `db:/run/secrets/db_password` | Compose secret | Database password; `root:999` (the image's postgres group), `0640` |
| `/srv/tgbotdocs/data` | `app:/data` | read-write | `DATA_ROOT`: `logs/`, `temporary/`, `runtime-temp/`, and the instance lock; `10001:10001`, `0700` |
| `/srv/tgbotdocs/models` | `app:/data/models` | read-only | `Qwen3VL-4B-Instruct-Q4_K_M.gguf`, `mmproj-Qwen3VL-4B-Instruct-F16.gguf` |
| `/srv/tgbotdocs/frozen` | `app:/data/frozen` | read-only | `frozen-t01b.json` |
| volume `tgbotdocs_db-data` | `db:/var/lib/postgresql` | named volume | PostgreSQL cluster (`PGDATA=/var/lib/postgresql/18/docker`) |

`/data` is a bind mount rather than a named volume. That way the operator can place the models and the frozen configuration, and read the technical log, directly on the host. The models and the frozen configuration are pinned inputs whose hashes the application verifies. Mounting them read-only keeps the application from changing them, and a compromised process cannot replace them. The database uses a named volume, as ADR-0005 specifies.

```sh
sudo install -d -m 0755 /srv/tgbotdocs /srv/tgbotdocs/models /srv/tgbotdocs/frozen
sudo install -d -m 0750 -o root -g 10001 /srv/tgbotdocs/config
sudo install -d -m 0700 -o 10001 -g 10001 /srv/tgbotdocs/data
```

## Model Files and Frozen Configuration

Download the files over HTTPS from the pinned revision, then verify them before first use:

```sh
cd /srv/tgbotdocs/models
base=https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/1cd86afb9a95c410a6038ab3b40d8b578c892266
sudo curl -fL --retry 3 -o Qwen3VL-4B-Instruct-Q4_K_M.gguf "$base/Qwen3VL-4B-Instruct-Q4_K_M.gguf"
sudo curl -fL --retry 3 -o mmproj-Qwen3VL-4B-Instruct-F16.gguf "$base/mmproj-Qwen3VL-4B-Instruct-F16.gguf"
sha256sum -c <<'EOF'
66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a  Qwen3VL-4B-Instruct-Q4_K_M.gguf
256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331  mmproj-Qwen3VL-4B-Instruct-F16.gguf
EOF
```

Copy `frozen-t01b.json` from the calibrated data root into `/srv/tgbotdocs/frozen/` with mode `0644`. The frozen configuration binds the recognition code hash, prompt identity, dependency versions, and the Python version. Build the image from the same commit that the frozen configuration matches. Otherwise startup stops with `frozen_recognition_identity_mismatch_recalibrate`.

## Configuration

```sh
sudo cp deploy/linux/tgbotdocs.env.example /srv/tgbotdocs/config/tgbotdocs.env
sudo chown root:10001 /srv/tgbotdocs/config/tgbotdocs.env && sudo chmod 0640 /srv/tgbotdocs/config/tgbotdocs.env
( umask 077; openssl rand -hex 32 | sudo tee /srv/tgbotdocs/config/db-password >/dev/null )
sudo chown root:999 /srv/tgbotdocs/config/db-password && sudo chmod 0640 /srv/tgbotdocs/config/db-password
```

Edit `tgbotdocs.env`:

- Set `BOT_TOKEN` and `SHARED_PASSWORD` (random, at least 16 characters).
- In `DATABASE_URL`, replace the password with the content of `db-password`. Never paste either into a ticket, log, or chat.
- Set `RUNTIME_EXECUTABLE_SHA256` as described in the next section.

The container paths `DATA_ROOT=/data`, `TEMPORARY_ROOT=/data/temporary`, and `FROZEN_CONFIG=/data/frozen/frozen-t01b.json` meet the configuration rules: absolute, outside the application tree (`/opt/tgbotdocs`), not under AppData, and the temporary root inside the data root. The configuration file is read by the application itself. It is not a Compose `env_file`, so its values do not become container environment variables.

The database password file initializes the cluster only on the **first** start, when the volume is empty. After that, changing the file does not change the database role's password.

## Pin the Runtime Executable

The frozen configuration pins the Windows `llama-server.exe`. The Linux image contains a different executable, even for the same release. The application accepts it only when both `RUNTIME_EXECUTABLE` and a 64-character lowercase `RUNTIME_EXECUTABLE_SHA256` are set. Compute the hash on the Linux host from the pinned base image and from the built application image. The two values must be identical:

```sh
docker run --rm --entrypoint sha256sum "$LLAMA_CPP_IMAGE" /app/llama-server
docker compose -f deploy/linux/compose.yaml build app
docker run --rm --entrypoint sha256sum tgbotdocs-app:local /app/llama-server
```

Put the hash into `RUNTIME_EXECUTABLE_SHA256`. Every change of the base image requires a new hash. The hash covers only the executable. The shared libraries next to it in `/app` (`libggml*.so`, `libllama.so`, the CUDA backend) are pinned only through the image digest.

**ED-017 caveat (proposal awaiting the developer).** At every start with this override, the application alerts `runtime_executable_differs_from_frozen`. Recognition quality on Linux has not been verified until the developer decides whether the Windows calibration and benchmark results transfer, or whether Linux needs its own verification, including a benchmark run if required. Until then, Linux results must not be reported as calibrated quality.

## Build, Check, First Start

Run from the repository root of the checkout that matches the frozen configuration:

```sh
docker compose -f deploy/linux/compose.yaml build app
docker compose -f deploy/linux/compose.yaml up -d db
docker compose -f deploy/linux/compose.yaml run --rm app check
docker compose -f deploy/linux/compose.yaml up -d
docker compose -f deploy/linux/compose.yaml ps
```

`check` makes no Telegram request. It cleans owned temporary leftovers, validates the configuration, applies the Alembic migrations, verifies the model, projector, and executable hashes, and starts and stops `llama-server` on the GPU. It prints `local_startup_verified` on success, or a content-free `local_application_failed: <code>` otherwise. `check` and the service take the same instance lock (`/data/.tgbotdocs-instance.lock`). Run `check` only while the `app` service is stopped (`docker compose ... stop app`), or it reports `application_already_running`.

`run`, the image's default command, performs the same startup sequence, including the migrations, and then starts long polling. `db` must be healthy first: its health check uses TCP `pg_isready`, so the temporary socket-only server of the first initialization does not count. With operators configured, the first start sends `startup_completed`, followed by `runtime_executable_differs_from_frozen` (ED-017). In BotFather, disable adding the bot to groups (T08).

## Logs

- Application technical log: `/srv/tgbotdocs/data/logs/tgbotdocs.log`. It is rotated at UTC midnight and 7 files are kept. It contains event codes only (OPERATIONS, Logs).
- Container output: `docker compose -f deploy/linux/compose.yaml logs app` shows only `tgbotdocs_starting`, `tgbotdocs_stopped`, or a failure code. `logs db` shows the PostgreSQL server log, with statement and parameter logging disabled as on Windows. Docker keeps up to 3 files of 10 MB per service.
- `llama-server` output is discarded by the application. Operator alerts go to `OPERATOR_TELEGRAM_IDS`.

## Stop, Restart, Upgrade

- Stop: `docker compose -f deploy/linux/compose.yaml stop`. The bot receives SIGTERM through the container init, stops polling, cancels jobs, removes their temporary data, and stops `llama-server`. The grace period is 60 s. After that, Docker kills the process, and the next start cleans leftovers before polling.
- Restart after a failure is automatic (`restart: unless-stopped`). A restart does not resume document jobs or sign-ins (STATE_MACHINE).
- `docker compose ... down` removes containers and networks but keeps the database volume. **Never use `down -v`**: it deletes the database volume.
- Application upgrade: check out the new commit. If the recognition code, prompts, dependencies, or runtime changed, a new frozen configuration is required. Then run `docker compose ... build app`, run `check` with the service stopped, and run `up -d`. Recompute `RUNTIME_EXECUTABLE_SHA256` whenever the base image changes.
- PostgreSQL: for a patch update within 18.x, replace the pinned digest, then run `docker compose ... pull db` and `up -d db`. A major-version upgrade needs dump/restore or `pg_upgrade` and is not covered here.

## Backup and Restore

Back up only the database, which holds users and current profiles (DATA_MODEL). The temporary directory, logs, and models are never part of a backup. The models are re-downloadable pinned artifacts. The configuration file and the database password file are secrets. Keep their backup separately under the environment owner's protection. A dump may contain sensitive profile text, so store it restricted.

```sh
sudo install -d -m 0700 -o "$(id -u)" /srv/tgbotdocs-backup
( umask 077; docker compose -f deploy/linux/compose.yaml exec -T db \
    pg_dump -U tgbotdocs -d tgbotdocs --format=custom \
    > /srv/tgbotdocs-backup/tgbotdocs-$(date -u +%Y%m%dT%H%M%SZ).dump )
```

Restore into the same database while the bot is stopped:

```sh
docker compose -f deploy/linux/compose.yaml stop app
docker compose -f deploy/linux/compose.yaml exec -T db \
    pg_restore -U tgbotdocs -d tgbotdocs --clean --if-exists --no-owner \
    < /srv/tgbotdocs-backup/tgbotdocs-<timestamp>.dump
docker compose -f deploy/linux/compose.yaml start app
```

`exec` connects through the container's local socket, which the official image trusts inside the container. Restoring the database does not revive document jobs or sign-ins. Neither backup nor restore has been run on Linux.

## Design Notes

- **Container init.** `init: true` runs Docker's init as PID 1. It reaps processes, forwards signals, and keeps the bot from being PID 1. This matters because file-preparation workers and `llama-server` get a parent-death signal, and they exit at once if their parent is PID 1 (`application/supervision.py`). Use `--init` with a manual `docker run`.
- **Temporary directory on disk (initial choice).** `TEMPORARY_ROOT=/data/temporary` lies on the host disk inside the data bind mount. The configuration requires it inside `DATA_ROOT`. ADR-0005 leaves the choice between disk and a tmpfs to T08, after RAM measurements. A tmpfs would keep document files off the SSD and disappear when the container stops. However, it counts against RAM and swap. Admission also requires the 2 GiB quota plus a 2 GiB free-space reserve on that filesystem, so a tmpfs would need about 4 GiB of RAM. On the 16 GiB reference class, that memory competes with `llama-server`, the bot, and PostgreSQL, and no measurement under a full quota exists yet. Disk behaves as measured on Windows and is the initial choice. The tmpfs alternative is an extra `type: tmpfs` mount at `/data/temporary` with `tmpfs.size` of at least 4 GiB and a mode that lets UID 10001 write (not verified). Swap must then be disabled or encrypted for the RAM-only property to hold.
- **Networks.** `db` sits only on an internal network. `app` joins that network and one with outbound access for Telegram. No service publishes a port. PostgreSQL is reachable only from `app`, and `llama-server` listens on the app container's loopback with a per-start API key.
- **GPU.** `app` reserves one NVIDIA GPU (`driver: nvidia`, `count: 1`, `capabilities: [gpu]`). `db` has no GPU.
- **Hardening.** `app` runs as UID/GID 10001, drops all capabilities, and sets `no-new-privileges`. The database role is the cluster's bootstrap role. A separate non-superuser application role, as on the Windows development cluster, has not been added yet.
- **Migrations** run automatically on every `check` and `run` (`ProfileStore.migrate`). For that reason the project is installed editable next to `migrations/` in `/opt/tgbotdocs`.

## Verification Status

| Check | Result |
| --- | --- |
| `docker compose -f deploy/linux/compose.yaml config` (Docker CLI 29.8.1, Compose v5.5.1, on Windows without a daemon), with default and overridden host paths | verified: the model resolves as intended |
| hadolint 2.15.1 on `deploy/linux/Dockerfile` | verified: no findings after the user was made numeric (DL3066) |
| Registry tags and digests listed above | verified through the registry APIs on 2026-09-28 |
| Image build, including the placeholder failure and the digest guard | not verified: no daemon on this PC |
| Container start, GPU access, `check`, `run`, migrations, alerts, logs, stop behaviour, backup/restore | not verified: needs a native Linux host with an NVIDIA GPU |
| Recognition quality on Linux | not verified: ED-017 |

The validation tools were installed only under `C:\Users\nikit\TgBotDocsData\tools` for the user, without administrator rights or a daemon:

- Compose v5.5.1 (`docker-compose-windows-x86_64.exe`) and hadolint 2.15.1 (`hadolint-windows-x86_64.exe`) matched the SHA-256 values published with their GitHub releases: `a3c0c730…d2f` and `01d92729…b0a`.
- `download.docker.com` publishes no checksum for `docker-29.8.1.zip`. Its local SHA-256 is `f99b6e0ac1950e6c47c267b1d7ac53ef973682208523212d03477478c6562aaf`, and the executables are not Authenticode-signed.
