# T02 Local Foundation Verification

Date: 2026-09-28. Status: Windows foundation implemented; real Telegram walking
skeleton and Linux image build/native verification remain **not performed**.
Implementation proceeds under S-14; recognition quality remains unaccepted.

## Implemented Path

The T02 walking skeleton injects a synthetic fixed profile only for its check.
Private sign-in, message deletion, admission, download, the recognition core,
English result entities, and terminal cleanup are connected through per-user
mailboxes. Production personal-profile dialogues replace the test profile in T03.
Handlers enqueue events; cancellation invalidates generations and drains work
before removing originals. Stale updates do not start work or sign users in.

The application keeps all recognition files unchanged and verifies the frozen
code, prompt, dependency, runtime and policy identity at startup. The application
subclass schedules each adapter request separately, including token counting,
retry and alternate reads, and excludes GPU waiting from the core budget. Compiler
requests use the same scheduler with interactive priority.

PostgreSQL stores only users and current profiles; SQLAlchemy/psycopg runs in a
dedicated thread pool. Alembic performs actual migrations. See the verified
[PostgreSQL development setup](../operations/POSTGRESQL_DEVELOPMENT.md).

The temporary root is dedicated, marked and validated. Startup stops only matching
recorded process identities and cleans owned job directories before checking the
token, database or runtime. Cleanup retries preserve ownership markers and close
intake after deletion exhaustion and reopen it after recovery. Simulated restart
checks recreate the lifecycle service and recover owned process/job sidecars,
creation intents and deletion intents. Empty/truncated process staging writes are
discarded only with valid committed ownership and a valid committed manifest.
An initially truncated ownership marker has no such proof and remains fail-closed
for operator inspection. These checks do not establish native abrupt-termination
recovery at every individual disk-write boundary.
Application subprocesses are bound to a Windows kill-on-close Job Object; the
Linux branch supplies a parent-death signal but has not been run natively.

## Executed Checks

- Application foundation suite: 59 tests passed in 25.85 seconds. The suite covers
  startup, application foundation, subprocess supervision, fair scheduling,
  lifecycle handling, and real PostgreSQL storage.
- `python -m uv add` installed aiogram 3.31.0, SQLAlchemy 2.1.1, psycopg 3.3.6,
  Alembic 1.20.0 and python-dotenv 1.2.3. The existing frozen recognition
  dependencies and Python 3.14.5 stayed unchanged.
- Recognition regression suite: 293 passed, one opt-in runtime skip.
- Application checks cover real frozen-core parsing/preparation with synthetic
  model replies and controlled Telegram, duplicate/stale inputs, admission,
  responsive cancellation, per-call order/budget/cancellation, ownership, quota,
  cleanup retries, UTF-16 result entities and withheld invalid candidates.
- A native Windows subprocess test killed the parent abruptly, confirmed its
  supervised child terminated, then ran startup cleanup of synthetic originals.
- The external `foundation-check.env` uses a deliberately synthetic token and
  password plus generated local database credentials. A local startup check
  migrated PostgreSQL, verified frozen artifact hashes, started the real pinned
  CUDA llama-server, passed health, and stopped it. No Telegram client/API call
  was made. Command:
  `.venv\Scripts\python.exe -m tgbotdocs check --config C:\Users\nikit\TgBotDocsData\foundation-check.env`.
- The walking skeleton also ran a reviewed synthetic tuning image through the
  real pinned runtime and per-call scheduler using a controlled Telegram
  transport: one result, four accepted-value entities, and zero remaining job
  directories. This is integration evidence, not a new calibration or quality
  acceptance measurement. No benchmark case was read or run.
- T02 review findings for repeated-cancel cleanup and coordination between
  intake closure and the per-user mailbox were fixed and are included in the
  checked foundation implementation.

Test temporary data is placed outside AppData by setting process-local `TEMP` and
`TMP` to `C:\Users\nikit\TgBotDocsData\test-temp` before pytest. Logs/results report
codes rather than document content or secret values.

## Pending Checks

The real Telegram test is reserved for the developer's joint E2E. T01c corpus
preparation and the single integrated T01c/T07 sealed benchmark remain deferred
and mandatory. Native abrupt termination at every lifecycle disk-write boundary
has not been verified. Native Linux verification is not performed. Docker
is unavailable in the current shell, so an image build has not been verified;
packaging preparation belongs to T08. These limitations prevent claiming full
platform delivery or quality acceptance.
