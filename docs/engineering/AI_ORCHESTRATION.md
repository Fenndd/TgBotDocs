# Working with Subagents

## When to Delegate

Use a subagent for an independent part of a task, isolation of a large context, checking a separate hypothesis, or independent review if the benefit justifies the startup and coordination costs. Simple edits and tightly dependent sequential steps should usually be handled in the main session.

Define roles and tasks for the current task. Do not create fixed profiles such as `explorer`, `worker`, `reviewer`, or similar in advance. Choose the number of agents based on useful independent tasks and environment constraints, rather than trying to use every available slot.

## Choosing a Model in Codex

Assess reasoning difficulty, context volume, risk/reversibility, and expected output volume separately. A large input or output does not by itself require a stronger reasoning model. Delegate only when the expected benefit exceeds startup, context transfer, and verification costs; first consider targeted search and reading in the main session.

The combinations below are project routing preferences, not launch settings, quality guarantees, or verified pricing rankings. Check the available models and effort values in the current session. They concern development assistants, not the local Qwen model used by the product.

| Model | Effort | Guideline |
| --- | --- | --- |
| GPT-6 Luna | max by default; high only for very elementary tasks | Bounded fact gathering, repository search, or repetitive changes with an established reference and straightforward verification |
| GPT-6 Sol | high | Bounded engineering work requiring independent reasoning: implementation, diagnosis, meaningful tests, or review |
| GPT-6 Astra | medium | Interrelated changes, architecture analysis, conflicting evidence, or implementation with significant uncertainty |
| GPT-6 Astra | high | Especially difficult or consequential analysis, including concurrency/security decisions or a demonstrated reasoning failure at a lower level |

Prefer the smallest adequate model/effort combination that can reasonably be expected to produce a reliable result, subject to the user's explicit preferences. For Luna, use `max` by default and `high` only for very elementary tasks; do not lower it to `medium` or `low` under the economy rule. Use actual pricing/usage evidence when comparing monetary costs; the table alone does not establish which combination is cheapest. Consider uncertainty, the consequences of error, the context needed, and the ability to verify. The number of files and the parent session's settings do not by themselves determine the choice.

The table guides subagent requests; it does not switch the main session's model. For models other than Luna, do not select `max` solely because a task involves large reads or mechanical work. Keep product decisions, resolution of ambiguous requirements, ownership of tightly coupled concurrency/security changes, and final integration with the main agent. A bounded independent review of such work can still be delegated to a suitable reasoning model.

If the result is uncertain or a check fails, first determine the cause: requirements, data, or access may be missing. A stronger model will not remove such obstacles on its own. Increase the model level when the analysis complexity is actually the limiting factor; do not repeat ineffective attempts indefinitely.

## Choosing a Model in Claude Code

The same criteria apply; only the model/effort set differs. Use Sonnet and Opus for subagents. Do not recommend Haiku. Do not use Fable. Delegate only as the session's tool rules allow.

| Preset | Model | Effort | Guideline |
| --- | --- | --- | --- |
| `sonnet-high` | Sonnet | high | Bounded fact gathering, repository search, or repetitive changes with an established reference and straightforward verification |
| `opus-medium` | Opus | medium | Bounded engineering work requiring independent reasoning: implementation, diagnosis, meaningful tests, or review |
| `opus-high` | Opus | high | Interrelated changes, architecture analysis, conflicting evidence, or implementation with significant uncertainty |
| `opus-max` | Opus | max | Especially difficult or consequential analysis, including concurrency/security decisions or a demonstrated reasoning failure at a lower level |

Claude Code sets effort only in a subagent definition, not per call, so each combination is a roleless preset in [.claude/agents/](../../.claude/agents/). Launch the preset by its agent type and do not pass the `model` parameter, which would override the preset's model. These presets fix only model and effort; the task brief defines the role, so they are not the fixed role profiles prohibited above. Sonnet `max` is permitted by the user but has no preset because Opus `medium` covers its expected use; add one only when a task shows the need. The table guides subagents and does not change the main session's model or effort.

## Environment Capabilities

Before launching, check which models, effort values, and context handoff methods are actually available. Set the selected parameters explicitly when the interface supports it. Do not promise that an override will be applied if the tool only inherits the parent session's settings.

