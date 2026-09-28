# Work Status

Updated: 2026-09-28.

## Current Stage

**T01b is calibrated and frozen; T02/T03 are verified locally and T04 implementation is active.** The developer's 22-case reviewed manifest was calibrated successfully. `runner freeze --auto` selected point 127 and wrote `C:\Users\nikit\TgBotDocsData\dev\frozen\frozen-t01b.json` (SHA-256 `dd1d01a0e8ff878a60b7b4bf61b6bcb20939cd5bd5695bed4eaa79a55ea633f6`). See [T01b calibration report](docs/testing/T01B_CALIBRATION_REPORT.md). Under the developer's 2026-09-28 decision (S-14), T01c preparation and the sealed run are deferred until the complete product is available in Telegram; T02 proceeds after T01b freeze. The benchmark remains mandatory and **recognition quality is not accepted**. Real-Telegram E2E and native Linux verification have not been performed.

## Stop Point (2026-09-28, automatic continuation active)

- Done: the developer (Nikita) reviewed the tuning set at 01:41; `review-apply` wrote `C:\Users\nikit\TgBotDocsData\corpora\t01b-tuning-review-v3\reviewed-manifest.json` (sha256 `022fd0b2…`): 22 verified, tune-17/tune-22/tune-23 rejected and excluded, no calibration eligibility blockers.
- Done: the completed calibration report at `C:\Users\nikit\TgBotDocsData\dev\measurements\t01b-calibration.json` was found and reused. Calibration eligibility passed; no environment change during collection. Automatic freeze succeeded without an override: 85 accepted values and 16 automatic profiles, zero errors; readable completeness 68/75. Current recognition identity still matches after adding application dependencies.
- Done: T02 Windows foundation: PostgreSQL 18.6 on loopback port 55432, real migrations and owner-isolated storage, per-call fair scheduling, supervised child processes, owned temporary cleanup/recovery, and a controlled Telegram walking path. See [T02 report](docs/testing/T02_FOUNDATION_REPORT.md). The native runtime startup check and controlled real-model synthetic image check passed. No real Telegram request was made.
- Done: T03 access and personal profile settings are connected to the production per-user actor. Real local-model semantic checks and an actor-to-PostgreSQL check passed; see [T03 report](docs/testing/T03_PROGRESS_REPORT.md). The document flow and Settings overlap are integrated in T04–T06. Work remains on `main`; recognition configuration/source are unchanged.
- Local verification configuration is outside Git at `C:\Users\nikit\TgBotDocsData\foundation-check.env`; it contains a synthetic Telegram token/password. PostgreSQL credentials are in `C:\Users\nikit\TgBotDocsData\postgresql-dev-credentials.json`. Do not print either file. PostgreSQL binaries and the cluster are under the same data root; [local setup commands](docs/operations/POSTGRESQL_DEVELOPMENT.md) start/stop them.
- Resumed: the heartbeat arrived at 04:51:46 UTC (06:51:46 Bratislava), after the previous pause at 94% usage. The allowance check showed 0% used/100% remaining. Development resumed under the explicit continuation instruction. PostgreSQL remains available locally. The goal is unfinished; the goal-status tool still reports the earlier paused metadata and has no resume action, so this direct scheduled instruction and this Stop Point record the actual active continuation.
- Latest verified local commits include `1bbe8a0` (controlled Telegram walking path and T02 evidence) and `f8a0b7d` (per-user password guard). Earlier logical commits cover T01b freeze/acceptance deferral, locked dependencies, migrated storage, scheduler, lifecycle and startup supervision. No push was performed in this continuation.
- Verified: the final compiler separately checks computation requests and inventories every type/field/list, then constrains drafts to that inventory. Actual CUDA checks passed for supported two-type/list/date, unsupported nested/calculation, and already printed total/average with a calculation prohibition. The independent final compiler review found no confirmed P1/P2; 41 compiler checks passed. Human review of the complete preview remains required.
- Verified: `scripts/check-profile-dialogue.py --config C:\Users\nikit\TgBotDocsData\foundation-check.env` passed with two profiles, one list, three unsupported-request questions and zero Telegram calls. Real PostgreSQL confirmed atomic Save, equal readback, repeat-confirmation idempotence and explicit deletion to zero synthetic-owner rows. All runtime contexts exited. The combined application/storage suite passed **120 tests in 17.20 seconds**; Ruff and Git whitespace checks passed; frozen environment mismatches are empty.
- In progress: T04 resource intake and collection flow. Implement bounded streaming downloads, content validation in supervised children, complete ordered page sets, admission from frozen per-kind p5 times, collection/late-album/cancel/expiry rules. T05 connects the recognition pipeline; T06 completes document questions, deferred Settings overlap and delivery. Current CLI has `check` only; production `run` is not yet implemented. No real Telegram call is permitted during autonomous work.

