# T07 — Acceptance of Quality, Isolation, and Resilience

Status: specification ready; execution after T01–T06. Date: 2026-09-27. Tests are not run in the planning session.

## Goal and Basis

Demonstrate with independent ground truths and reproducible failures that the selected product performs the agreed flows, honestly represents uncertainty, and deletes temporary data.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md); [TEST_STRATEGY](../docs/testing/TEST_STRATEGY.md); [USER_FLOWS](../docs/requirements/USER_FLOWS.md); [CONTRACTS](../docs/architecture/CONTRACTS.md); [SECURITY](../docs/security/SECURITY.md).

## Scope and Dependencies

- Test integrated T02–T06 and the measured [T01](T01-recognition-baseline.md) baseline, not responses from a separately run model.
- Agree on the sample and ground truths in advance: synthetic or authorized data, different documents/languages/layouts, and phone photos. User uploads do not become a permanent test archive.
- S-09-A2 is accepted: 40 readable + 20 difficult + 10 negative cases; 0 incorrectly accepted values/automatic profiles and at least 90% of requested readable fields/cells. Denominators and procedure are in [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md).
- Any language is accepted without a whitelist, with honest uncertainty; the test set does not prove support for all writing systems. Specific materials and ground truths are created/checked in T01.

## Verification Matrix

| Area | Required cases | Expected outcome |
| --- | --- | --- |
| Intake and pages | PNG/JPEG/PDF, two sides, Several pages, album/late fragment | Complete order/source, no hidden cropping |
| Type/profile | One/multiple/no profile, unknown/mixed/non-document | Correct transition or clarification; another user's profile excluded |
| Fields and lists | Separate fields, rows across pages, leading zeros, dates | Requested items only; exact ground truths/statuses/columns |
| Uncertainty | Missing, glare/cropping, ambiguous characters, conflicting sides | Missing does not replace unreadable; conflict does not become fact |
| Access/isolation | Before password, another user's ID/callback, two owners, logout | No download/leak/unauthorized change |
| Failures | Model/DB/Telegram unavailable, invalid JSON, timeout, parser error | Clear error, queue continues, no stale response |
| Life cycle | Cancel at every stage, TTL, crash/restart, partial delivery | Cleanup, new login, profiles retained, document resubmitted |
| Leaks | Logs, backup, PostgreSQL, temp, model logs | No originals/OCR/fields/evidence/secrets outside the permitted lifecycle |

## Implementation Result

1. Versioned list of permitted test cases and independent ground truths; separate prompt-tuning examples from the final sample.
2. Actual verification commands/scenarios for the future project with pinned versions, configuration, results, and known untested cases.
3. Separate report of incorrectly accepted values, refusals/missing values, correct fields/cells, incorrect profiles, and fully successful documents; state the exact denominator for every metric.
4. Measurements of memory/time on the PC, resilience across sequential tasks, and cleanup under simulated failures. No conclusions about the customer's unknown multi-user workload.
5. Nonconformity checklist with reproduction steps; fixes rerun affected scenarios, then the agreed final sample.

## Acceptance and Limitations

Mark each case/group verified / not verified / failed; all required groups need factual confirmation. Check both the absence of incorrectly accepted facts and useful completeness: refusing everything is not a successful product. Required cases include a partial table as the only field, profile version change during matching, cleanup when dependencies are unavailable, and cancellation racing with a send.

JSON schema, verbal confidence, model self-assessment, and quoted evidence do not replace an independent ground truth. The absence of files after ordinary success does not prove cleanup after a crash. Do not include document data in a public report.

Excluded: audit of compliance with all laws, document authenticity checks, guarantees for every language/document, and server SLA. Delivery is not declared accepted if the selected criteria fail; results are returned to the user for a decision.

