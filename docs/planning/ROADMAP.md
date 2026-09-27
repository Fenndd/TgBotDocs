# Development Roadmap

Status: sequence defined based on agreed decisions; revised on 2026-09-27 after the independent review. Calendar estimates are not invented before the first measured result.

## Stages and Transition Conditions

| Stage | Separate tasks | What must be obtained to proceed |
| --- | --- | --- |
| 1. Architectural risk check | [T01](../../specs/T01-recognition-baseline.md): T01a → T01b → T01c | T01a: the selected Qwen 4B fits the PC and the runtime behaves as the design requires. T01b: a calibrated, frozen recognition core. T01c: the sealed benchmark meets the accepted criteria. Failure follows the remediation order of ADR-0004 on this PC (S-11-A1); scope or criteria changes return to the developer |
| 2. Product foundation | [T02](../../specs/T02-application-foundation.md) as a walking skeleton, then [T03](../../specs/T03-access-and-profiles.md) | An end-to-end path on the PC first; then reproducible launch, database/migrations, supervision, access, and personal confirmed profiles |
| 3. Documents and recognition | [T04](../../specs/T04-document-intake.md), [T05](../../specs/T05-recognition-pipeline.md) | Complete page sets, photo and file paths, admission, temporary lifecycle, instruction matching, merging, verification, scalar and repeating data |
| 4. End-to-end behavior | [T06](../../specs/T06-telegram-orchestration.md) | The state machine: English responses and clarifications, queue, cancellation, delivery, errors/TTL/restart, operator alerts |
| 5. Product acceptance | [T07](../../specs/T07-acceptance-and-resilience.md) | Quality, isolation, cleanup, and resilience have passed for the integrated application |
| 6. Prepared handoff | [T08](../../specs/T08-delivery.md) | Native Windows and Linux container paths, instructions, versions, licenses, backup/restore, and clean launch verified |

The sealed benchmark of T01c may be prepared in parallel with T01a and T01b. The walking skeleton exposes integration problems before T03–T06 build on the foundation. Separating T02–T06 makes it possible to verify each result independently. Specific dependencies are in the [task index](../../specs/README.md). Bypassing a dependency based on one successful model example is not allowed.

## Handoff and Future Server

The current PC is the development environment and the reference hardware class for v1 (S-11-A1). Before T08 is complete, an actual verification run on a native Linux x86-64/NVIDIA host is required; WSL2 on the development PC is acceptable only for early smoke tests (ED-008); the same PC booted natively into Linux qualifies. The environment for it will be selected later. This does not mean purchasing a server now. The customer's specific machine, scaling, SLA, and external deployment are subsequent decisions based on actual workload.

## Change Rule

Failure to meet quality/resource criteria, the need for external AI or stronger hardware, or new persistent storage is returned to the developer with measurements and options. Requirements must not be silently changed or a stage declared successful. Code, installation, and infrastructure are outside the current planning session.
