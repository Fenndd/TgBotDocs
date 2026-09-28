# First-Version Architecture

Status: accepted baseline and design contracts for subsequent implementation. Date: 2026-09-27; revised after the independent review (verification layer, state machine, runtime supervision, packaging). Operational behavior has not yet been verified by running the system.

## System Boundaries

Telegram is the user interface and external transport. A Python application, PostgreSQL, and a local llama-server run on one self-hosted machine; for v1, the current PC is the development machine and the reference hardware class (S-11-A1). The bot supervises llama-server and the file-preparation workers as child processes. The model has no network tools; no external AI is used in processing.

Accepted ADRs: [local processing](../decisions/ADR-0001-local-processing.md), [stack and transport](../decisions/ADR-0002-application-stack.md), [recognition](../decisions/ADR-0003-direct-local-vlm.md), [abstention and verification](../decisions/ADR-0004-abstention-and-verification.md), [runtime supervision and packaging](../decisions/ADR-0005-runtime-supervision-and-packaging.md). Hardware and developer answers: [SOURCES](../requirements/SOURCES.md).

## Components and Responsibilities

| Component | Responsibility | State |
| --- | --- | --- |
| Telegram adapter / aiogram | Long polling, private chats, English UI, messages/callbacks, result rendering | One instance per token; handlers only enqueue events |
| Access and profiles | Shared password, temporary authorization, personal profiles with optimistic versions | Profiles in PostgreSQL; authorization in RAM |
| Submission coordinator | Per-user actors: one document per user, page collection, cancellation, timers, delivery ([STATE_MACHINE](STATE_MACHINE.md)) | Temporary process state |
| Admission control and GPU scheduler | Busy and size refusals, one model call at a time, interactive calls first, turns between documents | Temporary process state |
| File preparation | Format, PDFs/images, order/orientation, lazy page rendering per batch | Short-lived child processes; no external links |
| Document understanding | Open description of type and matching a personal profile, explicit uncertainty | Local model API |
| Extraction and merging | Profile fields/columns only, page references, cross-batch merging, conflicts, and statuses | Direct VLM, strict schema, and application checks |
| Verification layer | Downgrade-only signals: token probabilities, second reading, profile validators, cross-page agreement, optional local OCR | Calibrated thresholds of the frozen configuration |
| Local model adapter and supervisor | Streaming calls, timeout/cancellation, idle check, restart, JSON contract | Qwen3-VL-4B-Instruct Q4_K_M / llama.cpp child process |
| Persistence adapter | Profiles, owners, migrations, and transactions | PostgreSQL / SQLAlchemy / psycopg (synchronous, thread pool) / Alembic |
| Temporary storage, diagnostics, and alerts | Quotas, deletion with retries, safe technical events, operator alerts | No archive of originals, OCR, or results |

These are logical application modules, not a set of microservices. Proposed future code structure: domain — entities/contracts; application — flows and the state machine; adapters — Telegram, PostgreSQL, model, files; configuration — startup and parameters. Source-code folders are not created now.

## Processing One Document

1. Check that the chat is private, verify access, and pass the pre-download admission check.
2. Assemble one logical document: a single file, an album, or Several pages; count pages.
3. Estimate processing time: refuse a set that cannot finish within the budget; otherwise queue the job. Active documents take turns on the GPU, one model call each.
4. Determine the document type and applicable profile from the matching view. If none exists, request instructions and confirmation; if the match is ambiguous, ask the user to choose. The GPU remains idle and the processing budget pauses while waiting.
5. Pin the profile snapshot and extract the requested fields/lists from all pages in resource-bounded batches, rendering pages lazily.
6. Merge batches, apply the verification layer, and check the schema, sources, types, normalization, conflicts, and completeness; produce complete/partial/failed.
7. Deliver an English message with values as `code` entities, then delete the content. Errors, cancellation, TTL expiry, and restart also lead to cleanup.

Profiles may be created by converting text with the model through the same scheduler, as short interactive calls. A profile setup request never runs concurrently with another inference.

## Classification and Accuracy

Classification and extraction have separate contracts and may use multiple requests to the same model. A permanent taxonomy and a passport-only classifier are not required: the type and applicability are described by the profile. The model's response does not create a profile without confirmation.

Agreement between models, valid JSON, page evidence, and verbal confidence do not prove character-level accuracy. The verification layer ([ADR-0004](../decisions/ADR-0004-abstention-and-verification.md)) therefore uses signals only to withhold values: it downgrades a candidate but never upgrades or chooses one. Separate OCR is not part of the required path; a local OCR cross-check is an optional signal if T01 shows the need. Field policies and limitations are in [CONTRACTS](CONTRACTS.md); evidence of quality relies on independent ground truths in [acceptance](../testing/ACCEPTANCE_PLAN.md).

## Data and Reliability

[DATA_MODEL](DATA_MODEL.md) defines persistent and temporary data. [STATE_MACHINE](STATE_MACHINE.md) defines states, timers, scheduling, admission, and restart. [OPERATIONS](../operations/OPERATIONS.md) defines parameter values, the launch profile, and operator alerts. [USER_FLOWS](../requirements/USER_FLOWS.md) describes user transitions.

The process has no persistent document queue. After a crash, the user resubmits documents; profiles are retained. The first version has no group chats, horizontal scaling, or public web interface.

## Portability and Next Step

Target platforms are Windows and Linux x86-64 with an NVIDIA GPU. Windows uses a native installation; Linux uses Docker Compose with the bot and llama-server in one application container and PostgreSQL in another ([ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md)). Each platform must be checked before delivery; the customer's server and SLA are not defined yet. Integration uses a local HTTP contract, so portability does not require processing documents with external AI.

T01b is calibrated and frozen, so [T02](../../specs/T02-application-foundation.md) may proceed; this does not accept recognition quality. Continue local development and checks through T02–T08 in order. Defer benchmark preparation and the one sealed integrated quality run shared by T01c and T07 until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer. Local T07 resilience checks and T08 preparation may happen before then, but acceptance remains pending. Failure follows the remediation order of ADR-0004 on this PC.
