# Development Plan

Status: implementation authorized and active; updated 2026-09-28. T01b tooling is implemented and tested; the next steps need the developer's human review and photographs. [STATUS](STATUS.md) records the current state and evidence; the [T01 procedure](docs/testing/T01_PROCEDURE.md) gives the exact commands.

## Current Execution Sequence

1. T01b (developer): review the 25-case tuning set in its review form and apply the decisions. Then (assistant): run calibration, freeze with the pre-declared rule (ED-014), and record the calibration report with risk–coverage curves and per-page times. If no zero-error point exists, follow ADR-0004's remediation order on this PC.
2. T01c (developer): generate the benchmark plan, print and photograph the 20 difficult cases, deliver the photo-path cases through Telegram, and review all 70 cases. Then (assistant): ingest, seal against the frozen configuration, run the benchmark once, and report against ACCEPTANCE_PLAN. Do not begin T02 before it passes.
3. T02 through T08: follow the existing [roadmap](docs/planning/ROADMAP.md) and specifications, with logically complete verified local commits and a separate final quality pass.
4. Defer final real-Telegram E2E and remote deployment per the user's current instruction. Record unavailable native Linux verification honestly; do not substitute Windows or WSL evidence.

The rest of this file records the completed planning package. Its old session exclusions do not override the current development authorization.

## Prepared Results

- [Sources](docs/requirements/SOURCES.md): TT.txt and direct clarifications are separated from previous AI ideas; the source is not copied into the project. S-10 records the developer's decision authority; S-11 the T01 escalation path.
- [Specification](docs/requirements/PRODUCT_SPEC.md) and [user flows](docs/requirements/USER_FLOWS.md): open types/languages, personal profiles, fields/lists, errors, access, and life cycle.
- [Decision register](docs/requirements/OPEN_QUESTIONS.md), [architecture](docs/architecture/ARCHITECTURE.md), and [ADRs](docs/decisions/README.md): agreed boundaries, stack, experimental recognition path, verification layer (ADR-0004), and runtime supervision and packaging (ADR-0005); engineering decisions are labeled ED.
- [Contracts](docs/architecture/CONTRACTS.md), [data](docs/architecture/DATA_MODEL.md), [state machine](docs/architecture/STATE_MACHINE.md), [security](docs/security/SECURITY.md), and [operations](docs/operations/OPERATIONS.md): the details required for implementation.
- [Acceptance](docs/testing/ACCEPTANCE_PLAN.md) and [verification strategy](docs/testing/TEST_STRATEGY.md): measurable criteria, sealed benchmark, and explicit limitations.
- [Roadmap](docs/planning/ROADMAP.md) and [eight individual tasks](specs/README.md): sequence, dependencies, results, and checks; T01 in three stages.

## Completion Condition for the Current Task

The main decisions have been aligned; the documents are consistent and checked; the next work is the specific implementation of [T01a](specs/T01-recognition-baseline.md). The actual status of checks is recorded in [STATUS.md](STATUS.md).

Untested models are not declared suitable: T01 contains criteria for continuing, the remediation order on the current PC, and the point at which scope or criteria return to the developer. Selecting test corpus materials, pinning exact dependency versions, and running on Linux are defined tasks for future development, not unresolved fundamental decisions.

Code, manifests, CI, installing models or the environment, external resources, commits, and pushes are outside the results of this session.
