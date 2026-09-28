# TgBotDocs application image for Linux x86-64 with an NVIDIA GPU (ADR-0005).
#
# Built by deploy/linux/compose.yaml with the repository root as the context.
# The bot is the main process; it starts and supervises llama-server from the
# base image as its child. Nothing in this file has been built or run yet; see
# docs/operations/INSTALL_LINUX.md for the verification status.

# llama.cpp CUDA server image of the pinned build b11221, by digest.
#
# UNRESOLVED: upstream publishes images only from a daily scheduled workflow, and
# ghcr.io/ggml-org/llama.cpp has no image for b11221 (checked 2026-09-28; the
# nearest are server-cuda-b11206 and server-cuda-b11223). There is no default:
# Compose forwards the required LLAMA_CPP_IMAGE selected for review. A distinct
# Linux executable requires its own calibration; Windows evidence does not
# authorize it. See INSTALL_LINUX.md for the unresolved platform gate.
ARG LLAMA_CPP_IMAGE
# Set to 1 only for a locally built image that has no registry digest.
ARG ALLOW_UNPINNED_LLAMA_CPP_IMAGE=

# uv 0.12.19, the version that manages the lockfile on the development PC.
FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM ${LLAMA_CPP_IMAGE}

ARG LLAMA_CPP_IMAGE
ARG ALLOW_UNPINNED_LLAMA_CPP_IMAGE
# The reviewed CUDA candidates use Ubuntu and provide bash. A custom base must
# provide it too; pipefail keeps build validation failures visible.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# Refuse a base referenced only by a movable tag, and one without the server.
RUN set -eu; \
    if ! printf '%s\n' "${LLAMA_CPP_IMAGE}" | grep -Eq '^[a-z0-9][a-zA-Z0-9./:_-]*@sha256:[0-9a-f]{64}$'; then \
      if [ "${ALLOW_UNPINNED_LLAMA_CPP_IMAGE}" != 1 ] || \
         ! printf '%s\n' "${LLAMA_CPP_IMAGE}" | grep -Eq '^local/[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9][A-Za-z0-9_.-]*$'; then \
        echo "LLAMA_CPP_IMAGE requires a full sha256 digest (local builds need explicit opt-in)" >&2; exit 1; \
      fi; \
    fi; \
    test -x /app/llama-server

# A fixed non-root identity; the host data directory is owned by this UID/GID.
RUN groupadd --system --gid 10001 tgbotdocs \
    && useradd --system --uid 10001 --gid tgbotdocs --home-dir /nonexistent \
       --no-create-home --shell /usr/sbin/nologin tgbotdocs \
    && mkdir -p /data /config

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/tgbotdocs/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /opt/tgbotdocs
COPY --from=uv /uv /usr/local/bin/uv

# The interpreter (exact version from .python-version; the frozen recognition
# configuration binds it) and the locked runtime dependencies, without the project.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv python install "$(cat .python-version)" \
    && uv sync --locked --no-dev --no-install-project

# The project stays an editable install: ProfileStore finds the Alembic
# migrations relative to the source tree (/opt/tgbotdocs/migrations).
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev \
    && .venv/bin/python -m compileall -q src migrations \
    && .venv/bin/python -c "import platform, sys; expected = open('.python-version').read().strip(); sys.exit(platform.python_version() != expected)"

ENV PATH=/opt/tgbotdocs/.venv/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLAMA_ARG_HOST=127.0.0.1

# Numeric, so host ownership (chown 10001:10001) matches without name lookup.
USER 10001:10001

# The base image probes llama-server on port 8080; here the bot owns the runtime
# on a loopback port and v1 has no health endpoint (OPERATIONS, Operator Alerts).
HEALTHCHECK NONE

# Configuration comes from TGBOTDOCS_CONFIG (set by compose.yaml). The bot must
# not be PID 1: compose.yaml sets `init: true` (children exit if their parent is
# PID 1, see application/supervision.py).
ENTRYPOINT ["/opt/tgbotdocs/.venv/bin/python", "-m", "tgbotdocs"]
CMD ["run"]
