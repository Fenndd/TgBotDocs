# Workflow

## From Request to Result

1. Define the result of the current task and its verification criteria. Read the relevant materials and check the Git state.
2. Separate confirmed facts from proposals. Clarify uncertainties that affect product behavior or significant costs; explicitly label other assumptions.
3. Make a short plan for complex work. Create a detailed specification in [specs/](../../specs/README.md) if it helps align and verify the task.
4. Make coherent changes in small increments. Preserve other people's changes and account for changes made in parallel.
5. Verify the result against the task criteria and review the final diff. Fix any issues found, then repeat the affected checks.
6. Update documents whose facts have changed and, if needed, [STATUS.md](../../STATUS.md). Report the result and its practical limitations.

This workflow does not require separate approval for every local action. Significant product decisions and actions beyond the granted authorization require user involvement.

## Sources and Decisions

- Preserve source material without paraphrasing. Link later clarifications to the requirements without rewriting the original after the fact.
- Requirements, specifications, and ADRs have an explicit status. An agent's proposal does not automatically become an accepted decision.
- Support significant technical decisions with options, reasoning, consequences, and sources. Use the [decision log](../decisions/README.md) for this.
- If documents conflict with the user's current request, clearly state the discrepancy and update related records within the scope of the task.

## Checks and Review

First run checks directly related to the change. Expand the set if shared contracts or integrations are affected, or if significant risk remains. When required checks become available in the project, run them all.

When fixing a bug, where possible confirm the original failure and that it no longer occurs after the change. A test should check expected behavior, not reproduce the implementation text. Verify small documentation changes by checking content, links, and the diff; do not create a test environment for them.

Independent review is useful for significant or risky changes: provide the requirements, task boundaries, diff, and check results. The reviewer first analyzes the result without editing it. A finding must identify the affected location, evidence of the problem, its consequences, and a proposed fix. Do not create findings just to increase their number. If there was no independent review, do not call a self-review independent.

A task is complete when its criteria have been met, applicable checks have passed, and related documents reflect the result. Any unchecked item remains an explicit limitation; do not record it as successful.

## Context, Limits, and Handoff

Store durable information in documents and Git, not only in chat history. Before continuing, compare `STATUS.md` with the actual files: the status may be outdated. Read only relevant sections, use search, and limit log output.

After finishing a task, you may start a new session; this is not required after every edit. When handing off unfinished work, record in `STATUS.md` what is done, remaining work, obstacles, check information, and the next concrete step. Refer to existing materials instead of repeating the entire history.

`PLAN.md` answers “what is ahead”; `STATUS.md` answers “what is happening now.” Git preserves change history, and ADRs preserve the rationale for significant decisions. Do not maintain several identical logs in parallel. When a commit is authorized, group one logical task with the required checks and documentation.

## Report

Briefly state what was achieved; which files changed and why; which checks were run and with what result; and what was not checked or remains unresolved. Add rationale and consequences for a significant decision. For delegation, use the format in [AI_ORCHESTRATION.md](AI_ORCHESTRATION.md).

Empty sections, a full command log, and a retelling of internal reasoning are not required. Verifiable facts that let someone assess the result and continue working are enough.

## Additional Instructions and Skills

Keep general, persistent rules in [AGENTS.md](../../AGENTS.md). Store detailed processes understandable to people in `docs/engineering/` and read them as needed for each task.

Add a skill when there is a useful repeatable process. Place tool-specific instructions, commands, and settings in a location supported by that tool after checking the current documentation. Do not independently copy a shared process for each AI: an adapter should refer to a single document.

Do not create skill directories, agent roles, MCP, hooks, or permission settings in advance without a specific need. Do not move rules from a personal environment into the repository as mandatory rules for everyone.
