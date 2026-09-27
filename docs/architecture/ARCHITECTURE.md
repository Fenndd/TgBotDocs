# First-Version Architecture

Status: accepted baseline and design contracts for subsequent implementation. Date: 2026-09-27. Operational behavior has not yet been verified by running the system.

## System Boundaries

Telegram is the user interface and external transport. A Python application, PostgreSQL, and a local llama-server run on the PC. Temporary file preparation is isolated in a managed process. The model has no network tools; no external AI is used in processing.

Accepted ADRs: [local processing](../decisions/ADR-0001-local-processing.md), [stack and transport](../decisions/ADR-0002-application-stack.md), [recognition](../decisions/ADR-0003-direct-local-vlm.md). Hardware and developer answers: [SOURCES](../requirements/SOURCES.md).

## Components and Responsibilities

| Component | Responsibility | State |
| --- | --- | --- |
| Telegram adapter / aiogram | Long polling, private chats, English UI, messages/callbacks | One instance per token |
| Access and profiles | Shared password, temporary authorization, personal profiles and confirmed versions | Profiles in PostgreSQL; authorization in RAM |
| Submission coordinator | One document per user, page collection, queue, cancellation, TTL, delivery | Temporary process state |
| File preparation | Format, PDFs/images, order/orientation, controlled page batches | Managed child process; no external links |
| Document understanding | Open description of type and matching a personal profile, explicit uncertainty | Local model API |
| Extraction and validation | Profile fields/columns only, page evidence, conflicts, and statuses | Direct VLM, strict schema, and application checks |
| Local model adapter | Request serialization, timeout/cancellation, JSON contract | Qwen3-VL-4B-Instruct Q4_K_M / llama.cpp |
| Persistence adapter | Profiles, versions, owners, migrations, and transactions | PostgreSQL / SQLAlchemy / psycopg / Alembic |
| Temporary storage and diagnostics | Quotas, deletion, safe technical events | No archive of originals, OCR, or results |

These are logical application modules, not a set of microservices. Proposed future code structure: domain — entities/contracts; application — flows; adapters — Telegram, PostgreSQL, model, files; configuration — startup and parameters. Source-code folders are not created now.

## Processing One Document

1. Check that the chat is private and verify access before downloading.
2. Assemble one logical document: a single file, an album, or Several pages.
3. Accept it into a bounded queue, check the deadline/resources, and prepare the pages.
4. Determine the document type and applicable profile. If none exists, request instructions and confirmation; if the match is ambiguous, ask the user to choose. The GPU remains idle while waiting.
5. Pin a snapshot of the profile version and extract the requested fields/lists from all pages in resource-bounded batches.
6. Check the schema, sources, types, normalization, conflicts, and completeness; produce complete/partial/failed.
7. Deliver an English message, then delete the content. Errors, cancellation, TTL expiry, and restart also lead to cleanup.

Profiles may be created by converting text with the model, but use the same sequential scheduler. A profile setup request must not compete for the GPU with a second inference.

## Classification and Accuracy

Classification and extraction have separate contracts and may use multiple requests to the same model. A permanent taxonomy and a passport-only classifier are not required: the type and applicability are described by the profile. The model's response does not create a profile without confirmation.

Separate OCR is not part of the required architecture. Its usefulness may be discussed after analyzing errors in the selected path. Agreement between models, valid JSON, page evidence, and verbal confidence do not prove character-level accuracy. Field policies and limitations are in [CONTRACTS](CONTRACTS.md); evidence of quality relies on independent ground truths in [acceptance](../testing/ACCEPTANCE_PLAN.md).

## Data and Reliability

[DATA_MODEL](DATA_MODEL.md) defines persistent and temporary data. [OPERATIONS](../operations/OPERATIONS.md) defines the queue, timers, quotas, restart, delivery, and cleanup. [USER_FLOWS](../requirements/USER_FLOWS.md) describes user transitions.

The process has no persistent document queue. After a crash, the user resubmits documents; profiles are retained. The first version has no group chats, horizontal scaling, or public web interface.

## Portability and Next Step

Target platforms are Windows and Linux x86-64 with an NVIDIA GPU. Each must be checked before delivery; the customer's server and SLA are not defined yet. Integration uses a local HTTP contract, so portability does not require processing documents with external AI.

The next specific task is [T01](../../specs/T01-recognition-baseline.md): test the selected model on the current PC. Success allows [T02](../../specs/T02-application-foundation.md) to proceed; failure returns the significant choice to the developer.
