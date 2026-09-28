# T05 — Local Profile Matching and Extraction

Status: the recognition integration is implemented and checked locally with scripted model substitutes and in the product; see the [T05 progress report](../docs/testing/T05_PROGRESS_REPORT.md) and its linked [T06 real-model product run](../docs/testing/T06_PROGRESS_REPORT.md). Recognition quality remains unaccepted: the required shared sealed T01c/T07 benchmark is deferred. T01b remains frozen and T01c acceptance does not gate local implementation. Updated: 2026-09-28; specification revised after the independent review (recognition core from T01b, matching view, batch merging, verification layer).

## Goal and Basis

From a prepared, complete document, obtain only the fields and lists of records selected by the user, with explicit uncertainty, using a direct local Qwen3-VL-4B-Instruct GGUF Q4_K_M through llama.cpp. The task integrates the recognition core frozen in T01b with confirmed profiles and product intake.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-004–007/011–014/016/018/021/022/024/025; [CONTRACTS](../docs/architecture/CONTRACTS.md); [DATA_MODEL](../docs/architecture/DATA_MODEL.md); [ADR-0004](../docs/decisions/ADR-0004-abstention-and-verification.md).

## Scope and Dependencies

- [T01](T01-recognition-baseline.md) provides the frozen recognition core and configuration; [T03](T03-access-and-profiles.md) provides confirmed personal profiles; [T04](T04-document-intake.md) provides a complete ordered set of pages.
- Separate fields and lists of records with columns are supported: the list container and scalar cells have different statuses according to CONTRACTS.
- Documents in any language are accepted without a whitelist, with an honest refusal when they cannot be read (S-09-A1); all writing systems are not guaranteed, and values are not translated automatically.
- One GPU task; a 30-minute processing budget charged for the job's own work (ED-003), configurable. Retries/batches do not restart this budget.
- A separate OCR path, cloud, fine-tuning, and silent model changes are outside the selected approach; a local OCR cross-check is only an optional verification signal (ADR-0004).

## Implementation Result

1. Matching receives the matching view of the prepared pages and immutable in-memory snapshots of the owner's profiles, referred to by per-call indices; the statuses matched/no_profile/uncertain/unreadable/mixed/not_document are checked against the contract.
2. A returned index is checked against the provided set. An arbitrary type name does not create a profile; equal applicability or an insufficient verification margin prompts the user to choose.
3. A manual choice is recorded as user-selected and pins the snapshot; it does not increase confidence in field reading.
4. Extraction receives the original pages and the confirmed schema: separate fields and lists of records. Document text remains data, not instructions to the system.
5. The entire document is processed in lazy batches with page IDs. For documents longer than the matching view, every batch reports whether each page belongs to the matched document; a page that does not ends the job as `mixed`.
6. Batches are merged by the scalar table and the list continuation protocol of CONTRACTS. Merging preserves record order, provenance, and conflicting candidates; identical rows are not removed just because they look alike.
7. A status, original value, and page references are returned for every field/cell; a text excerpt only if T01 enabled it. Normalization is only unambiguous; names, numbers, and leading zeros are not corrected or translated by guesswork.
8. The verification layer applies the enabled signals with the frozen thresholds; they only downgrade statuses. The schema, requested IDs/columns, allowed statuses, types, page IDs, normalization, and conflicts are checked. An unresolved scalar/cell has no accepted value; a partial list may contain cells that were read.
9. Incomplete traversal cannot yield complete or justified missing. The job outcome follows the precedence of CONTRACTS. Invalid JSON allows one contract-compliant retry within the budget, then a technical refusal without returning raw model text.

## Acceptance and Checks

- Check all matching statuses, absence of configuration, two similar personal profiles, a foreign/non-existent index, manual selection, and a document longer than the matching view with a foreign page inside it.
- For a separate field and each list cell, check extracted/missing/unreadable/ambiguous/invalid against an independent ground truth, including absent columns and conflicts between pages.
- Every row of the scalar merge table and the list continuation protocol is covered: rows split across a batch boundary, a continuation flag without a counterpart, repeated headers, and an empty list across batches.
- Lists spanning multiple pages do not lose rows/columns; repeated real records do not disappear; incomplete traversal is explicitly reflected in the result.
- Each enabled verification signal only downgrades; it never upgrades a status or selects a value.
- Small text, phone-camera distortion, both delivery paths, another document type, and several writing systems are checked on an agreed sample; languages not checked are not declared supported with proven quality.
- JSON, verbal confidence, and evidence cited by the model are not considered proof of truth. A conflict is not resolved by voting across repeated model responses.
- Prompt injection inside a document does not change the profile, trigger external actions, or add unrequested fields.
- Check runtime unavailability, the processing budget, invalid response, cancellation, and late results; the next GPU task starts only after the previous call has completed or been reset.

## Completion Conditions and Exclusions

The list/language contract is defined; thresholds are in [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md). Successful T01 measurements are required. Test separately a profile with a single partially read table: the result is partial and readable cells are retained. Completion requires quality/contract/failure checks to pass, not just one successful JSON response.

Excluded: identity/authenticity/KYC verification, cloud fallback, a stronger server, JSON file export, persistent embeddings/ground truths from user uploads, and a promise of error-free results beyond the checked sample.
