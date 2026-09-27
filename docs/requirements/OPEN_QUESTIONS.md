# Decision and Remaining Verification Register

Updated: 2026-09-27. The main first-version product and architectural questions have been closed by direct developer answers. Sources: [S-01–S-09](SOURCES.md).

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

Project details — field types, versioning, retry timers, resource protection, and libraries — are explicitly described in the contracts/operations documents. They are not attributed verbatim to TT.txt. The key decisions and user-facing time limits above are kept separate from engineering defaults.

## Checks Remaining for Development

| Check | Where it is performed | Why this is not an open architectural choice |
| --- | --- | --- |
| Model suitability, context/batch/resolution parameters, RAM/VRAM, and speed | T01 | The initial candidate has been selected; the experiment has criteria for continuing/revisiting it |
| Compatible exact library versions, runtime, and lockfile | T01/T02 | Component lines are defined; installation and verification belong to implementation |
| Control-sample materials and independent ground truth | T01/T07 | Scope and criteria are accepted; creating a verification tool/data is not allowed in this session |
| Actual launch and acceptance on Windows/Linux | T08 | Target platforms are agreed; the result cannot be declared before execution |
| Customer's specific machine, workload, and SLA | After the local working product | The user explicitly deferred the server; this does not block the agreed development |

Failure to meet T01 requires a new fact-based discussion. It is not grounds to declare the model suitable in advance or change it without the developer.

## Historical Clarification on File Size

The preference in S-02-U2.5 for no limit was clarified by the explicit choice in S-06-A3. The [standard Bot API](https://core.telegram.org/bots/api#file) limits downloads to 20 MB; the [local server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) removes this limit, but was not selected. Verified against the official documentation on 2026-09-27.
