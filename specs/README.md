# Development Tasks

Specifications are prepared based on the agreed requirements. **T01 is performed first** as a separate development task. There is no implementation yet; dependencies below mean the results of previous tasks, not merely the existence of their documents.

| Task | Result | Dependencies |
| --- | --- | --- |
| [T01 — recognition on PC](T01-recognition-baseline.md) | Measured direct Qwen 4B and suitability decision | Agreed contracts and criteria |
| [T02 — application foundation](T02-application-foundation.md) | Reproducible environment, PostgreSQL, model adapter, queue, and lifecycle | Successful T01 |
| [T03 — access and profiles](T03-access-and-profiles.md) | Authorization, personal CRUD, preview/confirm, versions | T02 |
| [T04 — document intake](T04-document-intake.md) | Files, PDF, album, Several pages, preparation, and cleanup | T02, T03 |
| [T05 — recognition](T05-recognition-pipeline.md) | Profile matching, fields/lists, validation, and uncertainty | T01, T03, T04 |
| [T06 — end-to-end Telegram](T06-telegram-orchestration.md) | Dialogues, queue, partial response, delivery, cancellation, and restart | T02–T05 |
| [T07 — acceptance](T07-acceptance-and-resilience.md) | Quality on 70 cases, isolation, failures, and no leaks | T01–T06 |
| [T08 — handoff](T08-delivery.md) | Verified Windows/Linux delivery, instructions, and licenses | T01–T07 |

Each task specifies scope and checks. Failure of T01 does not allow integration to continue as if the model were suitable: a review based on measurements must be agreed.

General requirements — [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md); stages — [ROADMAP](../docs/planning/ROADMAP.md). The status “specification ready” means its content is ready; execution is permitted only through a separate development task and after dependencies are met. The status “implemented” will appear only with code and check results.
