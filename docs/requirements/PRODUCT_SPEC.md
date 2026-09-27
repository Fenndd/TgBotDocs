# Product Specification

Status: agreed first-version baseline, 2026-09-27; REQ-014, REQ-021, and REQ-025 clarified after the independent review. Requirements are traceable to [S-01–S-13](SOURCES.md). There is no implementation or product testing yet.

## Purpose and Scope

An authorized user sends a document to the Telegram bot. The bot identifies the document type, selects a personal profile, and extracts only the requested fields or lists of records. If there is no profile, it asks for instructions; if the type or data is unclear, it asks for clarification or reports this honestly.

The first version accepts arbitrary documents in any language, with no built-in closed catalog and no language whitelist. This is not a promise that any content will be read without errors. The original script of values is preserved; the interface is in English. Materials and quality are checked according to the [accepted procedure](../testing/ACCEPTANCE_PLAN.md).

Development and the first check are performed on the current PC, whose hardware is also the limit for v1 recognition (S-11-A1). The deliverable is a product ready to hand over to the customer, with a verified launch on Windows and Linux x86-64/NVIDIA. The customer's specific server, workload, and SLA will be chosen later.

## Requirements and Verifiable Behavior

| ID | Requirement / behavior criterion | Source |
| --- | --- | --- |
| REQ-001 | The interface for receiving documents and results is Telegram | S-01 |
| REQ-002 | Accept PNG, JPG/JPEG, and PDF; a damaged, password-protected, or unsupported file receives an explicit outcome | S-01; USER_FLOWS details |
| REQ-003 | Sending a single image is sufficient to start without a separate processing command | S-01 |
| REQ-004 | The user specifies in ordinary text which data is needed for document types | S-01 |
| REQ-005 | Return only the requested data and operational statuses; additional model fields do not pass into the response | S-01, S-06-A2 |
| REQ-006 | For a recognized type without a configuration, request instructions in the chat, then preview/confirm | S-01, S-06-A1 |
| REQ-007 | Report inability to recognize the document or the required data | S-01 |
| REQ-008 | Do not create a permanent document archive; temporary processing is specified in REQ-020 | S-01, S-05-A3 |
| REQ-009 | All bot responses, menus, errors, and authorization are in English; document values are not translated automatically | S-01, S-09-A1 |
| REQ-010 | After /start, require the shared password from .env; before the correct password, no download/processing/settings are available | S-01 |
| REQ-011 | Support multiple pages and/or files for one document, including both sides of a card | S-02-U2.3 |
| REQ-012 | Check ordinary phone photographs: rotation, perspective, shadow, glare, blur | S-02-U2.4 |
| REQ-013 | Do not present a doubtful type as established; uncertainty leads to clarification/refusal; quality is evaluated by REQ-031 | S-02-U2.2, S-06-A2, S-09-A2 |
| REQ-014 | Model processing is local and self-hosted on the machine that runs the bot; images, derived text, and results are not sent to external AI. v1 recognition must fit and pass on the current PC's hardware (6 GiB VRAM, 16 GiB RAM), which is the reference hardware class of the delivered product | S-04-A2/A3, S-11-A1 |
| REQ-015 | Standard Bot API with the accepted Telegram download limit of 20 MB per file; there is no lower product-specific limit | S-06-A3 clarifies S-02-U2.5 |
| REQ-016 | Arbitrary document types already in the first version; passport/residence permit are examples, not a catalog | S-04-A1 |
| REQ-017 | Prepare a finished product for handover to the customer, with reproducible launch and a guide | S-04-A3 |
| REQ-018 | Each user has personal settings; other users' profiles are inaccessible and are not applied | S-05-A2 |
| REQ-019 | One set is one document: a single file is processed automatically, an album is a set, and separate files are collected through Several pages → Process | S-05-A1 |
| REQ-020 | Temporary disk is allowed; originals/derived data/results are deleted after a response, cancellation, error, or TTL. Settings and necessary access data are persistent; content is not in logs/backup | S-05-A3 |
| REQ-021 | An instruction becomes one or more personal profiles, one per described document type, with applicability, fields, and guidance; they are saved after preview/confirmation. Multiple applicable profiles trigger a choice | S-01, S-06-A1; ED-001 |
| REQ-022 | Full/partial English text result: readable fields and Missing / Unreadable / Ambiguous. No guesses; a doubtful type is clarified. A JSON file is not required | S-06-A2 |
| REQ-023 | Application stack: Python + aiogram + PostgreSQL | S-07-A1 |
| REQ-024 | Direct Qwen3-VL-4B-Instruct Q4_K_M via llama.cpp; the first task is to check its suitability on the PC | S-07-A2 |
| REQ-025 | One bot instance, long polling, one active GPU task, an application queue in which active documents take turns, private chats only | S-07-A3, S-12-A1 |
| REQ-026 | After a crash, unfinished documents are not restored: they are cleaned up and must be resent; profiles are retained | S-07-A3 |
| REQ-027 | Scalar fields and lists of records with specified columns; no arbitrary calculations/free-form reports | S-08-A1 |
| REQ-028 | Any language without a whitelist; attempt to read, preserve the original script, and be honest about uncertainty/impossibility | S-09-A1 |
| REQ-029 | Authorization lasts until restart or /logout; a new password takes effect on restart | S-08-A3 |
| REQ-030 | One unfinished document per user; 15 minutes of inactivity for collection/clarification, 30 minutes for processing, then error/cleanup; parameters are configurable | S-08-A3 |
| REQ-031 | 70 test cases: 40 readable, 20 challenging photos, 10 negative. Zero incorrectly accepted values/profiles, ≥90% of fields/cells in the readable portion; failure requires improvement/review | S-09-A2 |
| REQ-032 | Verified Windows and Linux x86-64/NVIDIA delivery: installation, configuration, migrations, licenses; customer server later | S-09-A3 |

## Details and Exclusions

[USER_FLOWS](USER_FLOWS.md) defines scenarios, [CONTRACTS](../architecture/CONTRACTS.md) defines statuses/fields/lists, [DATA_MODEL](../architecture/DATA_MODEL.md) defines versions and storage, [STATE_MACHINE](../architecture/STATE_MACHINE.md) defines states and timers, and [OPERATIONS](../operations/OPERATIONS.md) defines parameters, queue, and failures. These engineering details implement the accepted requirements and are not attributed to the source text as verbatim instructions; engineering decisions are labeled ED in the [decision register](OPEN_QUESTIONS.md).

The first version does not include groups, a shared profile catalog, a web console, SaaS/payments, permanent document history, JSON export, KYC/authenticity verification, free-form reports, fine-tuning, a distributed queue, or a hidden cloud fallback. Scalar values and one level of lists of records with columns are the agreed extraction scope; arbitrary nesting is identified in the interface as unsupported.

Universal error-free performance and readiness for unknown workloads are not promised. The accepted criteria apply to the tested set, and Linux and model suitability must be confirmed through execution in the relevant tasks.
