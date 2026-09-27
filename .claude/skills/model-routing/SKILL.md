---
name: model-routing
description: Choose models and bounded context handoffs for substantial subagent work in this repository, including bulk reading and repetitive file generation. Use when delegation is justified; keep small sequential tasks in the main session.
---

# Project Model Routing (Claude Code entrypoint)

The canonical skill is shared with Codex. Read [.agents/skills/model-routing/SKILL.md](../../../.agents/skills/model-routing/SKILL.md) and the shared [orchestration policy](../../../docs/engineering/AI_ORCHESTRATION.md), then follow them.

Claude Code adaptation: use the "Choosing a Model in Claude Code" table in that policy, not the Codex table. Only Sonnet and Opus are recommended; never use Fable. Launch the matching roleless preset from `.claude/agents/` (`sonnet-high`, `opus-medium`, `opus-high`, `opus-max`) as the agent type without passing `model`, because effort can only be set in the preset. Session tool rules, including when subagents may be spawned, take precedence.
