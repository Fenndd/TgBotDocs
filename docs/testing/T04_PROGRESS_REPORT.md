# T04 Intake Progress and Remaining Integration

Date: 2026-09-28. Status: resource layer and collection actor verified locally
with controlled Telegram substitutes. Frozen recognition source, dependencies and
configuration remain unchanged. No real Telegram request, deployment, push or
sealed benchmark run was performed; real-Telegram checks remain for the joint E2E.

## Verified Resource Layer

- Local commits `8012c2f` and `faf5585` provide bounded binary downloads, admission
  before download, stable file/page bindings, complete content inspection in
  supervised parser children, cancellation/drain and owned cleanup.
- Actual streamed bytes are checked against 20 MiB, independently of advertised
  sizes. Each synchronous quota check/write/flush finishes before another download
  can write. Local disk failures become `storage_limit`; network read failures
  remain `download_failed`. Derived-render reservations belong to T05 integration.
- PNG/JPEG images are checked and fully decoded after the pixel guard. This fixes
  the application intake gap in JPEG `verify()` without changing the frozen core.
  PDF parsing refuses protected/corrupt files and counts the complete document.
  A dynamic processing-time bound refuses an infeasible whole PDF before producing
  a giant metadata response. Parser stdout is bounded and contains metadata only.
- Albums use message order. Albums inside Several pages are sorted within their
  existing positions while unrelated files retain their placement. All PDF pages
  and stable `(file_key, file_page_index)` associations are preserved.
- Admission uses every page's kind and the frozen per-kind p5 time. The initial
  fixed overhead is explicitly unmeasured `0.0`; it is an engineering initial
  policy, not a performance acceptance result. No fixed page/file cap is added.
- Final intake/sink suite: **27 passed in 14.14 seconds**, including real parser
  children, protected PDFs with empty/nonempty passwords, truncated JPEG, exact
  byte limits, actual quota/concurrency, deduplication, generation invalidation,
  parser timeout/spawn cancellation, bounded stdout, ENOSPC and cleanup retry.
  Ruff and Git whitespace checks passed; all test child processes exited.
- The independent intake review ran **26 tests in 12.92 seconds** and verified
  Several pages album ordering. Its native-storage classification finding was
  subsequently fixed and covered by the final 27-test author run.

## Collection Actor

`application/documents.py` implements single-file startup, album quiet/absolute
timers, Several pages/Process, pre-delivery restart, post-delivery refusal,
generation-tagged operations and terminal cleanup. The actor checks include a
controlled ProductApplication with the actual supervised parser: authentication
before download, two owners, a mixed PNG/PDF/PNG set with all four pages,
duplicate-update suppression, distinct messages with identical bytes,
compressed-photo provenance, Logout/Cancel and zero remaining owned job directories.

Album rules inside Several pages are covered: a known group's late fragment
restarts the pass before delivery while keeping the admission place and the
charged budget, is refused without download after delivery starts, and stays
remembered for 15 minutes after the job ends; unrelated files and new albums
after Process are refused.

An independent review (three Claude Code `opus-high` reviewers: specification,
concurrency, test adequacy; each finding adversarially re-verified by a separate
`opus-high` agent with scratch reproductions) confirmed eight findings. All were
fixed with regressions:

- A refused first album part (Busy, or while another job is active or finishing)
  now closes its media group, so the remaining parts cannot form a partial album.
- Buttons stay valid for the job's current generation; only a new generation or
  a new process invalidates them.
- An accepted page that is still downloading counts as activity for the
  15-minute inactivity timer, and Process resets it.
- An empty seal after failed late album parts leaves the album quiet mode, so
  the set again waits for an explicit Process.
- A Several pages job after Process no longer counts as waiting for the user.
- Timer and capacity configuration parsing/validation now has a test, and the
  expired job's own button and late album part are shown not to revive it.

Verification of the committed collector (temporary worktree at the commit
content): `tests/application` **151 passed**; Ruff passed. The complete
repository suite with real PostgreSQL passed **459, 1 skipped** on the combined
working tree (this collector plus the first T05/T06 changes) before those were
split into later commits.

T05 recognition integration and T06 questions/delivery continue in their own
commits and reports. Recognition quality is not accepted. Resume from
[STATUS](../../STATUS.md).
