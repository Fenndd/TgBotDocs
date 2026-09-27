# Work Status

Updated: 2026-09-27.

## Current Stage

**Implementation is active in T01.** T01a's technical transition condition is met on the current PC; see the [measured feasibility report](docs/testing/T01A_REPORT.md). T01b recognition-core implementation is starting. Human review of the synthetic development/tuning corpus remains pending; no accepted calibration or sealed benchmark has run. T02 is prohibited until T01c passes.

## Current Development Evidence

- The user authorized local implementation, dependencies, model downloads, tests, worktrees, and logical commits; no push, remote deployment, external inference, or final real-Telegram E2E is authorized. Linux hardware verification unavailable on this PC must remain explicitly deferred.
- Work is isolated on `codex/local-product`; the original `main` checkout was clean and remains preserved. Fixture work was separately committed and integrated. Parallel independent changes use separate worktrees.
- Official Qwen3-VL-4B Q4_K_M/FP16 mmproj and llama.cpp b11221 CUDA 12.4 artifacts were downloaded and hash-verified. Six serialized configurations, actual PDF renders, simulated JPEG paths, cancellation, timeout recovery, restart, context envelope, multilingual development diagnostics, and localization were measured. All content-free results and limits are linked from T01A_REPORT.
- The measured starting profile is GPU vision, q8_0 K/V, context 4096, image maximum 1024, PDF 150 DPI. Two pages fit the probe prompt and 1024 output-token reserve; production prompts must calculate their own admission. The 12-case diagnostic matched 69/75 generated values, with Arabic and Devanagari differences; this is not an accepted quality result.
- The 12-case gallery is local at `C:\Users\nikit\AppData\Local\TgBotDocs\t01a-fixtures-dev-v5\review.html`. A human review request is pending. Automatic visual review and deterministic generation do not satisfy the mandatory human-review procedure. Additional tuning and genuine photograph evidence remain required before quality acceptance.
- Six measurement-harness tests pass. An independent Sol/high review found measurement issues that were fixed. Product-level supervision, contracts, calibration, and resilience are not yet verified.
- Next: implement and verify the T01b production recognition core, prepare at least 20 tuning cases for review, calibrate only after the required review, freeze, then execute the sealed T01c gate. Never promote development/tuning originals or their variants to the benchmark.

The planning and assistant-setup sections below are historical records from preceding tasks; statements about no implementation or commits refer to those tasks.

## Post-Review Remediation

An independent pre-development review on 2026-09-27 was delivered in chat and is not stored as a separate file. Its findings were resolved in the planning documents:

- Developer decisions: [S-10](docs/requirements/SOURCES.md) — the developer is the final decision-maker; S-11 — if T01 fails, remediation stays on the current PC's hardware, and a stronger GPU server is not a v1 escalation path; S-12 — active documents take turns on the GPU, one model call each; S-13 — profiles can be edited while a document is queued or processed, but not while it waits for the user's answer (supersedes ED-004).
- Engineering decisions ED-001–ED-013 in the [decision register](docs/requirements/OPEN_QUESTIONS.md), with ED-004 superseded; [ADR-0004](docs/decisions/ADR-0004-abstention-and-verification.md) (downgrade-only verification layer, calibration, remediation order) and [ADR-0005](docs/decisions/ADR-0005-runtime-supervision-and-packaging.md) (child-process supervision, streaming cancellation, synchronous database access, packaging, toolchain).
- New [STATE_MACHINE](docs/architecture/STATE_MACHINE.md): the single reference for sessions, jobs, timers, scheduler, admission, restart, and cleanup.
- Revised: PRODUCT_SPEC (REQ-014, REQ-021), CONTRACTS, DATA_MODEL, USER_FLOWS, OPERATIONS, SECURITY, ARCHITECTURE, RECOGNITION_OPTIONS, ACCEPTANCE_PLAN, TEST_STRATEGY, ROADMAP, clarifications in ADR-0001–ADR-0003, specifications T01–T08 and their index, README, and PLAN.
- Checks passed: internal links, Markdown table structure, UTF-8/LF/final newline, 32 unique requirement IDs, a search for superseded terms, and `git diff --check`. External facts used in the new ADRs were checked against official sources on 2026-09-27: the Telegram Bot API and file documentation, the llama.cpp server README, issues, and Docker documentation, the Qwen3-VL-4B configuration, psycopg, the Python asyncio and version documentation, and aiogram.
- Second completeness pass: every review finding was traced to the changed documents. Gaps closed: the definition of user activity; budget-exhaustion and failure transitions in every processing state; download, file, and quota errors during collection; behavior while the database or runtime is unavailable; Telegram's 64-byte callback-data limit; `.env` wording; a startup alert instead of a health endpoint; reuse of the T01a development set for tuning; and the current PC booted into Linux as a T08 host option. The global password pause was replaced by an operator alert, because it would let anyone block new sign-ins, while a leaked password exposes compute but no other user's data.
- Not verified: every runtime property the design relies on — VRAM envelope, streaming cancellation, token probabilities with images and schema — is measured in T01a.
- Open but not blocking: the Linux verification host for T08, where the current PC booted into Linux qualifies; the customer's workload and SLA, deferred by the developer.
- The `AGENTS.md` rule, the skill-setup bullet below, and `docs/learning/` belong to a separate session and were not changed.

