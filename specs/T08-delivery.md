# T08 — Reproducible Delivery to the Customer

Status: available local T08 packaging and instructions are prepared for the developer's joint Telegram test; actual evidence and limits are in the [local report](../docs/testing/T08_LOCAL_REPORT.md). Full handoff acceptance remains pending. The final real-Telegram E2E, one integrated sealed benchmark shared by T01c/T07, clean-machine Windows checks and native Linux verification remain required. Updated 2026-09-28. No real Telegram request, external delivery or deployment was performed; native Linux verification was not performed.

## Goal and Basis

Deliver the finished product with reproducible local startup, settings, migrations, data deletion rules, and confirmed limitations; the customer will be able to deploy it on the agreed machine.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-014/017/020/023–026/032; [DATA_MODEL](../docs/architecture/DATA_MODEL.md); [SECURITY](../docs/security/SECURITY.md); [ADR-0005](../docs/decisions/ADR-0005-runtime-supervision-and-packaging.md). Local preparation follows T07's local checks. Full handoff acceptance also requires the joint Telegram E2E, the shared T01c/T07 benchmark, native Linux verification, and final OPERATIONS/contracts.

## Platform Boundaries and Dependencies

- Development and measurements use the user's Windows PC, whose hardware (6 GiB VRAM, 16 GiB RAM) is the reference class for v1 (S-11-A1). The customer's server, workload, and response time are unknown.
- Delivery for Windows x64 and Linux x86-64 with an NVIDIA GPU is accepted (S-09-A3); both platforms are checked separately. Windows uses a native installation; Linux uses Docker Compose (ADR-0005).
- “Works on Windows” does not mean Linux was checked, and vice versa. An unchecked platform is explicitly marked; instructions do not substitute for execution.
- Final Linux verification runs on a native Linux x86-64 host with an NVIDIA GPU; WSL2 on the development PC is acceptable only for early smoke tests of the container path (ED-008). The development PC booted natively into Linux, for example from a separate disk, qualifies and matches the reference hardware.
- Python/aiogram/PostgreSQL and direct local llama.cpp are selected; hardware requirements are derived from T01 and integration checks, not model weight size.

## Delivery Result

1. Application source with the uv lockfile; versions of Python, PostgreSQL, llama.cpp, the model and vision component, and artifact hashes. Linux: a Compose file and the application image pinned by digest. Windows: the pinned llama.cpp CUDA archive, the PostgreSQL service, and the bot service or scheduled task with start at boot and restart on failure.
2. Verified instructions for obtaining/installing required components from official sources, migrations, startup, and shutdown for each platform; actual commands after execution, without fictional “success.”
3. Example configuration without secrets: Telegram token, shared password with its length guidance, PostgreSQL, llama-server endpoint and API key, temp directory, launch profile, admission per-page times, operator IDs, 15 minutes of waiting, and 30 minutes of processing with the ability to configure these, plus the other agreed parameters. The configuration file lives outside the source tree.
4. Description of required access/connections: Telegram and PostgreSQL, local inference. Document processing has no cloud fallback; a user prompt cannot create external model access. BotFather settings disable adding the bot to groups.
5. User guide: login/logout, personal profiles with preview/confirm and multi-type instructions, a single file/album/Several pages, photo versus file quality, type clarification, partial responses, Busy and size refusals, and resubmission after restart.
6. Operations: one bot instance/long polling, one GPU task, in-memory queue, supervised child processes, cleanup before new uploads, operator alerts and logs without content, and the procedure for diagnosing unsuccessful deletion and a closed intake.
7. Back up only permitted persistent PostgreSQL settings; temp/originals/OCR/results/evidence are not included in backup. Restoring the DB does not revive document tasks or authorization.
8. List of licenses/notices for the delivered artifacts, including the model (Apache-2.0), llama.cpp (MIT), psycopg (LGPL-3.0), PDFium and its dependencies, PostgreSQL, CUDA libraries if shipped, the container base images, and the Python dependencies. Do not promise the right to repackage all artifacts without checking their terms.
9. Acceptance report: checked configurations/languages/document types, measurements, and negative results; no promise of an unknown SLA or universal accuracy.

## Acceptance and Checks

- On an agreed clean machine for each platform, the package starts according to the instructions without personal paths, developer secrets, or undeclared components.
- Versions/artifacts match those checked; migrations and restart preserve profiles. No documents, test personal data, or keys are inside the package.
- The smoke test has passed on each platform: login, profile creation/confirmation, one file, a multipage document, partial response, Cancel, timeout, and restart followed by login/resubmission.
- Backup/restore preserves only permitted data; temp is absent from the backup, and a new startup safely cleans up leftovers.
- Separate factual results are available for Windows and Linux x86-64/NVIDIA; a failure/untested status blocks declaring delivery ready for the corresponding platform.
- Delivery contents and instructions are checked by another reproducible run, not only by running on the current developer machine.

## Completion Conditions and Exclusions

Platforms and T07 criteria are defined. Local packaging and available platform checks may proceed, but T08 is not complete until the final Telegram E2E and shared benchmark pass and a native Linux test host with an NVIDIA GPU is verified. If that environment is unavailable, Linux remains unchecked and T08 is incomplete. The customer's specific server is not required to begin development. External delivery of the package and deployment are agreed separately; a package prepared locally does not mean it was externally sent.

Excluded: buying/creating a server, external deployment, granting permissions, uploading secrets, SLA, multiple bot instances, and changing the model at the implementer's discretion. Specific external actions are performed only with separate user authorization.
