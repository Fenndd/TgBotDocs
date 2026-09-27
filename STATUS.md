# Work Status

Updated: 2026-09-27.

## Current Stage

**Planning is complete.** The next stage is the specific implementation of [T01: testing direct recognition on the current PC](specs/T01-recognition-baseline.md). Subsequent development-assistant setup is recorded below; application implementation has not started.

## Prepared

- 32 requirements with sources; six rounds of direct developer answers are preserved in [SOURCES](docs/requirements/SOURCES.md).
- User flows, contracts, data model, security, operating parameters, and acceptance criteria.
- Three ADRs: local processing; Python/aiogram/PostgreSQL and Telegram; direct Qwen3-VL-4B Q4_K_M through llama.cpp.
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

Model suitability, accuracy, RAM/VRAM, and speed have not yet been tested — this is the scope of T01 with the accepted criteria: 40 readable + 20 difficult + 10 negative cases; zero incorrectly accepted values/profiles and at least 90% completeness on the readable portion.

There are no actual application test commands yet. Compatibility of exact dependencies/the lockfile is checked in T01/T02; the end-to-end product in T06/T07; Windows and Linux x86-64/NVIDIA in T08. The customer's specific server and workload have deliberately been deferred.

No commits, pushes, external submissions, publication, or deployment were carried out in this task. Implementation must not start automatically because planning is complete: a separate development task is required.
