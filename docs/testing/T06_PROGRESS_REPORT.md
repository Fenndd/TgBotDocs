# T06 Telegram Orchestration Progress

Date: 2026-09-28. Status: implemented and verified locally with controlled
Telegram substitutes and, for one functional run, the real frozen model and real
PostgreSQL. **No real Telegram request was made**: the final real-Telegram E2E is
performed jointly with the developer. Recognition quality is not accepted (single
sealed T01c/T07 benchmark pending). Frozen recognition source/configuration is
unchanged (`environment_mismatches` empty).

## Implemented

- **Job state machine** (`application/documents.py`): collecting → admission →
  queued → recognition phase → awaiting_choice / awaiting_instruction → compiling →
  awaiting_confirmation → saving → delivering → finished, with cancellation,
  expiry and restart-by-late-album from every state. Matching statuses follow
  CONTRACTS; `no_profile`'s model-written type description is never shown.
- **Budget and scheduling**: the phases share one cumulative processing budget
  (T05 `RecognitionService`); waiting for the user or the GPU is not charged; a
  resumed job keeps its admission order in the S-12 ring; a phase or compilation
  starts only with remaining budget, otherwise the time-limit outcome.
- **Settings overlap (S-13, ED-013)**: Settings is view-only while the job waits;
  a job question arriving while a Settings draft is open is deferred, shown when
  the draft is saved, cancelled or expires, and only then starts the inactivity
  timer and the job draft's lifetime.
- **Buttons**: valid for the job's current generation; profile choices and
  preview decisions are bound to that profile/preview; foreign, forged and old
  tokens answer "Session expired"; tokens from a previous process also trigger one
  restart notice.
- **Delivery** (`application/delivery.py`, `OrderedTransport`): per-chat ordered
  messages; numbered parts with `code` entities, no parse mode, no link preview;
  only `retry_after` is retried within the 60 s window; failed/uncertain delivery
  is not reported complete and alerts the operator (not for a user who blocked the
  bot); after Cancel no part or retry starts and a part queued behind another
  message is withdrawn.
- **Rendering**: unresolved lists show Missing/Unreadable/Ambiguous (invalid as
  Unreadable with the format-check reason); a failed result says whether none of
  the requested data is present or it could not be read; the profile used is named,
  with "(chosen by you)" for a manual choice; compressed photos get the file hint.
- **Service** (`application/service.py`, `python -m tgbotdocs run --config ...`):
  startup order cleanup → configuration → PostgreSQL/migrations → runtime → long
  polling (`message`, `callback_query`); a 1 s tick drives timers; technical log
  rotated daily for 7 days with dependency loggers at WARNING; operator alerts for
  startup completed/failed, intake closed/reopened, runtime/database transitions,
  password surges and failed delivery. Stale detection compares message dates with
  the whole-second start time.
- **Dependency health** (`application/health.py`): database and runtime checks
  every 30 s gate intake before download; a dead, unreleased or repeatedly failing
  runtime is restarted inside the GPU scheduler slot (never during a call), retried
  rarely while unavailable, and every transition alerts once.
- **Platform runtime seam**: `RUNTIME_EXECUTABLE` + `RUNTIME_EXECUTABLE_SHA256`
  select another platform's build of the pinned llama.cpp release (the Linux
  image), verified by its own pinned hash; startup alerts
  `runtime_executable_differs_from_frozen`, because that executable was not the
  calibrated one and its platform needs its own verification (T08).

## Verified

- Complete suite with real PostgreSQL: **490 passed, 1 skipped** (184.6 s); Ruff
  passed. The T06 dialogue commit was verified separately in a temporary worktree
  (`tests/application` 181 passed).
- Scenario tests (`test_job_flow.py`, `test_job_flow_edges.py`): single file,
  album restart, uncertain choice, no-profile instruction with questions, preview,
  Edit, storage failure and Save, single vs several saved profiles, deferred
  questions, view-only Settings, every terminal matching status and error, Cancel
  in each waiting state, late results of a replaced or cancelled pass, turn order,
  budget pause, snapshot immutability, long/partial/zero results, delivery retries,
  uncertain/blocked delivery, Cancel during delivery, two-user isolation, stale
  buttons after restart.
- Model-based test (`test_state_machine.py`, Hypothesis, 300 examples × 60 steps,
  two users, late model responses): at most one job and one waiting flow per user,
  no download before sign-in, no model call for a cancelled/stale job or without
  budget, terminal jobs cleaned, drafts only for live jobs, results only for
  released current matches, foreign buttons change nothing. Mutation checks: it
  fails when job drafts are not discarded, when buttons are accepted across jobs
  and when deferral is removed.
- `test_service.py`: the production composition driven through aiogram's
  dispatcher with a scripted Bot API session: group refusal, stale password
  deletion with one restart notice, sign-in, a photo through the real intake and
  parser child, the frozen core (render, verification with V2, merge) with a
  deterministic model, delivery with a code entity and no preview, cleanup, stale
  button, operator startup alert without content.
- `test_health.py`: intake gating, one alert per transition, restart waiting for
  the running call, rare retries and recovery.
- Independent review of the dialogue (three `opus-high` reviewers: specification,
  concurrency, security/tests; adversarial `opus-high` verification): three
  defects and six test gaps confirmed and fixed; the two concurrency/lifetime
  regressions fail under mutation of the fix.
- **Real local product run** (`scripts/check-product-local.py`, controlled Bot API
  session, real PostgreSQL 18.6 and the frozen CUDA runtime, 43 s including
  startup): Settings instruction → preview → Save; a synthetic invoice through the
  file path (10.3 s) and the photo path (8.2 s) returned "Result: Complete" with
  the exact synthetic values; a receipt without a profile went through the in-job
  instruction, preview and Save and returned a complete result marked "(chosen by
  you)"; zero job directories and reservations remained; synthetic profiles were
  deleted. Zero Telegram network requests. Functional evidence only.

## Not Verified / Pending

- Real Telegram (the joint final E2E), including actual photo recompression,
  `retry_after`, blocked users and BotFather group settings.
- The single sealed integrated benchmark (T01c/T07) and any quality claim.
- Native Linux; the Linux build of llama-server is a different executable and
  needs its own verification.
- Observation: the instruction compiler sometimes copies the example description
  "Applicable documents" into a draft (seen once in the real run). The preview
  shows it and the user can edit it; improving the compiler prompt needs its own
  real-model check.