## Unattended Continuation and Usage Limit

The developer is away and authorized independent continuation, installation of necessary local dependencies, and small verified commits with descriptive bodies. Record developer-only decisions as deferred and continue independent work. Check the five-hour account window after substantial results and approximately every ten minutes. When remaining allowance is below 10%, finish or stop background work safely, commit verified results, record exact unfinished files/checks here, and stop all development until reset.

The heartbeat `tgbotdocs-resume-after-usage-reset` resumed this same conversation after the previous reset. It is now rearmed once for **2026-09-28 11:53:53 Europe/Bratislava** (09:53:53 UTC), two minutes after the current reset at 11:51:53. The PC and Codex app must remain running. At wake-up, check allowance before resuming; if still below 10%, move the same heartbeat to the next reset plus two minutes and stop again. Do not spend forced-reset credits. Remove the heartbeat when the goal is complete.

## Next Steps (in order)

1. **Assistant:** complete T04, then T05–T08 in order with logical local commits. Use controlled Telegram substitutes; do not send real Telegram messages, push, deploy, or change external resources.
2. **Assistant:** independently review the whole product, fix confirmed findings, rerun affected checks, and provide exact local token/password configuration and launch instructions.
3. **Developer and assistant together:** configure the real bot and perform the final Telegram E2E. Real Telegram checks remain pending until then.
4. **Deferred required acceptance:** prepare, independently review, seal, and run T01c once against the frozen configuration when the complete product is available in Telegram; follow [T01_PROCEDURE](docs/testing/T01_PROCEDURE.md). Do not claim quality acceptance before it passes. Native Linux x86-64/NVIDIA verification is not performed on this Windows PC.

## Continuing in Codex

Work on `main` in `C:\CodeProj\TgBotDocs\TgBotDocs`; it is the only branch and the only worktree. The earlier Codex and subagent worktrees and branches were removed on 2026-09-28 at the developer's request, after checking that every commit and file in them was already on `main`. Use the data paths from the table in [T01_PROCEDURE](docs/testing/T01_PROCEDURE.md) (`C:\Users\nikit\TgBotDocsData\...`); never `%LOCALAPPDATA%`, which both Codex and Claude virtualize. The earlier pause before tuning review is resolved: calibration and freeze are complete. Resume from the current Stop Point above.

## Evidence (2026-09-28)

