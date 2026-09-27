# Acceptance Matrix and Experiment

Status: numerical criteria accepted by the user (S-09-A2); procedural details prepared for implementation. Product testing is not performed in this session.

## Why Two Stages

T01 checks the selected model on the current PC before integration. T07 checks completed user scenarios and repeats the quality check after integration. A positive T01 result does not replace checks for access, deletion, the database, and Telegram.

## Accepted Benchmark Set

- 40 readable documents of different types, layouts, and scripts.
- 20 difficult photographs: rotation, perspective, lighting, glare, blur, partial cropping.
- 10 negative cases: not a document, mixed documents, empty/unreadable input, ambiguous profile, conflict between sides, instruction inside a document, inaccessible PDF.

A separate small tuning set is not part of the 70 benchmark cases. An original document and its modified variants must not be split between tuning and the benchmark. After tuning, the versions, parameters, prompts, and set manifest are fixed; failed cases must not be selectively removed from the report.

Categories for diversity: identity documents, invoices, receipts, certificates, contracts, applications/forms, letters, documents with repeating rows. This is a test plan, not an approved product catalog. The script matrix must include Latin, Cyrillic, Arabic, Chinese characters, Japanese script, and Devanagari; this is also not an input whitelist.

## Data and Ground Truth

For T01, prepare synthetic documents without real personal data, public materials whose use is permitted, or separately authorized samples. Photos of synthetic documents may reproduce real-world photography. Purely digital distortions are not considered proof of quality on arbitrary photographs.

Each case has: ID, origin/permission, scenario type, language/script, files/pages, instruction and expected profile, exact field/cell values, allowed status for an unreadable item, expected response. Documented ground truth is reviewed by a person before model measurement.

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

The zero-error criterion applies to the finite sample. It does not prove the absence of errors on all future documents. Metrics are shown overall and by language/script, type, quality, scalar fields, and lists, so an overall figure does not hide a failing group.

The completeness denominator is all requested, present scalar values and cells in the ground-truth rows across the 40 readable documents; omissions, refusals, and uncompleted jobs remain in the denominator. The numerator is those values accepted exactly correctly and matched to the correct row/page. Permitted normalization is specified in advance in the ground truth. An extra accepted row, incorrect row association, extra field, or incorrect normalization counts as an acceptance error, even if the text matches another fragment of the document.

Additional required scenarios: a single requested field with a partially readable table; a profile description changed during matching; restart with crash leftovers and an unavailable database/model; a race between Cancel and an already-started send with lost confirmation. These check contracts; they are not additional confirmed test results.

## Resources and Decision

On the verified PC, record model/quantization/mmproj, runtime version, context/image parameters, first and repeated processing times, p50/p95 on the set, peak RAM/VRAM, timeouts, and failure rate. Customer performance requirements are not yet known; measurements must not be relabeled as an SLA.

Failure to meet mandatory criteria means “test failed”: analyze errors and agree on a revision to the configuration/model/architecture. The threshold must not be lowered retroactively or cloud fallback declared an internal optimization.