## Prepared

- 32 requirements with sources; six rounds of direct developer answers and the S-10/S-11 decisions are preserved in [SOURCES](docs/requirements/SOURCES.md).
- User flows, contracts, data model, state machine, security, operating parameters, and acceptance criteria.
- Five ADRs: local processing; Python/aiogram/PostgreSQL and Telegram; direct Qwen3-VL-4B Q4_K_M through llama.cpp; verification layer; runtime supervision and packaging.
- [Roadmap](docs/planning/ROADMAP.md) and [eight individual specifications](specs/README.md) with dependencies and checks.
- The empty file for a copy of the task was removed; external TT.txt was not copied or changed.

## Verified

- The initial working tree was clean, on branch main. The resulting changes are limited to Markdown documentation.
- TT.txt and all four available user messages in the pinned conversation were read. Two long AI responses were truncated by the reading tool; this limitation is stated in SOURCES and does not affect the user's direct answers.
- The PC specifications were confirmed: Windows 11, Ryzen 5 5600H, 16 GiB RAM, RTX 3060 Laptop 6 GiB VRAM.
- Official sources for model/runtime options and Telegram limitations were checked; the architecture choice is distinguished from proof of quality.
- UTF-8, LF/final newline, internal links, Markdown table structure, 32 unique requirement IDs, and the presence of eight specifications were checked.
- `git diff --check` passed; new files were also checked directly. The deleted file is absent and has no remaining links.
- The SHA-256 of the original TT.txt matches the initial value: 28B3D1DD67AB7BBB783625A546930C1C2DF405F4E0420B279D3EFA4505F38179.

## Independent Review

GPT-6 Sol / high was requested for requirements analysis, official recognition options, and task drafts: regular substantive work using independent sources. The main agent checked the material against the sources and integrated the documents.

GPT-6 Astra / medium was requested for independent review of related contracts: interrelated data, cancellation, cleanup, and partial results. Four findings were identified and fixed: partial tables, immutable profile applicability, cleanup before dependencies, and the boundary for cancelling a send that has already started. A second independent review confirmed that all four had been resolved and found no new significant contradictions in the affected contracts.

The requested parameters are stated; the tool did not separately confirm the subagents' actual runtime settings. Their completion messages were verified by reading files and through checks performed by the main agent.

## Development-Assistant Setup After Planning

- Added a task-start rule to [AGENTS.md](AGENTS.md): consider applicable instructions and the available project-local/user-global skill catalog, fully read selected skill entrypoints and canonical instructions, and load supporting materials selectively. The rule avoids a manually maintained skill inventory and routine full-directory scans; it does not change discovery settings or guarantee model compliance. The ongoing teaching checklist is in [SESSION_UNDERSTANDING](docs/learning/SESSION_UNDERSTANDING.md).