If a combination is unavailable, choose an appropriate available alternative within the session's permissions and report the difference. For Claude Code, use its own table above. For Gemini, use the same task-based selection principle, without inventing model equivalencies with Codex or carrying over unsupported parameters.

This document does not enable or configure the subagent mechanism. It does not expand tool permissions, authorize external data sharing, or override active session limitations.

## Task Definition and Coordination

Give the subagent the goal, required sources, editing boundaries or read-only mode, result criteria, and expected checks. Provide enough context while avoiding unnecessary copying of the entire history.

Use a short task-specific brief instead of a full-history fork when history is not necessary. Check the interface before selecting a model: in the current collaboration interface a full-history fork inherits the parent's settings and does not accept overrides. This interface-specific limitation must be rechecked when the tools change.

For parallel edits, assign different file areas. Perform dependent changes sequentially; the main agent integrates shared files. Use a separate checkout only when isolation is genuinely needed. Do not create multiple workers for the same implementation without a reason.

The main agent checks findings, integrates the result, and is responsible for the overall verification. A subagent's “done” message alone does not confirm that the task is complete.

## Reading and Writing with Bounded Context

For context gathering, assign a concrete question and relevant paths in read-only mode. Ask for findings with file/symbol references, verified line locations where useful, contradictions, and remaining uncertainty. Do not return entire files or a generic repository summary. The main agent reads the necessary original sections before editing or accepting a significant conclusion; a summary may omit important conditions and line numbers must be checked.

For repetitive generation, provide an existing reference, the target paths, behavior criteria, and meaningful checks. Have the subagent write directly to the assigned files and return the changed paths, a short explanation, actual check results, and unresolved issues. The main agent inspects the diff and relevant implementation without requiring the full generated text in the chat. If a pattern does not exist, define it first rather than asking a worker to invent architecture. Do not create boilerplate or tests merely to exercise delegation.

These modes describe task shapes, not permanent agent roles or separate required skills. No file-size threshold forces delegation or blocks a necessary targeted read.

## Application to This Project

- T01: independent research into public runtime/model documentation and later analysis of permitted benchmark metrics can be bounded subtasks. Keep the suitability decision with the main agent. Serialize GPU measurements; parallel inference would distort the baseline.
- T02–T06: delegate independent adapter work or repetitive changes only after contracts, reference patterns, ownership, and checks are clear. Queue/cancellation, profile isolation, and temporary-data cleanup need suitable reasoning and integrated verification.
- T07–T08: independent acceptance review or platform instructions can be separate subtasks; platform readiness requires actual execution evidence.

Do not send real document images, extracted values, secrets, or private profile content to development assistants or external services. Use permitted synthetic fixtures, source code without secrets, and content-free measurements. Development routing does not alter REQ-014 or authorize Portal/cloud inference in the application.

## Scope and Evidence

The project-local [model-routing skill](../../.agents/skills/model-routing/SKILL.md) is a Codex entrypoint to this shared policy; [.claude/skills/model-routing](../../.claude/skills/model-routing/SKILL.md) is the Claude Code entrypoint to the same skill. Claude Code uses its own model table and the subagent presets in `.claude/agents/`; there is no one-to-one mapping between the Codex and Claude tables. Other clients use this document through the existing repository instructions; no global configuration is changed.

This is advisory routing through existing subagent tools. Apart from the Claude Code model/effort presets, no Portal service, custom router plugin, hook, MCP server, API dependency, or telemetry system is configured. Reconsider enforced routing only after actual repeated inefficient operations and a tested integration justify it. Codex supports [plugin hooks](https://developers.openai.com/plugins/build/plugins), but that does not establish an installed or trusted hook in this checkout.

The source idea is discussed in [Spotify's Shunt article](https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90): bounded reading and direct file generation reduce the primary agent's context. Its reported savings are specific to its benchmark, not a measured reduction in this project's total tokens, latency, or cost. A single shared policy and a small entrypoint follow [OpenAI's guidance on focused skills](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).

## Transparency

In the final report on substantial delegation, state the task, selected model and effort, a brief reason for the choice, the result, and how it was checked. If the tool does not expose the actual execution parameters, say so; do not present requested parameters as confirmed.

Include elapsed time and token usage only when the tool actually reports them. Mark unavailable metrics as unavailable; do not estimate savings from model names or present worker-only token counts as total workflow usage. Use the existing task report and `STATUS.md` for significant results rather than creating a parallel activity log.
