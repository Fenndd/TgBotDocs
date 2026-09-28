# Work Status

Updated: 2026-09-28 (Claude Code continuation).

## Current Stage

**T04–T07 local work is implemented and verified; T08 local packaging is built and reviewed but not yet integrated (see Stop Point).** The product runs end to end on this PC with `python -m tgbotdocs run --config <external .env>`: private sign-in, personal profiles, single file / album / Several pages intake, recognition with the frozen T01b core, profile choice or in-job instruction with preview, English delivery, cancellation, expiry, restart handling, dependency health and operator alerts. **No real Telegram request has been made**; the final real-Telegram E2E is done jointly with the developer (S-14-A5). Recognition quality is **not accepted**: the single sealed T01c/T07 benchmark is deferred until after that E2E (S-14). Native Linux verification is not possible on this PC. The frozen configuration `C:\Users\nikit\TgBotDocsData\dev\frozen\frozen-t01b.json` (SHA-256 `dd1d01a0…633f6`) still matches the checkout (`environment_mismatches` empty).

## Stop Point (2026-09-28, stopped at the developer's request)

Work was stopped completely on the developer's instruction after finishing the running subtasks. Nothing is running: no bot, llama-server, test or agent process remains; the development PostgreSQL cluster is running on 127.0.0.1:55432 as before. Nothing was pushed.

- `main` is clean at the commit that records this stop point. Verified at `dbd1f1d`: complete suite with real PostgreSQL **492 passed, 1 skipped** (156.4 s); Ruff passed.
- Commits after the T04–T06 record: `b0fd7af` compiler descriptions come from the instruction (real-model T03 check still verified; previews now say e.g. "Applies to: Invoices"); `db2b99e` idle signed-out actors are released and remembered update IDs are bounded; `1fc5cdd` content-free `job_finished` log line per job; `dbd1f1d` T07 local resilience/leak/resource checks ([T07 local report](docs/testing/T07_LOCAL_REPORT.md)): runtime crash and database outage recovered, no leaks, peak bot 246 MiB / llama-server 3,054 MiB RSS / device GPU 4,965 MiB. A 3,000-example model-based run also passed.
- **T07 local checks: done** (quality benchmark deferred as before).
- **T08 local preparation: built and reviewed, NOT integrated into `main`.** Four agent branches, each with one commit on top of `61861c2`, live in locked worktrees under `.claude/worktrees/`:
  - `worktree-wf_7df708dc-4a9-1` `3fc0a9a`: `deploy/windows/*.ps1` (scheduled task via S4U, PostgreSQL service, artifact verification; dry-run by default, nothing registered) and `docs/operations/INSTALL_WINDOWS.md`.
  - `worktree-wf_7df708dc-4a9-2` `5c9ad5d`: `deploy/linux/Dockerfile`, `compose.yaml`, `tgbotdocs.env.example`, `.dockerignore`, `docs/operations/INSTALL_LINUX.md` (compose syntax validated with a user-level Docker CLI; nothing built or run).
  - `worktree-wf_7df708dc-4a9-3` `7e2e509`: `docs/operations/USER_GUIDE.md`, `RUNBOOK.md`, `CONFIGURATION.md`, `THIRD_PARTY_NOTICES.md`.
  - `worktree-wf_7df708dc-4a9-4` `e8af09b`: `scripts/backup-postgres.ps1` and `docs/operations/BACKUP_RESTORE.md` (Backup/Verify/Restore verified on the dev cluster with synthetic data).
- The independent T08 reviews found issues that must be fixed during integration. Two are P1, both in the Windows package: Task Scheduler's restart-on-failure probably does not fire when the bot exits with a nonzero code, and the recommended layout under the drive root needs ACL hardening. The P2 issues are: the Windows task stop may not end the Python child; `.env.example` holds personal paths; the Linux compose build has no pinned image argument; the application image is not pinned by digest; a wrong alert-order claim; RUNBOOK startup-refusal and temp-root guidance; the network footprint is missing; and the backup script is hard-wired to the dev layout. The remainder is P3 wording and link work. The full agent results, checks and review findings are saved outside Git in `C:\Users\nikit\TgBotDocsData\handoff\t08-workflow-result.json`.

