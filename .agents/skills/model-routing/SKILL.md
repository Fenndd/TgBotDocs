---
name: model-routing
description: Choose models and bounded context handoffs for substantial subagent work in this repository, including bulk reading and repetitive file generation. Use when delegation is justified; keep small sequential tasks in the main session.
---

# Project Model Routing

Read the shared [orchestration policy](../../../docs/engineering/AI_ORCHESTRATION.md) before selecting a subagent. That document owns the model preferences, project constraints, handoff modes, and reporting requirements; do not copy them into client-specific profiles.

Choose whether to delegate, then choose the model and effort using reasoning difficulty, context/output volume, risk, and verification cost. Apply the current tool's supported parameters and context-fork rules. This skill provides instructions, not an automatic model switch or enforced router.

Give the worker a concrete question or result, minimal source pointers, read-only or exact editing boundaries, and observable completion criteria. Prefer compact evidence for reading tasks and direct changes to assigned files for writing tasks. Verify the relevant original sources, resulting diff, and actual checks before integration. Keep the main agent responsible for product decisions and the final result.
