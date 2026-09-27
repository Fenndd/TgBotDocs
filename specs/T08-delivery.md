# T08 — Reproducible Delivery to the Customer

Status: specification ready; execution after T01–T07. Date: 2026-09-27. External hosting, server creation, and environment setup are not performed now.

## Goal and Basis

Deliver the finished product with reproducible local startup, settings, migrations, data deletion rules, and confirmed limitations; the customer will be able to deploy it on the agreed machine.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-014/017/020/023–026; [DATA_MODEL](../docs/architecture/DATA_MODEL.md); [SECURITY](../docs/security/SECURITY.md). Dependencies: completed T01–T07 and final OPERATIONS/contracts.

## Platform Boundaries and Dependencies

- Current development/measurements use the user's Windows PC. The customer's server, GPU/RAM, workload, and response time are unknown.
- Delivery for Windows x64 and Linux x86-64 with an NVIDIA GPU is accepted (S-09-A3); both platforms are checked separately.
- “Works on Windows” does not mean Linux was checked, and vice versa. An unchecked platform is explicitly marked; instructions do not substitute for execution.
- Python/aiogram/PostgreSQL and direct local llama.cpp are selected; hardware requirements are derived from T01 and integration checks, not model weight size.

## Delivery Result

1. Application source and reproducible pinning of verified Python dependencies; versions of PostgreSQL, llama.cpp, the model/vision component, and artifact hashes.
2. Verified instructions for obtaining/installing required components from official sources, migrations, startup, and shutdown; actual commands after execution, without fictional “success.”
3. Example configuration without secrets: Telegram token, shared password, PostgreSQL, local model endpoint, temp directory, 15 minutes of waiting, and 30 minutes of processing with the ability to configure these, plus the other agreed parameters.
4. Description of required access/connections: Telegram and PostgreSQL, local inference. Document processing has no cloud fallback; a user prompt cannot create external model access.
5. User guide: login/logout, personal profiles with preview/confirm, a single file/album/Several pages, type clarification, partial responses, and resubmission after restart.
6. Operations: one bot instance/long polling, one GPU task, in-memory queue, cleanup before new uploads, monitoring technical errors without content, and procedure for diagnosing unsuccessful deletion.
7. Back up only permitted persistent PostgreSQL settings; temp/originals/OCR/results/evidence are not included in backup. Restoring the DB does not revive document tasks or authorization.
8. List of licenses/notices for the model, llama.cpp, and dependencies in the selected delivery. Do not promise the right to repackage all artifacts without checking their terms.
9. Acceptance report: checked configurations/languages/document types, measurements, and negative results; no promise of an unknown SLA or universal accuracy.

## Acceptance and Checks

- On an agreed clean machine, the package starts according to the instructions without personal paths, developer secrets, or undeclared components.
- Versions/artifacts match those checked; migrations and restart preserve profiles. No documents, test personal data, or keys are inside the package.
- The smoke test has passed: login, profile creation/confirmation, one file, a multipage document, partial response, Cancel, timeout, and restart followed by login/resubmission.
- Backup/restore preserves only permitted data; temp is absent from the backup, and a new startup safely cleans up leftovers.
- Separate factual results are available for Windows and Linux x86-64/NVIDIA; a failure/untested status blocks declaring delivery ready for the corresponding platform.
- Delivery contents and instructions are checked by another reproducible run, not only by running on the current developer machine.

## Completion Conditions and Exclusions

Platforms and T07 criteria are defined. Acceptance requires a Linux test host with agreed resources/authorized access; this is a future T08 check. If such an environment is not yet available, Linux remains unchecked and T08 is incomplete. The customer's specific server is not required to begin development. External delivery of the package and deployment are agreed separately; a package prepared locally does not mean it was externally sent.

Excluded: buying/creating a server, external deployment, granting permissions, uploading secrets, SLA, multiple bot instances, and changing the model at the implementer's discretion. Specific external actions are performed only with separate user authorization.

