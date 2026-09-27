# Decision and Remaining Verification Register

Updated: 2026-09-27, after the independent review. The main first-version product and architectural questions have been closed by direct developer answers. Sources: [S-01–S-13](SOURCES.md).

## Decisions Made

| ID | Decision | Rationale and details |
| --- | --- | --- |
| Q-001 | Arbitrary document types in the first version; no closed catalog | S-04-A1; REQ-016 |
| Q-002 | Model processing on the current PC, without external AI; server later | S-04-A2/A3; [ADR-0001](../decisions/ADR-0001-local-processing.md) |
| Q-003 | Target is the current PC with 16 GiB RAM / 6 GiB VRAM; the customer's unknown workload/SLA is not invented | S-04-A3, E-01; working range to be measured in T01 |
| Q-004 | One file automatically; album as a set; Several pages → Process; one set is one document | S-05-A1; [USER_FLOWS](USER_FLOWS.md) |
| Q-005 | Personal profiles from text, with preview and confirmation | S-05-A2, S-06-A1; [DATA_MODEL](../architecture/DATA_MODEL.md) |
| Q-006 | Temporary disk is allowed; contents are deleted and not included in logs/backup/DB; resend after a crash | S-05-A3, S-07-A3; [SECURITY](../security/SECURITY.md) |
| Q-007 | Standard Bot API, accepted download limit of 20 MB per file; resource failures are explained | S-06-A3; [OPERATIONS](../operations/OPERATIONS.md) |
| Q-008 | Type is linked to the personal profile description; multiple applicable profiles trigger clarification; a new one is saved after confirmation | S-06-A1; [CONTRACTS](../architecture/CONTRACTS.md) |
| Q-009 | Direct Qwen3-VL-4B-Instruct Q4_K_M via llama.cpp; first, experiment on the PC | S-07-A2; [ADR-0003](../decisions/ADR-0003-direct-local-vlm.md) |
| Q-010 | 70 test cases; 0 incorrectly accepted values/profiles; ≥90% of requested fields/cells in the readable portion | S-09-A2; [ACCEPTANCE_PLAN](../testing/ACCEPTANCE_PLAN.md) |
| Q-011 | Partial English text response, explicit statuses, type clarification; JSON file not needed | S-06-A2; REQ-022 |
| Q-012 | Python + aiogram + PostgreSQL; one bot/long polling/one GPU task/queue; Windows and Linux x86-64/NVIDIA | S-07-A1/A3, S-09-A3; [ADR-0002](../decisions/ADR-0002-application-stack.md) |
| Q-013 | Private chats; sign-in until restart/logout; password changes on restart; one active document; 15-minute waiting, 30-minute processing | S-07-A3, S-08-A3; [OPERATIONS](../operations/OPERATIONS.md) |
| Q-014 | Scalar fields and lists of records with columns; no arbitrary calculations/reports | S-08-A1; REQ-027 |
| Q-015 | Any language without a whitelist, original script, honest refusal when reading is not possible | S-08-A2, S-09-A1; REQ-028 |
| Q-016 | The developer is the final decision-maker; the brief's core purpose and explicit constraints are preserved unless the developer changes them | S-10; engineering details are recorded as ED below |
| Q-017 | v1 recognition must pass on the current PC's hardware (6 GiB VRAM, 16 GiB RAM); T01 remediation stays within it; a stronger GPU server is not a v1 escalation path; narrowing the scope or revising the criteria needs a separate developer decision | S-11-A1; [ADR-0004](../decisions/ADR-0004-abstention-and-verification.md); REQ-014 |
| Q-018 | Active documents take turns on the GPU, one model call each, in admission order; a long document does not block short ones, and its 30-minute budget counts only its own work | S-12-A1; [STATE_MACHINE](../architecture/STATE_MACHINE.md) |
| Q-019 | Profiles can be edited while the user's document is queued or processed, but not while the bot waits for the user's answer about it; the running document keeps its snapshot; a document question waits until an open profile draft is closed | S-13-A1; supersedes ED-004 |

Project details — field types, versioning, retry timers, resource protection, and libraries — are explicitly described in the contracts/operations documents. They are not attributed verbatim to TT.txt. The key decisions and user-facing time limits above are kept separate from engineering defaults.

## Engineering Decisions

Recorded under S-10-A4. They are not developer answers: each follows from the cited requirements, and the developer can override it. The last column names the documents that apply the decision. Significant architectural choices are ADRs: [ADR-0004](../decisions/ADR-0004-abstention-and-verification.md) (verification layer) and [ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md) (runtime supervision, packaging, toolchain).