- Branch `main` in `C:\CodeProj\TgBotDocs\TgBotDocs`, pushed to `origin/main` (GitHub `Fenndd/TgBotDocs`) on 2026-09-28 at the developer's request. `python -m uv sync --locked`, then `.venv\Scripts\python.exe -m pytest -q` passes 293 tests (1 opt-in skip), including an end-to-end test of the whole T01 tooling chain (review-apply, calibration, freeze, ingest, seal, one benchmark run; fake model), and `.venv\Scripts\python.exe -m ruff check src tests` passes.
- Parallel packages (core trace/runner/freeze, metrics, tuning review tooling, benchmark preparation) were implemented by subagents in isolated worktrees (Claude Code presets `opus-high`/`opus-medium`) and each was independently reviewed by another agent; every confirmed finding was fixed with a regression test before integration. The requested presets are recorded; the tool did not expose actual runtime settings. Their commits were integrated by cherry-pick; the temporary worktrees and branches no longer exist.
- Development diagnostics on the unreviewed tuning set with the full runner (`t01b-diagnostics-t01b-3.json` in the data root's `measurements`, content-free), prompt version t01b-3: 24 cases completed and the encrypted PDF was correctly refused; no wrong automatic profile at any margin; the best zero-error point (V1 ≥ 0.7 with the V2 alternate view) accepted 90 values with 0 incorrect and readable completeness 0.907; V1 alone reaches zero errors at 0.95 with 0.867. Case wall time p50 11.6 s, p95 21.4 s including V2 calls; sampled device GPU memory peak 5,083 MiB. The report carries `environment_changed_during_run` because non-behavioral commits (runtime PID, entry points) landed during the run. **This is not calibration:** the ground truth is unreviewed, and these numbers must not be reported as quality results.
- An earlier diagnostic with prompt t01b-2 showed four confidently wrong automatic profiles (index probability 0.94–1.0) that no margin withheld; the t01b-3 matching prompt (ED-015) was developed on the tuning set to fix this. Remaining known model weaknesses: Arabic readings (added diacritics or misread words) and one Devanagari vowel sign, withheld by V1/V2 at the zero-error point; a two-sided card with conflicting IDs returns `uncertain` instead of the drafted ambiguous field.

## Recovered State (2026-09-27, continuation session)

- The preceding Codex session stopped in T01b with uncommitted work in two worktrees: the uv project, model adapter, runtime supervisor, prompts, and core orchestration in `codex/local-product`, and corpus/metrics modules in `codex/t01-corpus`. Its last recorded GPU smoke on dev-01 had failed with a contract violation; the prompt fix was already in the working tree. Re-running the smoke with that code completed in manual and automatic matching modes with 10/10 exact accepted values and all renders removed (technical diagnostic only).
- That work is committed on `codex/local-product` (`0e648de`, `e2d0b35`, `361a198`); `main` contains it. The other Codex branches (`codex/recognition-contracts`, `codex/recognition-contract-fixes`, `codex/page-preparation`, `codex/t01-fixtures`, `codex/t01-corpus`) held only content already on `main` (checked by patch identity; the one set of untracked worktree files differed only by lint fixes). At the developer's request, they and their worktrees under `C:\Users\nikit\.codex\worktrees\` were removed on 2026-09-28.
- Path correction: the Codex desktop app virtualizes `%LOCALAPPDATA%`, so the artifacts the earlier status placed under `C:\Users\nikit\AppData\Local\TgBotDocs*` physically lived under `C:\Users\nikit\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\`. The Claude desktop app virtualizes `%LOCALAPPDATA%` the same way (into `...\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\`), so a data root created there was invisible to the developer's browser. **All project data now lives outside AppData, where no app redirects it:** the data root `C:\Users\nikit\TgBotDocsData\dev` (model, projector, and runtime files are hard links to the verified originals; the pinned `llama-server.exe` hash matches) and the development, tuning, and benchmark packages under `C:\Users\nikit\TgBotDocsData\corpora\` (tuning manifest hashes re-verified after the move). Never place project data under `%LOCALAPPDATA%`; the copies left in both apps' virtualized folders are obsolete.

## Earlier Development Evidence (T01a)

- The user authorized local implementation, dependencies, model downloads, tests, worktrees, and logical commits; no push, remote deployment, external inference, or final real-Telegram E2E is authorized. Linux hardware verification unavailable on this PC must remain explicitly deferred.
- Official Qwen3-VL-4B Q4_K_M/FP16 mmproj and llama.cpp b11221 CUDA 12.4 artifacts were downloaded and hash-verified; six serialized configurations, PDF renders, simulated JPEG paths, cancellation, timeout recovery, restart, context envelope, multilingual diagnostics, and localization were measured ([T01A_REPORT](docs/testing/T01A_REPORT.md)). The starting profile is GPU vision, q8_0 K/V, context 4096, image maximum 1024, PDF 150 DPI.

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
