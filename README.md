# Telegram Bot for Extracting Data from Documents

Stage: T01 implementation is active. [T01a runtime feasibility](docs/testing/T01A_REPORT.md) meets the technical condition to implement T01b; quality acceptance and the finished bot remain incomplete. The intended bot receives documents in Telegram and returns only the data requested in the user's personal text settings. The first version accepts arbitrary documents in any languages, with an honest refusal when they cannot be read; processing is local and must fit the current PC's hardware.

The selected stack is Python + aiogram + PostgreSQL and direct local Qwen3-VL-4B-Instruct Q4_K_M through llama.cpp. Current experimental commands and their limitations are recorded in the [T01a report](docs/testing/T01A_REPORT.md). T01b is calibrated and frozen on 22 reviewed cases, and T02 is active. Recognition quality is not accepted yet. Defer benchmark preparation and the single sealed integrated run shared by T01c and T07 until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer. Local T07 resilience checks and T08 preparation may proceed first; they do not complete acceptance.

## Navigation

| Document | Purpose |
| --- | --- |
| [STATUS.md](STATUS.md) | Current state, checks, and next step |
| [PLAN.md](PLAN.md) | Sequence of alignments and criterion for completing planning |
| [Requirements](docs/requirements/PRODUCT_SPEC.md) | Requirements, sources, and draft acceptance criteria |
| [Sources](docs/requirements/SOURCES.md) | Requirement provenance and boundaries of available context |
| [Open Questions](docs/requirements/OPEN_QUESTIONS.md) | Options, recommendations, and user decisions |
| [Architecture](docs/architecture/ARCHITECTURE.md) | Agreed boundaries, components, and technical decisions |
| [Contracts](docs/architecture/CONTRACTS.md), [data](docs/architecture/DATA_MODEL.md), [state machine](docs/architecture/STATE_MACHINE.md) | Profiles, pages, fields/lists, merging, persistent and temporary data, dialogue and job states, timers, scheduling |
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

Documentation is maintained in English. Exploratory tooling exists under `tools/t01`; it is not a finished bot or product installer. The original idea remains in the provided file outside the repository; a full copy is not transferred into the project.