| ID | Decision | Basis | Applied in |
| --- | --- | --- | --- |
| ED-001 | One instruction may describe several document types. The compiler returns one profile draft per described type; all drafts appear in one preview and are saved atomically on confirmation. Later edits are per profile | The S-01 example instruction covers a passport and a residence permit; REQ-004 refers to document types in the plural; S-06-A1 | CONTRACTS, USER_FLOWS, DATA_MODEL, REQ-021, T03 |
| ED-002 | No fixed page or file caps. The accepted 30-minute limit is applied before GPU work: a set that cannot finish within the budget even at the lower-bound per-page time measured in T01 is refused with an explicit message. When all job slots are taken, a new job is refused as Busy before download | REQ-015 and S-06-A3 exclude a product-specific size limit; S-08-A3 sets the 30-minute limit; an explicit refusal before work is not truncation | STATE_MACHINE, OPERATIONS, USER_FLOWS, T04, T06 |
| ED-003 | The 30-minute processing budget is cumulative per document and charged only for the job's own work in matching, instruction compilation, and extraction until the result is ready for delivery. Waiting for the user (collection, clarification, preview) or for the GPU is not charged; the waiting states use the 15-minute inactivity timer. Delivery keeps its own window | S-08-A3 separates "15 minutes of inactivity for collection/clarification" from "30 minutes for processing" | STATE_MACHINE, OPERATIONS, T05, T06 |
| ED-004 | Superseded by Q-019 (S-13-A1). The earlier choice made Settings read-only during a whole job so that free text had one recipient | REQ-030; S-13-A1 | — |
| ED-005 | Updates created before the process start are stale: no state change and no download; one restart notice per user; a stale message equal to the password is deleted and does not sign the user in | REQ-026, REQ-029; Telegram keeps undelivered updates for up to 24 hours | STATE_MACHINE, OPERATIONS, USER_FLOWS, T06 |
| ED-006 | Content-free operator alerts go to optional configured Telegram IDs. A failed deletion is retried with backoff; then intake closes for everyone with an alert and reopens automatically when the leftovers are gone | REQ-020 requires fail-closed deletion; the product has no admin role, so a closed intake must not stay silent | OPERATIONS, STATE_MACHINE, SECURITY, T02, T06, T08 |
| ED-007 | A profile is one row with a version number (optimistic concurrency); previous versions are not retained; jobs use in-memory snapshots | No feature reads profile history; jobs do not survive a restart; old versions would keep text the user removed | DATA_MODEL, CONTRACTS, T03 |
| ED-008 | Final Linux verification runs on a native Linux x86-64 host with an NVIDIA GPU; WSL2 on the development PC serves only early smoke tests of the container path | REQ-032; WSL2 uses a paravirtualized GPU driver stack | ROADMAP, T08, ADR-0005 |
| ED-009 | Access hardening within the shared-password model: constant-time comparison, deletion of the password message, per-user attempt limits with an operator alert on a global surge (a global pause would let anyone block sign-ins), group joining disabled in BotFather, and configuration outside the source tree | S-01 and REQ-010 keep a simple shared password; bots can delete incoming private messages within 48 hours | SECURITY, OPERATIONS, USER_FLOWS, T03, T08 |
| ED-010 | Results are plain text with values in `code` entities and link previews disabled; `invalid` is shown as Unreadable with a reason; a result without any accepted value is `failed`, including one in which every field is `missing` | REQ-005, REQ-007, REQ-022; Telegram recognizes URLs, mentions, and commands in plain text | CONTRACTS, USER_FLOWS, T06 |
| ED-011 | Telegram photos are taken at the largest size and recorded as the compressed path; the benchmark records delivery paths, and at least half of the difficult photographs use the photo path; an unreadable value from a compressed photo leads to a suggestion to resend as a file | REQ-003, REQ-012; Telegram keeps photos only as resized JPEGs of at most 1,280 or 2,560 px | USER_FLOWS, ACCEPTANCE_PLAN, T04, T07 |
| ED-012 | T01 runs as T01a (runtime feasibility), T01b (recognition core and calibration), and T01c (sealed benchmark); the benchmark has a replacement rule; T02 starts with a walking skeleton | S-07-A2 (check the model first); REQ-031; early integration feedback | T01, T02, ROADMAP, ACCEPTANCE_PLAN, TEST_STRATEGY |
| ED-013 | Overlap rules for S-13-A1: at most one flow waits for the user's input at a time; Several pages collection and the awaiting states count as waiting; a job question is deferred while a Settings draft is open, with a notice, and its inactivity timer starts when the question is shown; Several pages starts only after an open draft is closed; Save during a running job says that the change applies to later documents | S-13-A1; free text must have exactly one recipient | STATE_MACHINE, USER_FLOWS, DATA_MODEL, T03, T06 |

## Checks Remaining for Development

| Check | Where it is performed | Why this is not an open architectural choice |
| --- | --- | --- |
| Runtime envelope, launch profile, and runtime behavior: fit, speed, cancellation, token probabilities | T01a | The model is selected; the configuration within the PC is chosen by measurement |
| Model suitability, verification thresholds, and enabled signals | T01b/T01c | Criteria, calibration rules, and the remediation order are fixed (ADR-0004, S-11-A1) |
| Compatible exact library versions, Python line, runtime, and lockfile | T01b/T02 | The toolchain is decided in ADR-0005; versions are verified at installation |
| Tuning-set and benchmark materials and independent ground truth | T01b/T01c/T07 | Scope, criteria, and the review procedure are accepted; creating data is not allowed in this session |
| Per-page times for admission control | T01b/T01c | The admission rule is fixed (ED-002); only its values are measured |
| Actual launch and acceptance on Windows/Linux | T08 | Target platforms and packaging are decided (ADR-0005); the result cannot be declared before execution |
| Native Linux x86-64/NVIDIA verification host | Before T08 | A resource, not a design choice (ED-008); the current PC booted natively into Linux qualifies |
| Customer's specific machine, workload, and SLA | After the local working product | The user explicitly deferred the server; this does not block the agreed development |

Failure to meet T01 follows the remediation order of ADR-0004 on the current PC (S-11-A1). It is not grounds to declare the model suitable in advance or change it without the developer; narrowing the scope or revising the criteria is the developer's decision.

## Historical Clarification on File Size

The preference in S-02-U2.5 for no limit was clarified by the explicit choice in S-06-A3. The [standard Bot API](https://core.telegram.org/bots/api#file) limits downloads to 20 MB; the [local server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) removes this limit, but was not selected. Verified against the official documentation on 2026-09-27.
