# Working with Subagents

## When to Delegate

Use a subagent for an independent part of a task, isolation of a large context, checking a separate hypothesis, or independent review if the benefit justifies the startup and coordination costs. Simple edits and tightly dependent sequential steps should usually be handled in the main session.

Define roles and tasks for the current task. Do not create fixed profiles such as `explorer`, `worker`, `reviewer`, or similar in advance. Choose the number of agents based on useful independent tasks and environment constraints, rather than trying to use every available slot.

## Choosing a Model in Codex

The combinations below are preferred options from the workflow discussion. They are guidelines for selection, not launch settings, quality guarantees, or statements about pricing.

| Model | Effort | Guideline |
| --- | --- | --- |
| GPT-6 Luna | max | A limited and clear task: search, fact gathering, mechanical changes, implementation with clear criteria |
| GPT-6 Sol | high | Regular substantive engineering work: implementation, diagnosis, tests, and review that require independent decisions |
| GPT-6 Astra | medium | A complex or ambiguous task: interrelated changes, architecture analysis, conflicting evidence |
| GPT-6 Astra | high | An especially difficult or consequential task where additional analysis is likely to improve the result, including after a simpler approach fails |

Choose the least costly available combination that can reasonably be expected to produce a reliable result. Consider uncertainty, the consequences of error, the context needed, and the ability to verify. The number of files and the parent session's settings do not by themselves determine the choice.

If the result is uncertain or a check fails, first determine the cause: requirements, data, or access may be missing. A stronger model will not remove such obstacles on its own. Increase the model level when the analysis complexity is actually the limiting factor; do not repeat ineffective attempts indefinitely.

## Environment Capabilities

Before launching, check which models, effort values, and context handoff methods are actually available. Set the selected parameters explicitly when the interface supports it. Do not promise that an override will be applied if the tool only inherits the parent session's settings.

If a combination is unavailable, choose an appropriate available alternative within the session's permissions and report the difference. For Claude Code and Gemini, use the same task-based selection principle, without inventing model equivalencies with Codex or carrying over unsupported parameters.

This document does not enable or configure the subagent mechanism. It does not expand tool permissions, authorize external data sharing, or override active session limitations.

## Task Definition and Coordination

Give the subagent the goal, required sources, editing boundaries or read-only mode, result criteria, and expected checks. Provide enough context while avoiding unnecessary copying of the entire history.

For parallel edits, assign different file areas. Perform dependent changes sequentially; the main agent integrates shared files. Use a separate checkout only when isolation is genuinely needed. Do not create multiple workers for the same implementation without a reason.

The main agent checks findings, integrates the result, and is responsible for the overall verification. A subagent's “done” message alone does not confirm that the task is complete.

## Transparency

In the final report on substantial delegation, state the task, selected model and effort, a brief reason for the choice, the result, and how it was checked. If the tool does not expose the actual execution parameters, say so; do not present requested parameters as confirmed.
