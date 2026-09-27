# Development Roadmap

Status: sequence defined based on agreed decisions. Date: 2026-09-27. Calendar estimates are not invented before the first measured result.

## Stages and Transition Conditions

| Stage | Separate tasks | What must be obtained to proceed |
| --- | --- | --- |
| 1. Architectural risk check | [T01](../../specs/T01-recognition-baseline.md) | The selected Qwen 4B runs locally and meets the accepted criteria; resource use and parameters are known. Failure returns the choice for discussion |
| 2. Product foundation | [T02](../../specs/T02-application-foundation.md), [T03](../../specs/T03-access-and-profiles.md) | Reproducible launch, database/migrations, access, personal confirmed profiles |
| 3. Documents and recognition | [T04](../../specs/T04-document-intake.md), [T05](../../specs/T05-recognition-pipeline.md) | Complete page sets, temporary lifecycle, instruction matching, scalar and repeating data |
| 4. End-to-end behavior | [T06](../../specs/T06-telegram-orchestration.md) | English responses and clarifications, queue, cancellation, delivery, errors/TTL/restart |
| 5. Product acceptance | [T07](../../specs/T07-acceptance-and-resilience.md) | Quality, isolation, cleanup, and resilience have passed for the integrated application |
| 6. Prepared handoff | [T08](../../specs/T08-delivery.md) | Windows/Linux, instructions, versions, licenses, backup/restore, and clean launch verified |

Separating T02–T06 makes it possible to verify each result independently. Specific dependencies are in the [task index](../../specs/README.md). Bypassing a dependency based on one successful model example is not allowed.

## Handoff and Future Server

The current PC is the initial development environment. Before T08 is complete, an actual verification run on Linux x86-64/NVIDIA is required; the environment for it will be selected later. This does not mean purchasing a server now. The customer's specific machine, scaling, SLA, and external deployment are subsequent decisions based on actual workload.

## Change Rule

Failure to meet quality/resource criteria, the need for external AI, or new persistent storage is returned to the developer with measurements and options. Requirements must not be silently changed or a stage declared successful. Code, installation, and infrastructure are outside the current planning session.
