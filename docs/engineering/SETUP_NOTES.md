# Rationale for the Initial Structure

Prepared 2026-09-27. The analysis is based on all five message exchanges in the provided discussion “Using AI in Development.” AI responses were considered proposals. References to the product from the discussion were not carried over: the current task is limited to preparation without product information.

## What Was Accepted and Why

- The short `AGENTS.md` contains general rules and conditional pointers to context. Large processes are read as needed for each task. This reduces repeated instructions and follows [OpenAI's recommendation for compact context](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).
- `AGENTS.md` is at the root, in accordance with [Codex's instruction discovery mechanism](https://learn.chatgpt.com/docs/agent-configuration/agents-md). `CLAUDE.md` and `GEMINI.md` only import the shared file so the rules do not diverge.
- The imports were checked against the [Claude Code documentation](https://code.claude.com/docs/en/memory) and the [Gemini CLI documentation](https://geminicli.com/docs/cli/gemini-md/). Modern Claude Code also supports reading `AGENTS.md` directly under certain conditions; the short import was retained for explicit inclusion and compatibility. Actual loading in local Claude/Gemini sessions was not checked here.
- `docs/` is the chosen documentation convention, not a required AI standard. `specs/` separates the details of individual tasks from general requirements. The folders are retained in Git by substantive files, so `.gitkeep` is not needed.
- `PLAN.md` and `STATUS.md` separate future actions from the current state. ADRs are for significant decisions, not a log of every action.
- The subagent policy keeps model and effort selection flexible. It does not create fixed roles, change environment settings, or guarantee that any client supports the parameters.

## What Was Left Blank

During the initial preparation, the original task had not yet been provided, and the product documents were templates. This is a historical state, not the current status.

On 2026-09-27, the user provided the external `TT.txt` and the pinned discussion. At the user's direct instruction, the empty file for a copy of the source was removed; the task text is not transferred into the repository. Links and the rationale are in [SOURCES.md](../requirements/SOURCES.md), and the current stage is in [STATUS.md](../../STATUS.md). Requirements, architecture, security, and verification are now being clarified together with the developer.

## What Was Deferred

- Implementation directories, test projects, dependency manifests, lockfiles, CI, and the environment — until a stack is selected and a task to set them up is defined.
- Codex/Claude/Gemini configuration, skills, hooks, MCP, and roles — until there is a specific need and the capabilities of the version in use have been checked.
- A traceability table mapping all requirements to code and tests — until requirements and implementation exist. Future identifiers and links are enough for now.
- A license, publishing rules, and release documentation — until the owner decides and the relevant process exists.
- Mandatory chat switching after every task, a full test suite after every change, and a separate reviewer for every change are not being introduced. The scope of the process should match the risk of the task.

## Git Files and Formatting

Local `.env` files are listed in `.gitignore` (with an exception for an example without secrets), as are personal Claude files and operating-system metadata. Shared documents and tool settings are not ignored wholesale.

Broad patterns such as `*.key`, `*.pem`, `credentials*`, IDE directories, and artifacts for unselected stacks were not added: without context, they could hide useful files. When specific secret files or generated artifacts appear, add precise rules before adding those files to Git. `.gitignore` does not remove files already tracked and does not protect against reading them.

The existing `.gitattributes` was preserved. `.editorconfig` sets UTF-8, LF, and a final newline for non-empty files; a source-code indentation style has not been chosen. Automatic trimming of trailing whitespace in Markdown is disabled because it may indicate a line break.
