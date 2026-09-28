# T07 — Acceptance of Quality, Isolation, and Resilience

Status: T07 local implementation and functional, isolation, cleanup, and resilience checks are complete; see the [T07 local report](../docs/testing/T07_LOCAL_REPORT.md). All Telegram interactions in those checks used a controlled substitute, with zero real Telegram requests. Full acceptance remains pending: T01c and T07 share one required sealed integrated 70-case quality run, deferred until the complete product is available through Telegram and the final real-Telegram E2E can be done jointly with the developer. Recognition quality is not accepted. Date: 2026-09-28; existing criteria remain unchanged.

## Goal and Basis

Demonstrate with independent ground truths and reproducible failures that the selected product performs the agreed flows, honestly represents uncertainty, and deletes temporary data.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md); [TEST_STRATEGY](../docs/testing/TEST_STRATEGY.md); [USER_FLOWS](../docs/requirements/USER_FLOWS.md); [STATE_MACHINE](../docs/architecture/STATE_MACHINE.md); [CONTRACTS](../docs/architecture/CONTRACTS.md); [SECURITY](../docs/security/SECURITY.md).

## Scope and Dependencies

- Test integrated T02–T06 and the frozen [T01](T01-recognition-baseline.md) configuration, not responses from a separately run model. Profiles are compiled by the product's instruction compiler and confirmed through the preview, not the hand-authored fixtures of T01b.
- Local functional, isolation, cleanup, and resilience checks may be completed before final real-Telegram E2E. T01b freeze is not recognition-quality acceptance. Defer the one integrated sealed quality run until the complete product is available through Telegram; its result supplies both T01c and T07 quality acceptance. Do not run a separate core-only sealed benchmark.
- The sample and ground truths follow [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md): synthetic or authorized data, different documents/languages/layouts, phone photos, and recorded delivery paths through the real bot. User uploads do not become a permanent test archive.
- S-09-A2 is accepted: 40 readable + 20 difficult + 10 negative cases; 0 incorrectly accepted values/automatic profiles and at least 90% of requested readable fields/cells. The same sealed set is used for the single T01c/T07 integrated run. A case examined individually to change prompts, thresholds, signals, or rules becomes a tuning case and must be replaced before a later acceptance run under the frozen-identity rules.
- Any language is accepted without a whitelist, with honest uncertainty; the test set does not prove support for all writing systems. Specific materials and ground truths are created/checked in T01.

## Verification Matrix

| Area | Required cases | Expected outcome |
| --- | --- | --- |
| Intake and pages | PNG/JPEG/PDF, photo and file paths, two sides, Several pages, album/late fragment | Complete order/source, no hidden cropping |
| Type/profile | One/multiple/no profile, multi-type instruction, unknown/mixed/non-document | Correct transition or clarification; another user's profile excluded |
| Fields and lists | Separate fields, rows across pages and batches, leading zeros, dates | Requested items only; exact ground truths/statuses/columns |
| Uncertainty | Missing, glare/cropping, ambiguous characters, conflicting sides | Missing does not replace unreadable; conflict does not become fact |
| Access/isolation | Before password, another user's ID/callback, two owners, logout, password limits | No download/leak/unauthorized change |
| Failures | Model/DB/Telegram unavailable, invalid JSON, timeout, runtime restart, parser error | Clear error, queue continues, no stale response |
| Life cycle | Cancel at every stage, TTL, admission refusal, crash/restart with stale updates, partial delivery | Cleanup, new login, profiles retained, document resubmitted |
| Output | Values that look like links, commands, or formatting | Shown as `code` text; no link preview; no unrequested fields |
| Leaks | Logs, backup, PostgreSQL, temp, model logs, runtime memory settings, operator alerts | No originals/OCR/fields/evidence/secrets outside the permitted lifecycle |

## Implementation Result

1. Versioned list of permitted test cases with delivery paths and independent ground truths; tuning examples separate from the final sample; replaced cases recorded.
2. Actual verification commands/scenarios for the future project with pinned versions, configuration, results, and known untested cases.
3. Separate report of incorrectly accepted values, refusals/missing values, correct fields/cells, incorrect profiles, and fully successful documents; state the exact denominator and the zero-error bound for every metric and group.
4. Measurements of memory/time on the PC, resilience across sequential tasks, and cleanup under simulated failures. No conclusions about the customer's unknown multi-user workload.
5. Nonconformity checklist with reproduction steps; fixes rerun affected local scenarios. Do not run the same sealed benchmark identity a second time; any later acceptance run must follow the ledger and the frozen-identity rules.

## Acceptance and Limitations

Mark each case/group verified / not verified / failed; all required groups need factual confirmation. Check both the absence of incorrectly accepted facts and useful completeness: refusing everything is not a successful product. Local resilience results can be recorded before the final Telegram E2E, but do not count as complete acceptance. Required cases include a partial table as the only field, a profile edited during matching or extraction (the job keeps its snapshot), cleanup when dependencies are unavailable, and cancellation racing with a send.

JSON schema, verbal confidence, model self-assessment, and quoted evidence do not replace an independent ground truth. The absence of files after ordinary success does not prove cleanup after a crash. Do not include document data in a public report.

Excluded: audit of compliance with all laws, document authenticity checks, guarantees for every language/document, and server SLA. Delivery is not declared accepted if the selected criteria fail; results are returned to the developer for a decision within the path of ADR-0004 and S-11-A1.
