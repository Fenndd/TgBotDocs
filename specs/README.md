# Development Tasks

Specifications are prepared based on the agreed requirements and were revised on 2026-09-27 after the independent review. T01b is calibrated and frozen; T02–T08 proceed in order. T01c benchmark preparation and the one sealed integrated run shared with T07 are deferred until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer. Dependencies below mean the results of previous tasks, not merely the existence of their documents.

| Task | Result | Dependencies |
| --- | --- | --- |
| [T01 — recognition on PC](T01-recognition-baseline.md) | T01a: runtime envelope and verified runtime behavior. T01b: calibrated, frozen recognition core. T01c: required quality acceptance from the one integrated sealed benchmark shared with T07 | Contracts, ADR-0004; the ADR-0005 toolchain for T01b |
| [T02 — application foundation](T02-application-foundation.md) | Walking skeleton, reproducible environment, supervision, PostgreSQL, scheduler, and lifecycle | T01b reviewed, calibrated, and frozen; T01c remains required acceptance but does not gate T02 |
| [T03 — access and profiles](T03-access-and-profiles.md) | Authorization with hardening, personal CRUD, multi-type preview/confirm, optimistic versions | T02 |
| [T04 — document intake](T04-document-intake.md) | Photo and file paths, PDF, album, Several pages, admission, preparation, and cleanup | T02, T03 |
| [T05 — recognition](T05-recognition-pipeline.md) | Profile matching, fields/lists, merging, verification, and uncertainty | T01b frozen, T03, T04; T01c is deferred acceptance, not an implementation gate |
| [T06 — end-to-end Telegram](T06-telegram-orchestration.md) | State machine, dialogues, queue, partial response, delivery, cancellation, restart, operator alerts | T02–T05 |
| [T07 — acceptance](T07-acceptance-and-resilience.md) | Local functional/isolation/resilience checks plus the deferred integrated quality acceptance on the sealed 70 cases | T01b frozen, T02–T06; T01c/T07 share one integrated sealed run after the product is available through Telegram |
| [T08 — handoff](T08-delivery.md) | Local delivery preparation and platform checks; full acceptance remains pending | T07 local checks; final acceptance also needs the joint Telegram E2E, shared T01c/T07 benchmark, and native Linux verification |

Each task specifies scope and checks. T01b freeze enables integration but is not quality acceptance. The T01c/T07 benchmark remains required; failure follows [ADR-0004](../docs/decisions/ADR-0004-abstention-and-verification.md) on the current PC (S-11-A1), and a change of scope or criteria is the developer's decision. The local work in T07/T08 does not mark the pending joint Telegram E2E or quality acceptance complete.

General requirements — [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md); stages — [ROADMAP](../docs/planning/ROADMAP.md). The status “specification ready” means its content is ready; execution is permitted only through a separate development task and after dependencies are met. Actual implementation and acceptance status are recorded in [STATUS](../STATUS.md), with local results distinguished from pending final checks.
