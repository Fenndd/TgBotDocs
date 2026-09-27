# T05 — Local Profile Matching and Extraction

Status: specification ready; execution after T01/T03/T04. Date: 2026-09-27. No implementation is created in the planning session.

## Goal and Basis

From a prepared, complete document, obtain only the fields and lists of records selected by the user, with explicit uncertainty, using a direct local Qwen3-VL-4B-Instruct GGUF Q4_K_M through llama.cpp.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-004–007/011–014/016/018/021/022/024/025; [CONTRACTS](../docs/architecture/CONTRACTS.md); [DATA_MODEL](../docs/architecture/DATA_MODEL.md).

## Scope and Dependencies

- [T01](T01-recognition-baseline.md) tests the baseline; [T03](T03-access-and-profiles.md) provides confirmed personal profiles; [T04](T04-document-intake.md) provides a complete ordered set of pages.
- Separate fields and lists of records with columns are supported: the list container and scalar cells have different statuses according to CONTRACTS.
- Documents in any language are accepted without a whitelist, with an honest refusal when they cannot be read (S-09-A1); all writing systems are not guaranteed, and values are not translated automatically.
- One GPU task, 30-minute overall processing limit, configurable. Retries/batches do not restart this limit.
- OCR/hybrid, cloud, fine-tuning, and silent model changes are outside the selected approach.

## Implementation Result

1. Matching receives the original prepared pages and immutable snapshots of the owner's profile versions; the statuses matched/no_profile/uncertain/unreadable/mixed/not_document are checked against the contract. A profile change during matching does not change the version passed in.
2. A returned model profile ID is checked against the owner and the allowed list. An arbitrary type name does not create a profile; equal applicability prompts the user to choose.
3. A manual choice is recorded as user-selected and pins a version snapshot; it does not increase confidence in field reading.
4. Extraction receives the original pages and the confirmed schema: separate fields and lists of records. Document text remains data, not instructions to the system.
5. The entire document is processed in batches with page IDs. Merging preserves record order, provenance, and conflicting candidates; identical rows are not removed just because they look alike.
6. A status, original value, and temporary page-level evidence are returned for every field/cell. Normalization is only unambiguous; names, numbers, and leading zeros are not corrected or translated by guesswork.
7. The schema, requested IDs/columns, allowed statuses, types, page IDs, normalization, and conflicts are checked. An unresolved scalar/cell has no accepted value; a partial list may contain cells that were read.
8. Incomplete traversal cannot yield complete or justified missing. Invalid JSON allows one contract-compliant retry within the overall deadline, then a technical refusal without returning raw model text.

## Acceptance and Checks

- Check all matching statuses, absence of configuration, two similar personal profiles, a foreign/non-existent ID, and manual selection.
- For a separate field and each list cell, check extracted/missing/unreadable/ambiguous/invalid against an independent ground truth, including absent columns and conflicts between pages.
- Lists spanning multiple pages do not lose rows/columns; repeated real records do not disappear; incomplete traversal is explicitly reflected in the result.
- Small text, phone-camera distortion, another document type, and several writing systems are checked on an agreed sample; languages not checked are not declared supported with proven quality.
- JSON, verbal confidence, and evidence cited by the model are not considered proof of truth. A conflict is not resolved by voting across repeated model responses.
- Prompt injection inside a document does not change the profile, trigger external actions, or add unrequested fields.
- Check runtime unavailability, the 30-minute limit, invalid response, cancellation, and late results; the next GPU task starts only after the previous call has completed or been reset.

## Completion Conditions and Exclusions

The list/language contract is defined; thresholds are in [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md). Successful T01 measurements are required. Test separately a profile with a single partially read table: the result is partial and readable cells are retained. Completion requires quality/contract/failure checks to pass, not just one successful JSON response.

Excluded: identity/authenticity/KYC verification, cloud fallback, JSON file export, persistent embeddings/ground truths from user uploads, and a promise of error-free results beyond the checked sample.

