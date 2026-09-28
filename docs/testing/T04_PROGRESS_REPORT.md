# T04 Intake Progress and Remaining Integration

Date: 2026-09-28. Status: resource layer verified; collection integration remains
in progress and is paused at the account usage checkpoint. T04 is not complete.
Frozen recognition source, dependencies and configuration remain unchanged.
No real Telegram request, deployment, push or sealed benchmark run was performed.

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

## Collection Actor and Open Checks

The current uncommitted `application/documents.py` implements single-file startup,
album quiet/absolute timers, Several pages/Process, pre-delivery restart, post-
delivery refusal, generation-tagged operations and terminal cleanup. Seven actor
checks passed in **5.62 seconds** before the latest manual-album lifecycle patch.
They include a controlled ProductApplication with the actual supervised parser:
authentication before download, two owners, a mixed PNG/PDF/PNG set with all four
pages, duplicate-update suppression, distinct messages with identical bytes,
compressed-photo provenance, Logout/Cancel and zero remaining owned job directories.

An independent collection review reproduced and verified fixes for two defects:
terminal cleanup needed the generation after resource closure, and Process needed
to refuse newly submitted separate files while prior downloads finished. Six
focused actor checks passed independently in 4.28 seconds.

The combined application/storage run produced **151 passed and one failed** in
26.20 seconds. The failing new integration assertion expected a collection count
after Process had already closed collection. The test now observes the count
while collection is open; all seven actor tests then passed. The complete suite
has not been rerun after the latest resource and manual-album fixes.

The latest independent finding applies album lifecycle rules inside Several
pages: a known group's late fragment must restart before delivery, be refused
with an incomplete-album notice after delivery, and remain remembered after the
job ends. A patch now tracks all member group IDs and applies a quiet window to
manual replay. **That latest patch has not been tested or independently rechecked.**
Add the before-delivery, after-delivery and terminal-memory regressions, including
preserved admission time/charged budget and refusal of unrelated files after
Process. Then rerun affected and combined checks before committing the collector
or advancing to T05.

T05 recognition integration, T06 questions/delivery and Settings overlap, T07 local
resilience, T08 packaging, whole-product review, joint real-Telegram E2E, the
deferred single T01c/T07 sealed benchmark and native Linux verification remain
pending. Recognition quality is not accepted. Resume from [STATUS](../../STATUS.md).
