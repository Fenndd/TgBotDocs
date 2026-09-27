# T02 — Application Foundation and Local Execution

Status: specification ready; execution after T01c passes. Revised on 2026-09-27 after the independent review: walking skeleton first, runtime supervision, scheduler, and toolchain. The environment and dependencies are not created in the planning session.

## Goal and Basis

Prepare the minimum verifiable foundation, starting with a walking skeleton: the thinnest end-to-end path from Telegram through the recognition core and back. Then add the mechanisms the later tasks build on: the state machine skeleton, the supervised runtime, the GPU scheduler, PostgreSQL, and the temporary lifecycle.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-001/002/010/014/015/017–026; [SECURITY](../docs/security/SECURITY.md); [STATE_MACHINE](../docs/architecture/STATE_MACHINE.md); [ADR-0005](../docs/decisions/ADR-0005-runtime-supervision-and-packaging.md). The user selected Python + aiogram + PostgreSQL, one bot instance through long polling, private chats only, one GPU task, and an in-application queue.

## Components and Status of Technical Decisions

| Component | Role | Status |
| --- | --- | --- |
| Python, aiogram, PostgreSQL | Application, Telegram, persistent settings/access | Selected by the user |
| Python 3.14 (3.13 fallback), uv, aiogram 3 | Runtime line, interpreter and lockfile management, Telegram framework | ADR-0005; versions verified at installation |
| SQLAlchemy 2 + psycopg 3 (synchronous, thread pool) + Alembic | PostgreSQL access and migrations | ADR-0005 |
| Pydantic 2 | Internal contract validation | Project composition |
| httpx | Streaming client for the local llama-server | Project composition |
| pypdfium2 + Pillow | PDF page rendering and image processing in child processes | Project composition; module from T01b |
| Recognition core | Model adapter, preparation, matching/extraction, merging, verification | Built and frozen in T01b |
| pytest, Hypothesis | Unit/component tests; model-based state machine tests | Test tooling |

This composition is not proof of compatibility or an existing dependency lock. Interfaces — [CONTRACTS](../docs/architecture/CONTRACTS.md); states — STATE_MACHINE; parameters — [OPERATIONS](../docs/operations/OPERATIONS.md). Versions are checked and recorded in the implementation task.

## Scope and Dependencies

- [T01](T01-recognition-baseline.md) has passed with a frozen recognition configuration. The foundation does not declare the model functional in advance.
- The foundation follows [USER_FLOWS](../docs/requirements/USER_FLOWS.md), STATE_MACHINE, CONTRACTS, and OPERATIONS. Mechanisms and checks using controlled substitutes are created here; full user scenarios are connected in T03–T06.
- Standard Bot API; accepted download limit of 20 MB per file. There is no fixed page or file cap; admission control follows ED-002.
- Settings/profiles and necessary access information are persistent. Originals, OCR, and results are temporary; they are not stored in PostgreSQL, logs, or backup.
- After a crash restart, unfinished documents are deleted and must be sent again; profiles are retained. A durable document queue is not required.
- Development and first verification run natively on the Windows development PC. The Linux application image is built here and verified in T08.

## Expected Result

1. Walking skeleton first: a signed-in user in a private chat sends one image; the bot processes it with a fixed test profile through the T01b recognition core, replies in English under the rendering contract, and cleans up. The password check is minimal here; T03 completes access protection. Later steps extend this path instead of building layers in isolation.
2. Handlers only enqueue events; per-user actors apply transitions (STATE_MACHINE). Job IDs, generations, and per-process nonces protect callbacks and late results.
3. The bot supervises llama-server, started with the launch profile, and the file-preparation workers: a Job Object on Windows, a parent-death signal and container init on Linux, recorded PIDs, and termination of leftovers at startup.
4. The GPU scheduler runs one streaming call at a time under the priority rules; a cancellation is confirmed through the slots endpoint, or the runtime is restarted.
5. The application checks configuration and required dependencies at startup. The configuration file is read from a path outside the source tree, and secrets are not printed. PostgreSQL or model connection errors have an explicit outcome.
6. Persistent data is created through migrations; database access is synchronous in a dedicated thread pool; connections, transactions, and migrations have a reproducible launch path. Document contents are not part of the schema.
7. Temporary data is managed through a unified lifecycle with the cleanup service: retries with backoff, staged intake closure, and operator alert plumbing. Cleanup covers completion, error, cancellation, TTL, and startup after a crash; cancellation order prevents deleting a file in use without coordination with the worker.
8. Diagnostic events contain only necessary technical details.

## Checks and Completion Criteria

- Actual installation/launch/migration/check commands have been performed; do not record successful results before that.
- The walking skeleton runs end to end on the development PC with a real Telegram test bot and the real runtime.
- Clean local launch and relaunch after migrations; expected errors for missing parameters/unavailable dependencies.
- Two jobs do not create two concurrent GPU calls; an error in one job does not stop later jobs. Cancelling a queued job does not run it later. A cancelled streaming call releases the slot, and a hung call leads to a runtime restart.
- Killing the bot process leaves no running children; the next start terminates recorded leftovers and cleans the temporary directory before polling, also when the database/model is unavailable.
- Restart retains profiles, deletes unfinished documents, and does not silently resume them. Other users do not receive information about the lost set.
- Isolation of temporary areas and persistent records is checked with two users; group chats do not enter the product scenario.
- Temporary data, model inputs/responses, password, and token are not found in logs/backup. Error checks use synthetic data.
- The Linux application image builds; running it on a Linux host is a T08 check.

## Task Boundary

Interfaces and operating rules are defined by the related documents. Full dialogues, profiles from [T03](T03-access-and-profiles.md), set assembly, customer server, webhook, distributed queue, and multiprocess GPU execution are out of scope. Do not implement additional scenarios under the guise of a “foundation.”
