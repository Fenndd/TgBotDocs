# Development Roadmap

Status: sequence defined based on agreed decisions; revised on 2026-09-27 after the independent review. Calendar estimates are not invented before the first measured result.

## Stages and Transition Conditions

| Stage | Separate tasks | What must be obtained to proceed |
| --- | --- | --- |
| 1. Recognition foundation | [T01](../../specs/T01-recognition-baseline.md): T01a → T01b before T02; T01c with T07 | T01a verifies the runtime on this PC. T01b produces the calibrated, frozen core and enables T02. T01c quality acceptance remains pending until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer; T01c and T07 share one integrated sealed benchmark run. Failure follows the remediation order of ADR-0004 on this PC (S-11-A1); scope or criteria changes return to the developer |
| 2. Product foundation | [T02](../../specs/T02-application-foundation.md) as a walking skeleton, then [T03](../../specs/T03-access-and-profiles.md) | An end-to-end path on the PC first; then reproducible launch, database/migrations, supervision, access, and personal confirmed profiles |
| 3. Documents and recognition | [T04](../../specs/T04-document-intake.md), [T05](../../specs/T05-recognition-pipeline.md) | Complete page sets, photo and file paths, admission, temporary lifecycle, instruction matching, merging, verification, scalar and repeating data |
| 4. End-to-end behavior | [T06](../../specs/T06-telegram-orchestration.md) | The state machine: English responses and clarifications, queue, cancellation, delivery, errors/TTL/restart, operator alerts |
| 5. Product acceptance | [T07](../../specs/T07-acceptance-and-resilience.md) | Local functional, isolation, cleanup, and resilience checks can proceed after T02–T06. The integrated 70-case quality benchmark is deferred and shared with T01c; T07 remains unaccepted until the one sealed run passes |
| 6. Prepared handoff | [T08](../../specs/T08-delivery.md) | Local packaging and available platform checks can proceed after T07's local checks. Full handoff acceptance remains pending the joint Telegram E2E, the shared sealed benchmark, and native Linux verification |

T01b is frozen and T02 may proceed; no recognition quality is accepted until the shared T01c/T07 benchmark passes. Continue T02–T08 in order, using controlled Telegram substitutes during local development. T07's functional and resilience checks and T08 preparation may proceed while real Telegram E2E is pending. Once the complete product is ready through Telegram, the developer and assistant perform the final E2E and one sealed integrated 70-case run; that run satisfies both T01c and T07 quality acceptance. Do not schedule a second benchmark run for T07. Specific dependencies are in the [task index](../../specs/README.md).

## Handoff and Future Server

The current PC is the development environment and the reference hardware class for v1 (S-11-A1). Before T08 is complete, an actual verification run on a native Linux x86-64/NVIDIA host is required; WSL2 on the development PC is acceptable only for early smoke tests (ED-008); the same PC booted natively into Linux qualifies. The environment for it will be selected later. This does not mean purchasing a server now. The customer's specific machine, scaling, SLA, and external deployment are subsequent decisions based on actual workload.

## Change Rule

Failure to meet quality/resource criteria, the need for external AI or stronger hardware, or new persistent storage is returned to the developer with measurements and options. Requirements must not be silently changed or a stage declared successful. Code, installation, and infrastructure are outside the current planning session.
