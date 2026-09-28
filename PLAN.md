# Development Plan

Status: local product preparation for the developer's joint Telegram test is complete; updated 2026-09-28. T02–T07 implementation and available T08 packaging are recorded in [STATUS](STATUS.md) and the [T08 local report](docs/testing/T08_LOCAL_REPORT.md). Independent product/packaging review findings were fixed and verified, including PostgreSQL directory permissions and foreign-service identity. Full platform and recognition-quality acceptance remains pending the explicit developer-controlled checks below.

## Current Execution Sequence

1. T02–T06 are implemented and verified locally ([T04](docs/testing/T04_PROGRESS_REPORT.md), [T05](docs/testing/T05_PROGRESS_REPORT.md), [T06](docs/testing/T06_PROGRESS_REPORT.md) reports). T01c does not gate implementation.
2. T07 local functional, isolation, and resilience checks passed, including controlled real CUDA/PostgreSQL checks with zero Telegram requests. They do not constitute recognition-quality or complete-product acceptance.
3. T08 local packaging, private backup/fresh-target restore, locked production-environment reproduction and operator/user instructions are prepared and checked where available. Elevated Windows boot/service/task checks and native Linux execution remain unperformed; the current Windows PC does not verify Linux.
4. After the complete product is available through Telegram, perform the final real-Telegram E2E jointly with the developer, then prepare, review, seal, and run the single 70-case integrated benchmark for both T01c and T07. The benchmark remains required acceptance; T01b freeze does not accept recognition quality. Do not schedule a second sealed run for T07.
5. Remote deployment remains deferred. Follow the benchmark ledger and record unperformed checks honestly.

While the developer is absent, continue independent work and defer developer-only decisions (S-16, S-17). Make small logical changes and verify each unit before committing. The S-16 usage guard applies to this resumed Codex session; save the precise stop point and stop completely below 10% remaining, then resume in this same thread after reset plus two minutes.

The rest of this file records the completed planning package. Its old session exclusions do not override the current development authorization.

## Prepared Results

- [Sources](docs/requirements/SOURCES.md): TT.txt and direct clarifications are separated from previous AI ideas; the source is not copied into the project. S-10 records the developer's decision authority; S-11 the T01 escalation path.
- [Specification](docs/requirements/PRODUCT_SPEC.md) and [user flows](docs/requirements/USER_FLOWS.md): open types/languages, personal profiles, fields/lists, errors, access, and life cycle.
- [Decision register](docs/requirements/OPEN_QUESTIONS.md), [architecture](docs/architecture/ARCHITECTURE.md), and [ADRs](docs/decisions/README.md): agreed boundaries, stack, experimental recognition path, verification layer (ADR-0004), and runtime supervision and packaging (ADR-0005); engineering decisions are labeled ED.
- [Contracts](docs/architecture/CONTRACTS.md), [data](docs/architecture/DATA_MODEL.md), [state machine](docs/architecture/STATE_MACHINE.md), [security](docs/security/SECURITY.md), and [operations](docs/operations/OPERATIONS.md): the details required for implementation.
- [Acceptance](docs/testing/ACCEPTANCE_PLAN.md) and [verification strategy](docs/testing/TEST_STRATEGY.md): measurable criteria, sealed benchmark, and explicit limitations.
- [Roadmap](docs/planning/ROADMAP.md) and [eight individual tasks](specs/README.md): sequence, dependencies, results, and checks; T01 in three stages.

## Completion Condition for the Current Task

T01b is frozen. The local product is ready for the developer to configure the real token/password and start the joint Telegram test using [the exact PC instructions](docs/operations/LOCAL_PC_JOINT_TEST.md). Final quality acceptance remains pending the one integrated T01c/T07 benchmark after that E2E. Full T08 acceptance also requires clean-machine Windows and native Linux verification. The actual status of checks is recorded in [STATUS.md](STATUS.md).

Untested models are not declared suitable: T01 contains criteria for continuing, the remediation order on the current PC, and the point at which scope or criteria return to the developer. Selecting test corpus materials, pinning exact dependency versions, and running on Linux are defined tasks for future development, not unresolved fundamental decisions.

The preceding planning-only exclusions are historical. The current development task authorized implementation, local dependencies and verified local commits. Push, real Telegram requests, external delivery and deployment were not performed.
