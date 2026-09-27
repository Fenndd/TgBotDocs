# Telegram Bot for Extracting Data from Documents

Stage: planning is complete; the next step is implementation of T01. The bot receives documents in Telegram and returns only the data requested in the user's personal text settings. The first version accepts arbitrary documents in any languages, with an honest refusal when they cannot be read; processing is local. The completed product is intended to be delivered to the customer.

The selected stack is Python + aiogram + PostgreSQL and a direct local Qwen3-VL-4B-Instruct Q4_K_M through llama.cpp. The next task is [T01: testing recognition on the current PC](specs/T01-recognition-baseline.md). No source code, dependencies, or infrastructure are being created in this session; model quality has not yet been tested.

## Navigation

| Document | Purpose |
| --- | --- |
| [STATUS.md](STATUS.md) | Current state, checks, and next step |
| [PLAN.md](PLAN.md) | Sequence of alignments and criterion for completing planning |
| [Requirements](docs/requirements/PRODUCT_SPEC.md) | Requirements, sources, and draft acceptance criteria |
| [Sources](docs/requirements/SOURCES.md) | Requirement provenance and boundaries of available context |
| [Open Questions](docs/requirements/OPEN_QUESTIONS.md) | Options, recommendations, and user decisions |
| [Architecture](docs/architecture/ARCHITECTURE.md) | Agreed boundaries, components, and technical decisions |
| [Contracts](docs/architecture/CONTRACTS.md), [data](docs/architecture/DATA_MODEL.md) | Profiles, pages, fields/lists, states, persistent and temporary data |
| [Decisions](docs/decisions/README.md) | ADRs: rationale, options, and consequences |
| [Security](docs/security/SECURITY.md) | Data processing and storage boundaries |
| [Verification](docs/testing/TEST_STRATEGY.md) | Acceptance scenarios and quality checks |
| [Acceptance criteria](docs/testing/ACCEPTANCE_PLAN.md), [operations](docs/operations/OPERATIONS.md) | Test set, measurements, queue, timers, and cleanup |
| [Roadmap](docs/planning/ROADMAP.md) | Stages and dependencies |
| [Task specifications](specs/README.md) | Individual tasks for subsequent development |

## Working in the Repository

- [AGENTS.md](AGENTS.md) contains the general rules; [CLAUDE.md](CLAUDE.md) and [GEMINI.md](GEMINI.md) connect them to the corresponding tools.
- [Workflow](docs/engineering/DEVELOPMENT_WORKFLOW.md) covers task execution, verification, and handoff.
- [Delegation](docs/engineering/AI_ORCHESTRATION.md) covers subtask selection and subagent parameters.
- [Preparation history](docs/engineering/SETUP_NOTES.md) explains the rationale for the initial structure.

Documentation is maintained in English. There are no application install, build, or test commands yet. The original idea remains in the provided file outside the repository; a full copy is not transferred into the project.
