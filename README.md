# Project Preparation

The repository is in the preparation phase. Information about the product and the original specification has not been added. The stack, architecture, and source-code structure have not been defined.

## Entry Points

| File | Purpose |
| --- | --- |
| [STATUS.md](STATUS.md) | Current state, check results, and next step |
| [PLAN.md](PLAN.md) | Preparation sequence; later, the implementation plan |
| [AGENTS.md](AGENTS.md) | General AI instructions and pointers to relevant context |
| [CLAUDE.md](CLAUDE.md), [GEMINI.md](GEMINI.md) | Connect the shared instructions to other tools |
| [DEVELOPMENT_WORKFLOW.md](docs/engineering/DEVELOPMENT_WORKFLOW.md) | Workflow, checks, reporting, and context handoff |
| [AI_ORCHESTRATION.md](docs/engineering/AI_ORCHESTRATION.md) | When to delegate and how to choose a subagent model |
| [SETUP_NOTES.md](docs/engineering/SETUP_NOTES.md) | Rationale for the initial structure and deferred settings |

## Documentation

| Location | What to store here |
| --- | --- |
| [ORIGINAL_BRIEF.md](docs/requirements/ORIGINAL_BRIEF.md) | Original specification without paraphrasing or editorial additions; the file is currently empty |
| [PRODUCT_SPEC.md](docs/requirements/PRODUCT_SPEC.md) | Verified requirements and acceptance criteria |
| [OPEN_QUESTIONS.md](docs/requirements/OPEN_QUESTIONS.md) | Questions and assumptions requiring a decision |
| [ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) | Architecture description after it is defined |
| [docs/decisions/](docs/decisions/README.md) | Significant decisions: options, rationale, and consequences |
| [SECURITY.md](docs/security/SECURITY.md) | Product security requirements after specification analysis |
| [TEST_STRATEGY.md](docs/testing/TEST_STRATEGY.md) | Product verification strategy after requirements are defined |
| [specs/](specs/README.md) | Specifications for individual tasks as needed |

Short templates indicate places for future information, not accepted decisions. Documentation is expanded based on facts; unknowns are not filled in with guesses.

## Getting Started

The first substantive step is to obtain the original specification and save it to `docs/requirements/ORIGINAL_BRIEF.md`. If the original is provided in another format, preserve the source file alongside it and list it in this documentation map. Then analyze the requirements according to the [plan](PLAN.md).

There are no installation, run, build, or test commands yet. Add them after choosing the stack and verifying the environment.
