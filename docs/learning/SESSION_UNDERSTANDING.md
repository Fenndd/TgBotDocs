# Session Understanding

Active topic: Codex skill discovery, scope, automatic selection, and context use.
Date: 2026-09-27.
Status: Complete. All five checklist items were demonstrated in the user's answers; boundary clarifications are recorded below.

Items remain unchecked until the user demonstrates understanding.

- [x] Distinguish repository-local and user-global skills from model training and tools.
- [x] Explain discovery metadata versus full instructions and supporting references.
- [x] Explain implicit selection, description quality, and explicit-only invocation.
- [x] Understand the context cost of the catalog and selected instructions.
- [x] Decide when a generic AGENTS.md reminder helps and why a manual skill inventory is unnecessary.

Current evidence: this chat's supplied skill catalog contains the four project-local skills and ten user-global Engineering skills. The Engineering invocation metadata enables implicit selection. Automatic discovery is confirmed for this chat; universal selection reliability has not been established.

The user correctly explained that new skill names do not need to be listed manually in AGENTS.md and that descriptions are supplied before selection. Clarification: the discovery catalog also includes names and file paths.

At the user's request, AGENTS.md now requires considering applicable repository instructions and project-local/user-global skill metadata before task execution, reading complete selected skill instructions, and loading supporting resources selectively. No discovery settings were changed. This establishes a behavioral rule; it does not prove infallible skill selection.

The user's initial scenario answer omitted the complete SKILL.md entrypoint. In the final answer, the user correctly confirmed that the full entrypoint is read before the applicable additional scenario materials; unrelated guides can remain unread.

Supplementary topic: when subagent instructions become available. Verified chain: AGENTS.md contains the task-context delegation pointer and mandatory pre-delegation policy instruction; the model-routing skill links to docs/engineering/AI_ORCHESTRATION.md. Linked document contents require an actual read and are not automatically loaded merely because a link exists. No subagents were launched for this explanation.

The user confirmed that a link does not load its target and that the orchestration policy is read when delegation becomes relevant. Clarification: read it before choosing and launching the subagent. This supplementary topic is understood.

Final consolidation: the user answered all four bundled questions correctly in substance: repository versus user scope, instructions rather than retraining, complete entrypoint plus relevant guides, description-based selection and explicit-only policy, and selective loading to limit context use.

Boundary clarifications supplied at closure:

- User-global availability is scoped to the user installation and environment; it is not automatic synchronization to another host or cloud environment. A skill grants neither tools nor server access.
- allow_implicit_invocation: false disables automatic selection; it is an invocation policy, not a filesystem access restriction.
- Initial skill names, descriptions, and paths do occupy context. Full instruction bodies and relevant references are loaded separately when read.

Teaching is complete for this topic. No further comprehension questions are pending.
