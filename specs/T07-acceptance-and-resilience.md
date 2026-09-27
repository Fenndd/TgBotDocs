# T07 — Acceptance of Quality, Isolation, and Resilience

Status: specification ready; execution after T01–T06. Date: 2026-09-27; revised after the independent review (sealed benchmark, delivery paths, compiled profiles, zero-error bounds). Tests are not run in the planning session.

## Goal and Basis

Demonstrate with independent ground truths and reproducible failures that the selected product performs the agreed flows, honestly represents uncertainty, and deletes temporary data.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md); [TEST_STRATEGY](../docs/testing/TEST_STRATEGY.md); [USER_FLOWS](../docs/requirements/USER_FLOWS.md); [STATE_MACHINE](../docs/architecture/STATE_MACHINE.md); [CONTRACTS](../docs/architecture/CONTRACTS.md); [SECURITY](../docs/security/SECURITY.md).

## Scope and Dependencies

- Test integrated T02–T06 and the frozen [T01](T01-recognition-baseline.md) configuration, not responses from a separately run model. Profiles are compiled by the product's instruction compiler and confirmed through the preview, not the hand-authored fixtures of T01b.
- The sample and ground truths follow [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md): synthetic or authorized data, different documents/languages/layouts, phone photos, and recorded delivery paths through the real bot. User uploads do not become a permanent test archive.
- S-09-A2 is accepted: 40 readable + 20 difficult + 10 negative cases; 0 incorrectly accepted values/automatic profiles and at least 90% of requested readable fields/cells. The benchmark is sealed: cases examined for tuning after T01c are replaced before this run.
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
5. Nonconformity checklist with reproduction steps; fixes rerun affected scenarios, then the sealed final sample.

## Acceptance and Limitations

Mark each case/group verified / not verified / failed; all required groups need factual confirmation. Check both the absence of incorrectly accepted facts and useful completeness: refusing everything is not a successful product. Required cases include a partial table as the only field, a profile edited during matching or extraction (the job keeps its snapshot), cleanup when dependencies are unavailable, and cancellation racing with a send.

JSON schema, verbal confidence, model self-assessment, and quoted evidence do not replace an independent ground truth. The absence of files after ordinary success does not prove cleanup after a crash. Do not include document data in a public report.

Excluded: audit of compliance with all laws, document authenticity checks, guarantees for every language/document, and server SLA. Delivery is not declared accepted if the selected criteria fail; results are returned to the developer for a decision within the path of ADR-0004 and S-11-A1.
