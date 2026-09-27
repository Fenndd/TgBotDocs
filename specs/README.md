# Development Tasks

Specifications are prepared based on the agreed requirements and were revised on 2026-09-27 after the independent review. **T01 is performed first**, in three stages, as separate development tasks. There is no implementation yet; dependencies below mean the results of previous tasks, not merely the existence of their documents.

| Task | Result | Dependencies |
| --- | --- | --- |
| [T01 — recognition on PC](T01-recognition-baseline.md) | T01a: runtime envelope, launch profile, and verified runtime behavior. T01b: calibrated, frozen recognition core. T01c: sealed benchmark result and suitability decision | Contracts, ADR-0004; the ADR-0005 toolchain for T01b |
| [T02 — application foundation](T02-application-foundation.md) | Walking skeleton, reproducible environment, supervision, PostgreSQL, scheduler, and lifecycle | T01c passed |
| [T03 — access and profiles](T03-access-and-profiles.md) | Authorization with hardening, personal CRUD, multi-type preview/confirm, optimistic versions | T02 |
| [T04 — document intake](T04-document-intake.md) | Photo and file paths, PDF, album, Several pages, admission, preparation, and cleanup | T02, T03 |
| [T05 — recognition](T05-recognition-pipeline.md) | Profile matching, fields/lists, merging, verification, and uncertainty | T01, T03, T04 |
| [T06 — end-to-end Telegram](T06-telegram-orchestration.md) | State machine, dialogues, queue, partial response, delivery, cancellation, restart, operator alerts | T02–T05 |
| [T07 — acceptance](T07-acceptance-and-resilience.md) | Quality on the sealed 70 cases, isolation, failures, and no leaks | T01–T06 |
| [T08 — handoff](T08-delivery.md) | Verified Windows (native) and Linux (container) delivery, instructions, and licenses | T01–T07 |

Each task specifies scope and checks. Failure of T01 does not allow integration to continue as if the model were suitable: remediation follows [ADR-0004](../docs/decisions/ADR-0004-abstention-and-verification.md) on the current PC (S-11-A1), and a change of scope or criteria is the developer's decision.

General requirements — [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md); stages — [ROADMAP](../docs/planning/ROADMAP.md). The status “specification ready” means its content is ready; execution is permitted only through a separate development task and after dependencies are met. The status “implemented” will appear only with code and check results.
