# Acceptance Matrix and Experiment

Status: numerical criteria accepted by the user (S-09-A2); procedural details prepared for implementation and revised on 2026-09-28 to define the deferred shared T01c/T07 run. Product-wide quality acceptance remains pending; T01b calibration is complete.

## Why Several Stages

T01a verifies runtime feasibility and T01b calibrates and freezes the recognition core before integration ([T01](../../specs/T01-recognition-baseline.md)). T02–T08 may proceed after T01b freeze; this does not accept recognition quality. Defer benchmark preparation until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer. One sealed integrated 70-case run then satisfies both T01c recognition-quality acceptance and T07 integrated quality acceptance; do not run a separate core-only benchmark first. T07's local functional, isolation, cleanup, and resilience checks may proceed beforehand, but they do not complete acceptance. These quality checks do not replace checks for access, deletion, the database, and Telegram.

## Accepted Benchmark Set

- 40 readable documents of different types, layouts, and scripts.
- 20 difficult photographs: rotation, perspective, lighting, glare, blur, partial cropping.
- 10 negative cases: not a document, mixed documents, empty/unreadable input, ambiguous profile, conflict between sides, instruction inside a document, inaccessible PDF.

Categories for diversity: identity documents, invoices, receipts, certificates, contracts, applications/forms, letters, documents with repeating rows. This is a test plan, not an approved product catalog. The script matrix must include Latin, Cyrillic, Arabic, Chinese characters, Japanese script, and Devanagari; this is also not an input whitelist.

## Tuning Set and Sealed Benchmark

A separate tuning set of at least 20 cases is not part of the 70 benchmark cases; it covers every script, category, and quality class of the benchmark; the T01a development set may form part of it. Prompts, thresholds, verification signals ([ADR-0004](../decisions/ADR-0004-abstention-and-verification.md)), and parameters are developed on the tuning set only. An original document and its modified variants must not be split between tuning and the benchmark.

Before a benchmark run, versions, parameters, prompts, thresholds, and the set manifest with file hashes are frozen. The benchmark runs once per frozen configuration; failed cases must not be selectively removed from the report. Aggregate metrics may be read freely. A benchmark case whose individual failure details are examined to change prompts, thresholds, signals, or rules becomes a tuning case and is replaced with a new case of the same category, script, and quality class before the next acceptance run. This keeps the accepted 40/20/10 composition and prevents tuning to the benchmark.

## Delivery Paths

Telegram delivers a photo as a server-resized JPEG, at most 1,280 or 2,560 px on the longer side, and keeps the original only for files. Every case records its delivery path: photo, image file, or PDF. The readable set includes both image paths, and at least half of the difficult photographs use the photo path, because that is the default way to "just send a picture" (REQ-003). The deferred T01c/T07 integrated run records each delivery path and uses real delivery through the completed bot. Do not collect or seal benchmark cases through a separate preliminary Telegram test before the complete product is available.

## Data and Ground Truth

For T01, prepare synthetic documents without real personal data, public materials whose use is permitted, or separately authorized samples. Photos of synthetic documents may reproduce real-world photography. Purely digital distortions are not considered proof of quality on arbitrary photographs.

Each case has: ID, origin/permission, scenario type, language/script, delivery path, files/pages, instruction and expected profile, exact field/cell values, allowed status for an unreadable item, expected response.

Synthetic documents are generated from recorded values, so their ground truth exists by construction. A person reviews every case before measurement: the rendered or photographed document shows the intended values in the intended places, and the expected statuses match what is visible. For a script the reviewer cannot read, the review compares the glyph sequence with a reference rendering of the recorded value, and the case record names the method. Public materials use their published transcriptions. A case without a reliable review is excluded before measurement, never after.

Synthetic materials without PII may be retained in a future test set. Real documents are not put in Git; their retention period and storage location require permission consistent with the adopted policy. User uploads must not be automatically reused for training or testing.

## Criteria

| Criterion | Condition |
| --- | --- |
| Incorrectly accepted values | 0 across all 70 cases; comparison against independent ground truth |
| Incorrect automatic profile | 0; ambiguity requires clarification |
| Completeness on readable portions | At least 90% of requested, present fields/cells extracted correctly |
| Lists | No extra/missing/duplicate rows without an explicit partial result; cells are matched to the correct rows |
| Unreadable/missing fields | Not replaced with guesses; absence and inability to read are distinguished where this can be determined |
| Uncertainty | The bot is not required to guess the type of an unknown document; a correct clarification request does not count as an incorrect type |
| Contract | No extra fields, fabricated page IDs, or invalid accepted types |
| Functional scenarios | All required scenarios in the T03–T07 matrix pass |
| Deletion and isolation | Any leak/uncleaned remnant/cross-user access blocks acceptance |

To avoid getting a system that “always asks,” the automatic selection rate for unambiguous profiles is tracked separately; persistent clarification in a scenario with one obviously applicable profile counts as a functional-scenario violation. For a profile known to be absent in advance, `no_profile` is expected, not a fabricated match.

The zero-error criterion applies to the finite sample. It does not prove the absence of errors on all future documents. Metrics are shown overall and by language/script, type, quality, delivery path, scalar fields, and lists, so an overall figure does not hide a failing group. Every zero-error result is reported with its sample size: for N accepted values and no observed errors, the 95% upper bound on the error rate is about 3/N. This is reporting; the accepted thresholds are unchanged.

The completeness denominator is all requested, present scalar values and cells in the ground-truth rows across the 40 readable documents; omissions, refusals, and uncompleted jobs remain in the denominator. The numerator is those values accepted exactly correctly and matched to the correct row/page. Permitted normalization is specified in advance in the ground truth. An extra accepted row, incorrect row association, extra field, or incorrect normalization counts as an acceptance error, even if the text matches another fragment of the document.

Additional required scenarios: a single requested field with a partially readable table; a profile edited while its document is being matched or extracted, where the job keeps its snapshot and the change applies to later documents; restart with crash leftovers and an unavailable database/model; a race between Cancel and an already-started send with lost confirmation. These check contracts; they are not additional confirmed test results.

## Calibration and Risk–Coverage

T01b reports, on the tuning set, accepted-value errors and completeness as functions of the verification thresholds (risk–coverage curves), per signal and combined, and justifies the frozen operating point. The benchmark reports only the frozen point.

## Resources and Decision

On the verified PC, record model/quantization/mmproj, runtime version, context/image parameters, first and repeated processing times, p50/p95 on the set, per-page times by page kind and resolution, peak RAM/VRAM, timeouts, and failure rate. The per-page times feed admission control ([OPERATIONS](../operations/OPERATIONS.md)). Customer performance requirements are not yet known; measurements must not be relabeled as an SLA.

Failure to meet mandatory criteria means “test failed”: analyze errors on the tuning set and replaced cases, and revise within the permitted path on the current PC (ADR-0004, S-11-A1). The threshold must not be lowered retroactively, and neither cloud fallback nor a stronger server may be declared an internal optimization.
