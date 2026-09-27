# ADR-0005. Runtime Supervision, Packaging, and Toolchain

Date: 2026-09-27. Status: accepted engineering decision under [S-10-A4](../requirements/SOURCES.md); the developer can override it. Basis: REQ-017, REQ-023–REQ-026, REQ-032; [ADR-0002](ADR-0002-application-stack.md); [OPERATIONS](../operations/OPERATIONS.md).

## Context

The operating model requires confirming that llama-server has released its slot after a timeout or cancellation and restarting it otherwise; file preparation must be killable; crash leftovers must not keep files open. The planning package did not say who starts, supervises, and restarts these processes on Windows and Linux, how a model call is cancelled, or how the product is packaged for both platforms.

Verified on 2026-09-27:

- Cancellation on client disconnect in llama-server has changed between versions. Issue [#24496](https://github.com/ggml-org/llama.cpp/issues/24496) (June 2026) reported that generation continued for streaming and non-streaming requests; issue [#29498](https://github.com/ggml-org/llama.cpp/issues/29498) (September 2026) reports that current builds cancel a disconnected streaming request within about 0.07 s unless a resumable-stream header is sent. The slots endpoint reports `is_processing` per slot.
- On Windows, psycopg's asynchronous mode is incompatible with the default `ProactorEventLoop` ([psycopg](https://www.psycopg.org/psycopg3/docs/advanced/async.html)), and `SelectorEventLoop` does not support asyncio subprocesses ([Python](https://docs.python.org/3.12/library/asyncio-platforms.html)).
- Official llama.cpp Docker images with CUDA exist (`server-cuda`, `server-cuda13`) and need the NVIDIA Container Toolkit on Linux ([docker.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)).
- Python 3.12 is in its security-only phase ([devguide](https://devguide.python.org/versions/)).

## Decision

1. **The bot process supervises its children on every platform.** It starts one llama-server and short-lived file-preparation workers. Children end with the bot: a Job Object with kill-on-close on Windows; a parent-death signal and a container init on Linux. The bot records child process IDs in the temporary root so that startup can terminate leftovers of a hard crash.
2. **Model calls are streamed.** Cancellation closes the stream. Before the next call, the scheduler confirms that the slot reports idle within the release window; otherwise the supervisor restarts llama-server and keeps the runtime unavailable until its health check passes. The client never sends headers that disable disconnect-cancellation. T01a verifies this behavior on the pinned build; every llama.cpp update repeats the check.
3. **Database access is synchronous in a small thread pool.** SQLAlchemy 2 with psycopg 3 in synchronous mode is called from the asyncio application through a dedicated thread pool; Alembic uses the same driver. The event loop stays the platform default (`ProactorEventLoop` on Windows), so asyncio subprocesses remain available. The database holds only profiles, so the thread overhead is negligible.
4. **Packaging.**
   - Linux x86-64/NVIDIA: Docker Compose with two services. `app` is an image built on the official llama.cpp CUDA server image, pinned by digest, with a pinned Python runtime and the application; the bot supervises llama-server inside the container. `db` is the official PostgreSQL image with a named volume. Model files are mounted read-only. The temporary directory is a dedicated mount; T08 chooses disk or a tmpfs sized to the quota after RAM measurements. The host needs the NVIDIA driver and the NVIDIA Container Toolkit.
   - Windows x64/NVIDIA: native installation. uv installs the Python runtime and dependencies from the lockfile; llama.cpp comes from the official Windows CUDA release archive of the pinned build, verified by SHA-256; PostgreSQL comes from its official Windows distribution and runs as a service. The bot runs as a service or scheduled task that starts at boot and restarts on failure; T08 selects the wrapper.
   - Both platforms use the same configuration schema; the configuration file lives outside the source tree.
5. **Toolchain.** uv manages the Python interpreter, the lockfile (`uv.lock`), and reproducible installs on both platforms. The Python line is the newest stable one whose dependencies all ship Windows and Linux wheels when T01b starts: 3.14 is the target and 3.13 the fallback; 3.12 is not used because only security fixes remain for it.
6. **Model artifacts** are pinned by file name and SHA-256 and downloaded from the official repository in a separate preparation step, never while a document is processed.

## Consequences

- Windows-specific supervision code (Job Object) and a Linux container image are part of the product; T08 verifies both platforms separately.
- The llama.cpp build is a pinned dependency: an update repeats the T01a runtime checks and, if recognition output changes, the benchmark.
- Final Linux verification needs a native Linux host with an NVIDIA GPU; WSL2 on the development PC is acceptable only for early smoke tests of the container path (ED-008).
- psycopg is LGPL-3.0; the T08 license list includes it, together with PDFium notices, CUDA redistribution terms if CUDA libraries are shipped, and the licenses of the base images.

## Options Not Selected

- A separate llama-server container: the bot could not restart a stuck runtime without access to the Docker socket, which is equivalent to root on the host.
- Docker on Windows through Docker Desktop and WSL2: adds a GPU virtualization layer and subscription conditions for larger organizations, while the development PC already runs natively.
- Native installation on Linux: distribution differences and a CUDA build of llama.cpp make reproducibility weaker than a pinned image.
- psycopg's asynchronous mode with `SelectorEventLoop`: incompatible with asyncio subprocesses on Windows.
- asyncpg: would avoid LGPL but requires a second driver or asynchronous migrations; unnecessary at this database load.
