# Processing Contracts

Status: v1 contract specification; revised on 2026-09-27 after the independent review (multi-type instructions, resolution and batch merging, verification signals, outcome semantics, result rendering). The contracts are described without source code.

## Extraction Profile

A profile has a stable ID, owner, version number, name and textual description of documents, original instruction, fields, and additional guidance. The document type is not limited to a coded passport/residence permit enum: the user may describe an invoice, certificate, contract, or another type.

The instruction compiler receives only the user instruction and, when editing, the current drafts; it never receives document pages or values read from them. It returns drafts or questions. One instruction may describe several document types (ED-001): the compiler returns one draft per described type, up to the configured maximum ([OPERATIONS](../operations/OPERATIONS.md)); an instruction that describes more types is answered with a request to split it. A draft contains a name, the applicability description, fields with an ID, English label, description, type, and optional validator, and additional guidance. Instructions are accepted as free text without a language whitelist; an unrecognized instruction triggers clarification. Unsupported parts are not silently dropped. All drafts from one instruction appear in one preview and are saved atomically after confirmation; later edits are per profile.

A validator is proposed only when the instruction states or clearly implies a format, such as a passport MRZ, an IBAN, a card number, or a calendar date. The preview shows it, and the user can remove it. There are no universal masks for document numbers.

Scalar field types: text, date, number, boolean. A document number is text, not a number. A decimal number is stored in normalized form as an exact decimal string; currency is extracted separately if requested. A date is normalized only when unambiguous. A repeating set is a list of records with the specified scalar columns; arbitrary nested structures and calculated fields are outside v1 and are explicitly rejected in the preview.

For a list, each row contains scalar cell values/statuses and a source. The list container has a separate complete / partial / unresolved status and a flag indicating whether the row enumeration is complete. complete means the full set and resolved cells; partial allows read cells alongside unresolved ones or an incomplete enumeration; unresolved means there are no reliable rows/cells. unresolved has a reason: missing/unreadable/ambiguous/invalid.

Order corresponds to the document. Identical content in two actual rows is not considered a duplicate; duplicates are removed only when reprocessing the same source. If the association of a cell with a row is unclear, it is not returned as belonging to an invented row. An empty complete list is allowed only when the justified absence of records is established; an unreadable table does not become an empty list.

## Profile Matching and Document Identification

Input: the matching view of the prepared pages and immutable in-memory snapshots of the current profiles that belong only to the current user. In the prompt, profiles are identified by per-call indices (1…N) that the application maps back to the snapshot, so the model never sees stored IDs. The selected index is bound to the snapshot passed in this call; a newer version from the database is not substituted after the model response. Output:

| Status | Meaning | Action |
| --- | --- | --- |
| matched | The document matches one profile; its current ID is specified | Proceed to extraction |
| no_profile | There is a meaningful description of the type, but no suitable configuration | Request instructions and confirmation of a new profile |
| uncertain | The type or choice between profiles is ambiguous | Offer to clarify the type/profile or send another image |
| unreadable | There is not enough content for recognition | Request a better image |
| mixed | There are signs of different documents in one set | Ask the user to send the documents separately |
| not_document | The input was not recognized as a document | Explain the refusal |

The matching view contains all pages when they fit one call at the matching resolution, which may be lower than the extraction resolution. Otherwise it contains the first pages that fit, in document order. For such longer documents, every extraction batch also reports for each page whether it belongs to the matched document: `yes`, `no`, or `unclear`. A page reported as `no` ends the job as `mixed`: the user is asked to send the documents separately, and no data is presented as the matched document's. `unclear` pages do not end the job.

An arbitrary type name from the model does not automatically create a new persistent profile. When two configurations are equally applicable, the model does not choose between them based on record order. A manual choice is marked as user-selected and does not increase field confidence.

The returned index is validated against the provided set. Self-assessed confidence is not used as a probability or sole threshold; automatic selection also requires the probability margin of the verification layer ([ADR-0004](../decisions/ADR-0004-abstention-and-verification.md)).

## Result for Each Requested Field

Fields: field ID, status, raw value, normalized value when conversion is permitted, and references to source pages. A supporting text excerpt is optional: it is enabled only if T01 shows that it improves accuracy, and it is never shown to the user. Evidence and verification-signal values exist only for the duration of the job.

