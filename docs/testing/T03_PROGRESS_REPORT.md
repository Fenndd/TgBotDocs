# T03 Progress and Open Verification

Date: 2026-09-28. Status: implementation in progress; **T03 is not complete**.
Recognition configuration and recognition source files remain frozen and unchanged.
No real Telegram API request, message or benchmark run was made.

## Verified Partial Results

- The RAM-only shared-password guard uses a constant-time UTF-8 comparison,
  per-user attempt windows, lock expiry, and a global-surge alert flag without a
  global sign-in pause. Two deterministic checks passed. Production sign-in,
  message deletion and operator alert integration remain to be completed.
- Instruction compilation uses the local model, interactive per-call scheduling,
  strict mutually exclusive drafts/questions, application-assigned UUIDs/owners,
  one contract retry, and the actual runtime's 4096-token context with a 1024-token
  output allowance. Existing recognition prompts/policy/configuration are unchanged.
- Owner-scoped RAM previews expire after inactivity and provide atomic creation,
  explicit deletion confirmation, optimistic version edits, repeated-confirmation
  idempotence, retry after storage failure, and draining of an already approved
  database write when its caller is cancelled.
- Compiler/preview deterministic checks: 26 passed in 1.24 seconds. Settings/access
  checks: eight passed in 3.97 seconds. Ruff over `src tests migrations` and Git
  whitespace checks passed. Settings is a composable dialogue module; it has not
  yet been connected to the production Telegram actor.
- With the actual frozen CUDA runtime, a synthetic instruction describing an
  invoice and a certificate produced exactly two drafts with the requested text
  fields and no validators. Both profiles were saved atomically in real PostgreSQL,
  confirmed twice without duplicates, read back equal, and removed using explicit
  deletion previews. The synthetic owner had zero profiles afterwards.

## Confirmed Failure to Fix Before Completing T03

The real-model negative check requested nested orders/line-items and an average
calculation. The model returned one structurally valid draft and zero questions,
silently simplifying unsupported requirements. Nothing from this check was saved.
Its input occupied 587 tokens, so this was a semantic interpretation failure rather
than a context overflow. T03 requires an explicit clarification/simplification
request for unsupported nesting or calculations. Structural validation alone does
not satisfy that requirement. Fix and verify this behavior with supported and
unsupported real-model examples before treating the compiler as ready.

## Dialogue Review and Remaining Integration

The first independent Settings review identified two defects: a Cancel button
could falsely claim that an already confirmed in-flight save changed nothing;
terminal failures retained draft text in closed RAM sessions. Both were fixed:
saving now waits for its result, and terminal error cleanup discards draft state.
Regression checks cover both fixes. The independent reviewer then ran the combined
access/compiler/profile-preview/Settings suite: **34 passed in 4.84 seconds**.
No additional confirmed P1/P2 findings were reported in that reviewed snapshot.

Complete production access/menu/profile integration, inactivity maintenance,
logout/stale-callback handling and the Settings/document overlap rule. Follow the
current findings and exact resumption instructions in [STATUS](../../STATUS.md).
T04–T08 implementation, the final whole-product review, the joint real-Telegram
test, the deferred T01c/T07 sealed benchmark, and native Linux verification remain
pending. No recognition-quality acceptance is claimed.
