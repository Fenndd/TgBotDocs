# ADR-0004. Abstention and Verification Layer

Date: 2026-09-27. Status: accepted engineering decision under [S-10-A4](../requirements/SOURCES.md); the developer can override it. Basis: REQ-013, REQ-022, REQ-031; [S-06-A2, S-09-A2, S-11-A1](../requirements/SOURCES.md).

## Context

The accepted criteria require zero incorrectly accepted values and zero incorrect automatic profiles across 70 cases, with at least 90% completeness on the readable part. Any OCR or VLM system misreads some values, so both criteria can hold together only if the system withholds exactly the values it would get wrong. Without a dedicated mechanism, withholding depends on the statuses the model reports about itself. The self-assessment of a 4B quantized model is not calibrated, and a prompt that asks for caution moves errors and completeness together without a controllable operating point.

A zero-error result on a finite sample is also a weak bound. With N accepted values and no observed errors, the 95% upper bound on the error rate is about 3/N; a system passes with even odds only if its true error rate is below about 0.7/N. For N = 400 these are 0.75% and 0.17%.

## Decision

1. A verification layer sits between the model output and the job result. Its signals can only downgrade a candidate: `extracted` to `ambiguous` or `invalid`, `matched` to `uncertain`. A signal never upgrades a status, never chooses between conflicting values, and does not prove a value correct. The existing rules stay: no voting across identical requests, and a retry does not increase confidence.
2. Candidate signals; each is enabled only if it improves the trade-off on the tuning set:

| ID | Signal | Downgrade | Cost |
| --- | --- | --- | --- |
| V1 | Raw (pre-sampling) token probabilities over the value span: the weakest token is below a threshold | `ambiguous` | Response metadata only |
| V2 | Second reading with a different view: a higher-resolution crop when the model can localize the value, otherwise the page at another resolution; the readings differ after permitted normalization | `ambiguous` | One more model call per checked field or page |
| V3 | Format validator declared in the profile only when the user's instruction states or clearly implies the format: check digits (MRZ, Luhn), IBAN mod-97, calendar-valid date, ISO codes | `invalid` | None |
| V4 | Agreement across pages and batches under the merge rules of [CONTRACTS](../architecture/CONTRACTS.md) | `ambiguous` | None |
| V5 | Local OCR cross-check within the PC's resources: the OCR text of the page does not contain the normalized value | `ambiguous` | Extra memory and time; considered only if V1–V4 are insufficient |

For profile matching, automatic selection requires one candidate with a probability margin above a threshold; otherwise the status is `uncertain`, and the user chooses.

3. Thresholds and the set of enabled signals are calibrated on the tuning set, never on the benchmark. They are frozen together with prompts, versions, and parameters before the benchmark run.
4. T01 reports risk–coverage curves on the tuning set: accepted-value errors and completeness as functions of the thresholds, per signal and combined. The benchmark reports only the frozen operating point.
5. If T01 fails, remediation follows S-11-A1 in this order, all on the current PC: (1) tune the configuration — image token budget, render resolution, KV-cache type, batch size, prompts; (2) enable more signals, including V2 and V5; (3) compare other self-hosted models that fit 6 GiB VRAM and 16 GiB RAM under the same contract. When these options are exhausted, the developer decides whether to narrow the v1 scope or revise the criteria; that decision precedes the next measurement and is never applied retroactively. External AI, a stronger GPU server, and a hidden fallback are excluded.

## Consequences

- The model adapter requests token probabilities. T01a verifies that the pinned llama.cpp build returns images, schema-constrained output, streaming, and probabilities together; if probabilities are unavailable, V1 is dropped and the report says so.
- Signal values are internal job data: they are not shown to users, not logged with content, and deleted with the job.
- V2 and V5 increase processing time per document; admission estimates (ED-002) use the measured rate of the frozen configuration.
- Evidence excerpts stay internal and optional; T01 measures whether they improve accuracy.
- Acceptance reports state N and the zero-error bound for every group. The signals reduce the chance of accepting a wrong value; a finite-sample result keeps its limited meaning.

## Options Not Selected

- Model self-reported statuses only: no controllable operating point.
- Majority voting across repeated identical requests: errors are correlated, and the contract forbids resolving conflicts by voting.
- A mandatory separate OCR pipeline from the start: memory and latency cost without evidence of need; kept as the optional V5.
- Showing unverified candidates as "possible readings": conflicts with the no-guesses rule (S-06-A2) and would need a developer decision.

## Measured Update (2026-09-28, development diagnostics)

On the unreviewed synthetic tuning set, the matching margin over profile-index token probabilities did not withhold any wrong automatic selection: the model chose wrong profiles for a blank page, identical profiles, a document without a suitable profile, and a two-sided card with index probabilities of 0.94–1.0. Following remediation step 1, the matching prompt was changed (describe the document first, field labels, explicit status rules; ED-015); a full diagnostic run with prompt version t01b-3 then showed no wrong automatic selection at any margin, and its best zero-error point (V1 0.7 with V2) reached 0.907 readable completeness. The margin stays a calibrated parameter; a profile-order permutation check was evaluated and not enabled because it did not improve the trade-off. V1 separated the observed misreadings (mostly Arabic diacritics) from correct values. These are diagnostics, not calibration: the tuning set's human review is still pending.