**Resume from here:**

1. Cherry-pick the four T08 commits onto `main` in this order: backup, windows, linux, docs. Fix the review findings in the handoff file. Link the new documents from OPERATIONS/README. Write the T08 report, run the full suite, and commit. Then remove the four worktrees and their branches.
2. Final whole-product review and fixes; prepare the exact local configuration and launch instructions for the joint test.
3. Joint real-Telegram E2E with the developer; then the deferred single sealed T01c/T07 benchmark; native Linux verification.

## Claude Code Session (2026-09-28)

Starting point: `main` at `0c7d717`, the only branch and worktree, 20 commits ahead of `origin/main`, with the untracked T04 collector (`application/documents.py`, `tests/application/test_documents.py`) whose manual-album patch was unverified. The Codex usage-checkpoint stop point, its heartbeat and the five-hour guard (S-16) belonged to the Codex session; this session continued under the developer's direct instruction to complete the product within the existing constraints (S-17).

Logical commits in this session (each verified before commit; none pushed):

- `b2fca69` T04 collector with the album-in-Several-pages rules; an independent review confirmed eight findings, all fixed with regressions ([T04 report](docs/testing/T04_PROGRESS_REPORT.md)).
- `1a45586` T05 seams: one cumulative processing budget across recognition phases, GPU queue wait removed from all trace durations including V2, global document-aware render-quota reservations ([T05 report](docs/testing/T05_PROGRESS_REPORT.md)).
- `d9c08d9` T06 job dialogue and delivery; an independent review confirmed three defects and six test gaps, all fixed; Hypothesis model-based invariants ([T06 report](docs/testing/T06_PROGRESS_REPORT.md)).
- `9f55ebd` `run` command with long polling, dependency health, operator alerts, log rotation, the Linux runtime-executable seam, and the local real-model product check.

Verified: complete suite with real PostgreSQL **490 passed, 1 skipped** (184.6 s); Ruff passed. `scripts/check-product-local.py --config C:\Users\nikit\TgBotDocsData\foundation-check.env` passed against the real frozen CUDA runtime and PostgreSQL with a controlled Bot API session and zero Telegram requests: Settings profile creation, a synthetic invoice through the file (10.3 s) and photo (8.2 s) paths with exact values, and an in-job profile creation for a second document type; no job directory or reservation left. This is functional evidence, not quality acceptance.

Independent reviews used the Claude Code `opus-high` preset (three reviewers plus adversarial verifiers per review); the tool did not expose actual runtime settings. Run tests with `--basetemp=C:/Users/nikit/TgBotDocsData/pytest-basetemp`: the default pytest temporary directory is under AppData, which the configuration deliberately rejects. Real PostgreSQL tests need `TGBOTDOCS_TEST_DATABASE_CREDENTIALS=C:/Users/nikit/TgBotDocsData/postgresql-dev-credentials.json`.

## Next Steps (in order)

See **Resume from here** in the Stop Point above; T07 local checks are complete.

## Open Points for the Developer

- **Linux runtime executable.** The frozen configuration pins the Windows `llama-server.exe` of build b11221. The Linux image necessarily contains a different executable of the same build. The application accepts it only through an explicit `RUNTIME_EXECUTABLE` plus pinned `RUNTIME_EXECUTABLE_SHA256` and alerts at startup that it is not the calibrated executable. Whether the Windows calibration and benchmark transfer to Linux, or Linux needs its own benchmark run, is the developer's decision (proposal ED-017).
- **WSL2/Docker on this PC.** Both require administrator rights, enabling Windows virtualization features and a reboot; this session is not elevated and does not change system settings. Under ED-008 WSL2 would only provide an early smoke test; final Linux verification needs a native Linux host.
- **Compiler description placeholder.** In the real run the instruction compiler once copied the example description "Applicable documents" into a draft; the preview shows it and the user can edit it. A prompt improvement needs its own real-model check.

## Earlier Evidence (Codex sessions, 2026-09-28)

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
