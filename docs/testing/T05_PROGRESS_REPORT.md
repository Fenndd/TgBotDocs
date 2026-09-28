# T05 Recognition Integration Progress

Date: 2026-09-28. Status: application seams verified with scripted model
substitutes and integrated with the product; a local real-model product run is
recorded below and in the [T06 report](T06_PROGRESS_REPORT.md). Recognition
quality is **not accepted**: it depends on the deferred single sealed T01c/T07
benchmark. Frozen recognition source,
prompts, thresholds, policy and configuration remain unchanged
(`environment_mismatches` stays empty); every change is in `application/`.

## What the Product Uses

- `application/pipeline.py` (`RecognitionService`) runs one recognition phase of
  an admitted job through the frozen `RecognitionCore`: matching and extraction,
  or extraction only with a user-selected profile. The phase receives only the
  job's remaining processing budget, so matching, instruction compilation,
  a manual choice and a restarted pass share one cumulative budget (ED-003). The
  time a phase charged is always reported, including after cancellation by Cancel
  or a late album fragment ("the budget already charged stays charged").
- `application/scheduler.py` (`ScheduledRecognitionCore`) keeps one model call at a
  time in the S-12 ring and now removes GPU queue wait from every trace duration:
  each call record, and the primary/alternate (V2) times of every batch. Without
  this, a turn given to another document between the primary and the V2 call was
  charged to this job and could make `decide` report a false time-limit error.
- `application/lifecycle.py` holds global render-quota reservations. A phase
  reserves an upper bound of the derived bytes the frozen core can hold for this
  document (one batch bounded by the prompt's image tokens, one lookahead page and
  the V2 view at 0.75 scale), and the same bound becomes the job's hard worker
  quota. Downloads of other jobs see reserved capacity as used, so originals and
  renders together stay within the configured 2 GiB temporary quota; failure is
  the explicit `storage_limit` outcome.

## Verified

- `tests/application/test_pipeline.py`: queue wait removed from call records and
  V2 times with a real interactive call taking the GPU between the primary and V2
  call (phases add up exactly to the budget's charged time); cancellation reports
  charged time and releases the reservation, scheduler metadata and render
  directories; a second phase continues only the remaining budget and times out on
  it; fixed error codes; document-aware reservation bounds; reservations block
  downloads and fail explicitly.
- Existing scheduler/core parity tests still pass, including the full core run
  with a retry and V2 through the scheduler.
- Integrated through the T06 state machine: scenario and model-based tests cover
  budget continuation across a manual choice or a saved profile, turn order and
  snapshot immutability ([T06 report](T06_PROGRESS_REPORT.md)).
- `tests/application/test_service.py` runs the real frozen core (inspection,
  rendering, verification with the V2 view, merging) through the production
  composition with a deterministic model.
- A local real-model run through the product (`scripts/check-product-local.py`,
  frozen CUDA runtime, real PostgreSQL, controlled Bot API) completed matching and
  extraction for synthetic documents on the file and photo paths and after an
  in-job profile creation; no job directory or reservation remained. This is
  functional evidence, not quality acceptance.

## Pending

- Quality, language and delivery-path acceptance: the single sealed integrated
  benchmark after the joint real-Telegram E2E.
