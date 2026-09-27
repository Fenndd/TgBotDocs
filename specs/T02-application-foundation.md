# T02 — Application Foundation and Local Execution

Status: specification ready; execution after successful T01. The environment and dependencies are not created in the planning session.

## Goal and Basis

Prepare the minimum verifiable foundation for the future application: Telegram entry, PostgreSQL for persistent settings/access, a local recognition interface, and sequential execution of GPU tasks.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-001/002/010/014/015/017–022; [SECURITY](../docs/security/SECURITY.md). The user selected Python + aiogram + PostgreSQL, one bot instance through long polling, private chats only, one GPU task, and an in-application queue.

## Components and Status of Technical Decisions

| Component | Role | Status |
| --- | --- | --- |
| Python, aiogram, PostgreSQL | Application, Telegram, persistent settings/access | Selected by the user |
| Python 3.12, aiogram 3 | Specific runtime/framework line | Project composition; compatibility and versions are checked during implementation |
| SQLAlchemy 2 + psycopg 3 + Alembic | PostgreSQL access and migrations | Project composition |
| Pydantic 2 | Internal contract validation | Project composition |
| httpx | Asynchronous client for local llama.cpp | Project composition |
| pypdfium2 + Pillow | PDF page rendering and image processing | Project composition |

This composition is not proof of compatibility or an existing dependency lock. Interfaces — [CONTRACTS](../docs/architecture/CONTRACTS.md); parameters — [OPERATIONS](../docs/operations/OPERATIONS.md). Versions are checked and recorded in the implementation task; the current session is limited to planning.

## Scope and Dependencies

- [T01](T01-recognition-baseline.md) first confirms the acceptability of the selected recognition or records the basis for reconsideration. The foundation does not declare the model functional in advance.
- The foundation follows [USER_FLOWS](../docs/requirements/USER_FLOWS.md), CONTRACTS, and OPERATIONS. Mechanisms and checks using controlled substitutes are created here; full user scenarios are connected in T03–T06.
- Standard Bot API; accepted download limit of 20 MB per file. Do not introduce a lower custom limit or substitute a total-set-size limit without a decision.
- Settings/profiles and necessary access information are persistent. Originals, OCR, and results are temporary; they are not stored in PostgreSQL, logs, or backup.
- After a crash restart, unfinished documents are deleted and must be sent again; profiles are retained. A durable document queue is not required.

## Expected Result

1. Telegram handlers, access/profiles, document lifecycle, local recognition interface, and external result representation are separated. Layer details should support testing, not create separate services without a need.
2. The application checks configuration and required dependencies at startup; secrets are loaded from an allowed configuration and are not printed. PostgreSQL or model connection errors have an explicit outcome.
3. One long-polling session accepts private chats only. Lack of authorization blocks document processing and changes to personal settings.
4. The queue is in the application; only one GPU recognition call runs at a time. Command intake, cancellation, and responding to the user are not blocked by synchronous handler work.
5. Persistent data is created through migrations; connections, transactions, and migrations have a reproducible launch path. Document contents are not part of the schema.
6. The llama.cpp client has a verifiable contract, handles unavailability/timeout/invalid responses, and links the job to its owner/set. Timeouts and retries come from OPERATIONS.
7. Temporary data is managed through a unified lifecycle. Cleanup covers completion, error, cancellation, TTL, and startup after a crash; cancellation order prevents deleting a file in use without coordination with the worker.
8. The result is sent according to the English user-facing contract; diagnostic events contain only necessary technical details.

## Checks and Completion Criteria

- Actual installation/launch/migration/check commands have been performed in the future environment; do not record successful results before that.
- Clean local launch and relaunch after migrations; expected errors for missing parameters/unavailable dependencies.
- Two jobs do not create two concurrent GPU calls; an error in one job does not stop later jobs. Canceling a queued job does not run it later.
- Restart retains profiles, deletes unfinished documents, and does not silently resume them. Other users do not receive information about the lost set.
- Isolation of temporary areas and persistent records is checked with two users; group chats do not enter the product scenario.
- Temporary data, model inputs/responses, password, and token are not found in logs/backup. Error checks use synthetic data.

## Task Boundary

Interfaces and operating rules are defined by the related documents. Acceptance must check cleanup of crash leftovers when the database/model is unavailable. Full recognition, profiles from [T03](T03-access-and-profiles.md), set assembly, customer server, webhook, distributed queue, and multiprocess GPU execution are out of scope. Do not implement additional scenarios under the guise of a “foundation.”
