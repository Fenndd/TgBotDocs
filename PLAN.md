# Development Plan

Status: implementation authorized and active; updated 2026-09-28. T01b is calibrated and frozen on 22 reviewed cases; T02's local foundation and T03's local implementation checks are verified, and T04 is active. The application/storage suite passed with actual PostgreSQL (120 tests in 17.20 seconds). See the [T03 progress report](docs/testing/T03_PROGRESS_REPORT.md), [T02 foundation report](docs/testing/T02_FOUNDATION_REPORT.md), and [STATUS](STATUS.md) for verified behavior and remaining checks.

## Current Execution Sequence

1. Continue T04–T06 in order, followed by T07 and T08, under the existing [roadmap](docs/planning/ROADMAP.md) and specifications. T02 and T03 local implementation checks are verified; T01c does not gate implementation. The [T03 progress report](docs/testing/T03_PROGRESS_REPORT.md) records the verified local results and the remaining T05/T06, Telegram, benchmark, and platform checks.
2. Perform T07's local functional, isolation, and resilience checks as the implementation becomes available. These checks may precede final real-Telegram E2E and do not constitute recognition-quality or complete-product acceptance.
3. Prepare T08 and perform available local packaging checks after T07's local checks. Keep native Linux results distinct; the current Windows PC does not verify that platform.
4. After the complete product is available through Telegram, perform the final real-Telegram E2E jointly with the developer, then prepare, review, seal, and run the single 70-case integrated benchmark for both T01c and T07. The benchmark remains required acceptance; T01b freeze does not accept recognition quality. Do not schedule a second sealed run for T07.
5. Remote deployment remains deferred. Follow the benchmark ledger and record unperformed checks honestly.

While the developer is absent, continue independent work and defer developer-only decisions. Make small logical changes, verify each unit before committing, and follow the usage guard in [S-16](docs/requirements/SOURCES.md): below 10% of the five-hour window, save the exact stop point, stop all work, and resume in the same thread only after reset plus two minutes.

The rest of this file records the completed planning package. Its old session exclusions do not override the current development authorization.

## Prepared Results

- [Sources](docs/requirements/SOURCES.md): TT.txt and direct clarifications are separated from previous AI ideas; the source is not copied into the project. S-10 records the developer's decision authority; S-11 the T01 escalation path.
- [Specification](docs/requirements/PRODUCT_SPEC.md) and [user flows](docs/requirements/USER_FLOWS.md): open types/languages, personal profiles, fields/lists, errors, access, and life cycle.
- [Decision register](docs/requirements/OPEN_QUESTIONS.md), [architecture](docs/architecture/ARCHITECTURE.md), and [ADRs](docs/decisions/README.md): agreed boundaries, stack, experimental recognition path, verification layer (ADR-0004), and runtime supervision and packaging (ADR-0005); engineering decisions are labeled ED.
- [Contracts](docs/architecture/CONTRACTS.md), [data](docs/architecture/DATA_MODEL.md), [state machine](docs/architecture/STATE_MACHINE.md), [security](docs/security/SECURITY.md), and [operations](docs/operations/OPERATIONS.md): the details required for implementation.
- [Acceptance](docs/testing/ACCEPTANCE_PLAN.md) and [verification strategy](docs/testing/TEST_STRATEGY.md): measurable criteria, sealed benchmark, and explicit limitations.
- [Roadmap](docs/planning/ROADMAP.md) and [eight individual tasks](specs/README.md): sequence, dependencies, results, and checks; T01 in three stages.

## Completion Condition for the Current Task

The main decisions have been aligned; T01b is frozen and the current work is T02–T08. Final quality acceptance remains pending the one integrated T01c/T07 benchmark run after the complete product is available through Telegram. The actual status of checks is recorded in [STATUS.md](STATUS.md).

Untested models are not declared suitable: T01 contains criteria for continuing, the remediation order on the current PC, and the point at which scope or criteria return to the developer. Selecting test corpus materials, pinning exact dependency versions, and running on Linux are defined tasks for future development, not unresolved fundamental decisions.

Code, manifests, CI, installing models or the environment, external resources, commits, and pushes are outside the results of this session.
