# Telegram Bot for Extracting Data from Documents

Stage: the local T02–T07 product is implemented, T01b recognition is frozen, and T08 packaging/operations have undergone review remediation. The bot supports private sign-in, personal confirmed profiles, file/photo/album/Several pages intake, local recognition, type clarification, profile instructions inside a job, partial results, cancellation, expiry and restart cleanup. Current verification and remaining acceptance checks are in [STATUS](STATUS.md).

The stack is Python + aiogram + PostgreSQL with local Qwen3-VL-4B-Instruct Q4_K_M through pinned llama.cpp. Recognition quality remains **unaccepted**. The final real-Telegram E2E is performed jointly with the developer; only then prepare/review/seal the one integrated T01c/T07 benchmark. Native Linux and clean-machine Windows unattended delivery checks remain separate and unperformed. No cloud-recognition fallback is provided.

For this developer PC, follow [the exact joint-test steps](docs/operations/LOCAL_PC_JOINT_TEST.md). The private configuration is outside Git; fill its blank bot token locally before a joint start. Generic platform instructions are [Windows](docs/operations/INSTALL_WINDOWS.md) and [Linux](docs/operations/INSTALL_LINUX.md); configuration, operation, permitted backups and notices are linked below.

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
| [Configuration](docs/operations/CONFIGURATION.md), [runbook](docs/operations/RUNBOOK.md), [user guide](docs/operations/USER_GUIDE.md) | External secrets/settings, runtime operation and user dialogue |
| [Backup/restore](docs/operations/BACKUP_RESTORE.md), [third-party notices](docs/operations/THIRD_PARTY_NOTICES.md) | Permitted persistent data and delivery license boundaries |
| [Roadmap](docs/planning/ROADMAP.md) | Stages and dependencies |
| [Task specifications](specs/README.md) | Individual tasks for subsequent development |

## Working in the Repository

- [AGENTS.md](AGENTS.md) contains the general rules; [CLAUDE.md](CLAUDE.md) and [GEMINI.md](GEMINI.md) connect them to the corresponding tools.
- [Workflow](docs/engineering/DEVELOPMENT_WORKFLOW.md) covers task execution, verification, and handoff.
- [Delegation](docs/engineering/AI_ORCHESTRATION.md) covers subtask selection and subagent parameters.
- [Preparation history](docs/engineering/SETUP_NOTES.md) explains the rationale for the initial structure.

Documentation is maintained in English. Exploratory recognition tooling under `tools/t01` remains distinct from the application under `src/tgbotdocs` and platform packaging under `deploy`. The original idea remains in the provided file outside the repository; a full copy is not transferred into the project.
