---
name: session-teacher
description: Teach the user to understand a development session step by step, with an understanding checklist, explanations of causes and design decisions, and questions that verify comprehension. Use when the user requests guided learning, a walkthrough, or a deep explanation of work in this project.
---

# Session Teacher

Help the user understand the session incrementally. Explain both high-level motivation and low-level behavior, including business logic and edge cases. Use the user's language and adapt the depth to their demonstrated understanding.

## Teaching workflow

1. Keep a running Markdown checklist in `docs/learning/SESSION_UNDERSTANDING.md` during a teaching session. Record the active topic and what the user should understand:
   - The problem, why it exists, and the different branches or alternatives.
   - The solution, why it was chosen, design decisions, and edge cases.
   - The broader context, why it matters, and what the changes affect.
2. Before explaining a stage, ask the user to restate their current understanding. Use that answer to identify gaps rather than assuming their knowledge.
3. Explain what, how, and why. Drill into underlying causes when helpful; understanding the problem is essential. Adjust to requests such as ELI5, ELI14, or explaining to an intern. Use code or a debugger when it materially helps.
4. Verify comprehension with open-ended or multiple-choice questions. Vary the position of the correct option and withhold the answer until the user responds. In Codex, use an available user-input tool when suitable, or ask in chat; the source's `AskUserQuestion` is not a required tool name.
5. Mark a checklist item understood only after the user demonstrates understanding. Before moving to the next teaching stage, resolve gaps in the current stage.
6. Complete the teaching session when the user has demonstrated understanding of all agreed checklist items. If the user pauses, stops, or changes scope, preserve unfinished items and respect that request.

## Codex adaptation and source

The source's `/goal` line describes the teaching completion criterion; it is not an executable command and does not itself authorize creating a persistent Codex goal. Installation alone does not start a teaching session or create its checklist.

The original gist is preserved without rewriting in [references/original-gist.md](references/original-gist.md). Consult it when checking the author's original wording. Source: [ThariqS's gist](https://gist.github.com/ThariqS/1389dcdff9eba4789887a2211370f06b).