| Status | Meaning |
| --- | --- |
| extracted | A value was obtained that passed the contract and applicable checks, with no detected conflict |
| missing | The field was not found in the available complete set; its absence is justified |
| unreadable | The value cannot be read, or its absence cannot be established because of quality/incompleteness |
| ambiguous | There are several incompatible values or an ambiguous interpretation |
| invalid | The candidate did not pass the format/type check; the UI must explain that reliable extraction is not possible |

For a scalar field or cell, there is no accepted value for statuses other than extracted. This rule does not prohibit read cells within a partial list. Do not force a value for a required field. Normalization of dates/numbers is allowed only when unambiguous; names and numbers are not corrected by guesswork, transliterated, or stripped of leading zeros.

Statuses reported by the model pass through the verification layer (ADR-0004), which can only downgrade them. Evidence traces the model response; it does not prove that the response is true. In tests, values are compared against independent ground truth. In operation, the extracted state means a recognition result, not verification of authenticity or identity.

## Resolution, Batches, and Merging

Preparation covers all pages and is not limited to the first N pages. Pages are rendered lazily, batch by batch, from the retained originals; a rendered page is deleted after its batch unless a verification signal needs it again.

The launch profile ([OPERATIONS](../operations/OPERATIONS.md)) fixes the per-image token budget, the PDF render resolution, and the context size; T01a selects them by measurement. An image above the budget is downscaled, never cropped. With about 144 KiB of f16 KV cache per token and one visual token per 32×32 px, a 6 GiB GPU is expected to fit only a few document pages per call; T01a measurements replace this estimate.

A batch contains consecutive pages in document order, as many as fit the context together with the prompt and a reserved output budget. Two sides of one card stay in one batch when they fit.

Scalar fields are merged across batches as follows. Readings are `extracted` values and the raw candidates of `invalid` statuses.

| Batch results for one field | Merged status |
| --- | --- |
| Any batch reports `ambiguous` | `ambiguous` |
| Two readings differ after permitted normalization | `ambiguous` (conflict) |
| At least one `extracted`, all readings agree, other batches report `missing` or `unreadable` | `extracted` |
| No `extracted`, at least one `invalid` | `invalid` |
| No readings, and at least one `unreadable` or an incomplete traversal | `unreadable` |
| Every batch reports `missing`, and the traversal is complete | `missing` |

Lists are merged as follows. Each batch receives the column schema and, when the list continues from the previous batch, the last row read there. A batch marks its first row `continues_previous` and its last row `continues_next` when a row visibly crosses the page boundary; two flagged halves are joined into one row. A flag without a counterpart, or conflicting cells, leaves the affected cells unresolved and makes the enumeration incomplete. Header, footer, and subtotal rows are not records unless the profile asks for them. Identical rows are not removed. Row order is batch order, then order within the batch. The list is complete only if every batch reports a complete enumeration and every continuation pair is joined; an empty list is complete only if every batch reports no rows with a complete enumeration.

If the full pass is not completed, complete or justified missing cannot be returned.

## Checks Before Responding

Strict schema; only requested field IDs; allowed types and statuses; no extra values; real page IDs; consistency across pages; validity of unambiguous normalization; verification signals. A conflict is not resolved by voting across identical model requests.

Do not use universal masks for document numbers without a basis in a specific profile. An expired document is not the same as a misrecognized date.

A scalar is resolved when it is `extracted` or justified `missing`; a list is resolved when it is complete, including a confirmed empty list. The job outcome is determined in this order:

1. `failed`: there is no accepted scalar, no accepted cell, and no confirmed empty list. This rule takes precedence, so a document in which every requested field is `missing` is `failed`, with the reason that none of the requested data is present.
2. `complete`: every scalar is resolved and every list is complete.
3. `partial`: any other result. A sole partially read list with an accepted cell gives the job a partial outcome, not failed.

A JSON error may trigger one retry with a clarified contract within the overall deadline. A retry does not increase confidence and does not launch a cloud model. If the contract is violated again, a technical error is returned; arbitrary model text is not sent to the user.

## User-Facing Result Rendering

The result is plain text with explicit message entities; no parse mode is used, so recognized characters cannot become formatting. Each value is sent inside a `code` entity, so Telegram does not turn it into a link, mention, or command, and link previews are disabled. Statuses use the labels of REQ-022: `missing` is shown as Missing, `unreadable` as Unreadable, `ambiguous` as Ambiguous, and `invalid` as Unreadable with the reason "did not pass the format check". A long result is split between fields or rows, never inside a value, into numbered messages of at most 4,096 characters after entity parsing.
