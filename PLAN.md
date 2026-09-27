# Preparation for Development

Status: preparation is complete; the package was revised after the independent review of 2026-09-27, and document checks have passed. Implementation will not start in this session.

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