- Added the project-local [session-teacher skill](.agents/skills/session-teacher/SKILL.md) from [ThariqS's gist](https://gist.github.com/ThariqS/1389dcdff9eba4789887a2211370f06b), with the original text preserved in its references. The entrypoint adds required skill metadata and adapts `AskUserQuestion` and `/goal` to Codex. It supports guided teaching with a comprehension checklist; installation does not start a lesson. Basic structure, source preservation, and links were checked; the standard validator is unavailable because PyYAML is missing, and runtime invocation remains unverified.
- Installed project-local `security-best-practices` and `security-threat-model` skills from `openai/skills` in a preceding task; their files were preserved during the routing update.
- Added the project-local [model-routing skill](.agents/skills/model-routing/SKILL.md) and updated [AI_ORCHESTRATION](docs/engineering/AI_ORCHESTRATION.md) with task-based model/effort selection, bounded reading, direct file generation, and verifiable reports. `AGENTS.md` points Codex to the skill for substantial delegation.
- The user subsequently clarified the Luna preference: `max` by default, `high` only for very elementary tasks. The policy now preserves this preference instead of lowering Luna effort for reading or mechanical work; the earlier behavioral review preceded this correction.
- Routing is advisory through existing subagent tools. No Portal, router plugin, hooks, global configuration, API dependencies, or separate telemetry system were added. Product requirements and T01–T08 remain unchanged; local Qwen suitability is still untested.
- A read-only independent behavioral review requested GPT-6 Sol / high with no inherited history. Seven scenarios covered small edits, evidence gathering, repetitive generation, concurrency/security diagnosis, GPU benchmarking, model override limitations, and savings claims. No material contradictions were found; cost wording was clarified after review. The tool did not separately confirm actual runtime model/effort.
- The standard skill validator could not run because PyYAML is absent in both available Python environments. The final checks used a separate dependency-free validator for this skill's simple frontmatter, file links, UTF-8/LF, and preservation hashes; Git whitespace checks passed. Runtime selection of the new skill and token/cost savings remain unverified.

## Claude Code Skill Parity

- Project-local Codex skills live in `.agents/skills/` and remain canonical. Claude Code loads project skills from `.claude/skills/`, so each of the four skills (`model-routing`, `security-best-practices`, `security-threat-model`, `session-teacher`) has a thin entrypoint there that duplicates only the name/description and points to the canonical file. Wrappers were chosen over symlinks because symlinks on Windows depend on developer mode and Git `core.symlinks`.
- Claude-specific adaptations: `session-teacher` uses `AskUserQuestion`; `model-routing` uses a separate Claude Code table in AI_ORCHESTRATION, following the user's decision: only Sonnet and Opus, no Fable. The presets are `sonnet-high`, `opus-medium`, `opus-high`, and `opus-max`, stored as roleless definitions in `.claude/agents/` because Claude Code sets effort only in a subagent definition. Sonnet `max` was allowed but not added.
- `AGENTS.md` now requires new project skills to be created in `.agents/skills/` with a Claude Code entrypoint.
- The user-level `self-learning` skill (Kulaxyz/self-learning-skills), which the user installed globally in Codex, was copied unchanged to `~/.claude/skills/self-learning/`. This is outside the repository.
- Global Codex plugins (GitHub, documents/PDF/spreadsheets/presentations, browser/Chrome/computer use, visualize, Figma MCP) are user-level and not project-specific; they were not mirrored into the repository.
- The four project skills appeared in the Claude Code skill list during the setup session. Not verified: discovery of the agent presets and the global `self-learning` skill in a new session. When a canonical skill's name or description changes, update its wrapper.

## Not Verified and Next Steps

Model suitability, accuracy, RAM/VRAM, and speed have not yet been tested. This is the scope of T01: T01a measures runtime feasibility; T01b calibrates the recognition core on the tuning set; T01c runs the sealed benchmark with the accepted criteria: 40 readable + 20 difficult + 10 negative cases, zero incorrectly accepted values/profiles, and at least 90% completeness on the readable portion. On failure, remediation stays on the current PC (ADR-0004).

There are no actual application test commands yet. Compatibility of exact dependencies/the lockfile is checked in T01b/T02; the end-to-end product in T06/T07; Windows (native) and Linux x86-64/NVIDIA (container, on a native Linux host still to be provided) in T08. The customer's specific server and workload have deliberately been deferred.

No commits, pushes, external submissions, publication, or deployment were carried out in this task. Implementation must not start automatically because planning is complete: a separate development task is required.
