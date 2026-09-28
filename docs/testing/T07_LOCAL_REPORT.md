# T07 Local Functional, Isolation and Resilience Checks

Date: 2026-09-28. Scope: the local checks that S-14-A4 allows before the joint
real-Telegram E2E. **Quality acceptance is not part of this report**: the single
sealed 70-case integrated benchmark shared with T01c is deferred (ED-016), and no
recognition accuracy is claimed. All checks ran on the development PC (Windows 11,
Ryzen 5 5600H, 16 GiB RAM, RTX 3060 Laptop 6 GiB) with the frozen configuration
`frozen-t01b.json` (SHA-256 `dd1d01a0…633f6`, `environment_mismatches` empty).
Telegram was always a controlled substitute; zero Telegram requests were made.

## Verification Matrix

Status per T07 area: **verified** (executed locally with evidence), **not verified**
(not executed; reason given) or **failed**.

| Area | Local evidence | Status |
| --- | --- | --- |
| Intake and pages | PNG/JPEG/PDF, photo and file paths, album order and late fragments, Several pages with mixed files, content-based format checks, protected/corrupt PDFs, pixel limit, 20 MiB actual bytes, quota and ENOSPC, parser child isolation and timeout: `tests/application/test_intake.py`, `test_documents.py`, `test_download_sink.py`; real model: file and photo paths | verified locally; real Telegram delivery paths pending the joint E2E |
| Type/profile | Matched, uncertain (choice among the snapshot), no profile (in-job instruction, preview, Save, one vs several profiles), unreadable/mixed/not_document, another user's profile excluded, snapshot immutability: `test_job_flow*.py`, `test_state_machine.py`; real model: automatic match of a saved profile and no match for a different type | verified locally (functional); automatic-selection quality pending the benchmark |
| Fields and lists | Frozen core contracts, merging, verification (T01b tests); rendering of fields, list reasons, long lists split into numbered parts without loss | verified (contracts and rendering); accuracy pending the benchmark |
| Uncertainty | Missing vs Unreadable vs Ambiguous vs invalid shown as Unreadable with the reason; failed results explain the cause; partial lists keep read cells | verified (contracts and rendering); ground-truth accuracy pending |
| Access/isolation | No download before sign-in and admission, password limits and deletion, group refusal, foreign/forged/old callbacks, two users' jobs, previews and results isolated, owner-scoped storage with real PostgreSQL | verified |
| Failures | Runtime crash during a real job (below), database outage (below), invalid JSON retry and contract failure (core tests), call and budget timeouts, queue-wait expiry, parser failure, Telegram delivery errors (retry_after, network, forbidden) with substitutes | verified locally; real Telegram outage behaviour pending the joint E2E |
| Life cycle | Cancel in every state including during delivery, inactivity expiry, admission refusal (Busy, time limit), restart with stale updates and buttons, cleanup after every terminal state, crash leftovers cleaned at startup (T02 native test), late results discarded | verified |
| Output | Values in `code` entities, no parse mode, link previews disabled, link-like values stay code, no unrequested fields | verified with the controlled Bot API; real client rendering pending the joint E2E |
| Leaks | Technical log, operator alerts, PostgreSQL tables and temporary root after real runs (below); llama-server runs with host prompt cache disabled (`--cache-ram 0`), no web UI and its output discarded; backup contains only the three permitted tables ([BACKUP_RESTORE](../operations/BACKUP_RESTORE.md)) | verified locally; OS paging/dump configuration and Telegram-side copies not verified |

## Real Resilience Run

`scripts/check-resilience-local.py --config C:\Users\nikit\TgBotDocsData\foundation-check.env`
(real startup, PostgreSQL 18.6, frozen CUDA runtime, controlled Bot API):

- Baseline synthetic invoice: complete, exact value, 10.5 s.
- llama-server killed during the job's model call: the job ended with an explicit
  error message (no result), the runtime was restarted automatically
  (`runtime_restarted` alert), and the next document completed with the exact
  value in 13.2 s.
- Leaks: the technical log (`startup_completed`, `runtime_restarted`; job outcome
  lines exist since commit `1fc5cdd`) contained no document value,
  password or token; PostgreSQL contained only `alembic_version`,
  `extraction_profiles` and `users`; no job directory or render reservation
  remained; operator messages were content-free.
- Resources: peak bot process RSS 243 MiB; llama-server RSS 3,050 MiB (includes
  the memory-mapped model); peak device GPU memory 4,940 MiB including about
  1.1 GiB used by other applications before the run.

A second run with `--database-outage` (57.4 s; baseline 8.2 s, crash recovery
10.2 s) stopped and restarted the development PostgreSQL cluster while the bot
ran:

- The health monitor detected the outage (`database_unavailable`); a new document
  was refused before any download with "Temporarily unavailable. Please try again
  later.", and no job or job directory was created.
- After the cluster restarted, the monitor reopened intake (`database_available`)
  and the next document completed with the exact value.
- The log contained only alert codes and `job_finished` lines with fixed outcome
  codes (`delivered_complete`, `runtime_transport_error`), random job IDs, page
  counts and charged seconds; no document value, password or token. Resources
  were as in the first run (bot 246 MiB, llama-server 3,054 MiB RSS, device GPU
  4,965 MiB).

A first attempt of this scenario hung inside the check script itself: capturing
the output of the PostgreSQL start command kept pipes open that the started
server inherited. The script was fixed (no captured pipes) and the run repeated;
the product was not involved. The interrupted attempt left one synthetic profile
and synthetic user rows, which were deleted (synthetic owner IDs ≥ 10^15 only).

A deeper model-based exploration (3,000 examples × 80 steps of the Hypothesis
state machine) also passed.

## Other Evidence

- Complete suite with real PostgreSQL passes (see [STATUS](../../STATUS.md) for the
  latest count); Ruff passes.
- Model-based state-machine test (Hypothesis) and scenario tests: see the
  [T06 report](T06_PROGRESS_REPORT.md).
- Local real-model product run (profile creation, file/photo paths, in-job
  instruction): [T06 report](T06_PROGRESS_REPORT.md).

## Not Verified Here

- Real Telegram behaviour (joint E2E), BotFather settings and client rendering.
- The sealed integrated benchmark: accuracy, completeness, language coverage,
  automatic profile selection quality and delivery-path comparison.
- Native Linux; long-duration soak runs and concurrent multi-user load on the GPU
  (the scheduler's fairness is verified with substitutes only).
- Abrupt power loss during every individual disk write (T02 covers recovery of
  recognized interrupted writes).
