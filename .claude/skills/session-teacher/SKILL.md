---
name: session-teacher
description: Teach the user to understand a development session step by step, with an understanding checklist, explanations of causes and design decisions, and questions that verify comprehension. Use when the user requests guided learning, a walkthrough, or a deep explanation of work in this project.
---

# Session Teacher (Claude Code entrypoint)

The canonical skill is shared with Codex. Read [.agents/skills/session-teacher/SKILL.md](../../../.agents/skills/session-teacher/SKILL.md) and follow its teaching workflow. Resolve its relative paths, such as `references/original-gist.md`, from `.agents/skills/session-teacher/`.

Claude Code adaptation: use the `AskUserQuestion` tool for multiple-choice comprehension checks when it fits, and ask open-ended questions in chat. The source's `/goal` line is a completion criterion, not a command. Installation alone does not start a teaching session or create its checklist.
