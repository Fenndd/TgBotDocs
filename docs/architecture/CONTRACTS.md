# Processing Contracts

Status: v1 contract specification; consistency checked. The contracts are described without source code.

## Extraction Profile

A profile has a stable ID, owner, version, name and textual description of documents, original instruction, fields, and additional guidance. The document type is not limited to a coded passport/residence permit enum: the user may describe an invoice, certificate, contract, or another type.

The instruction compiler receives only the user instruction and the current editable schema, and returns a draft or questions. The draft contains the scope and fields with an ID, English label, description, and type. Instructions are accepted as free text without a language whitelist; an unrecognized instruction triggers clarification. Unsupported parts are not silently dropped. Saving is possible only after display and confirmation.

Scalar field types: text, date, number, boolean. A document number is text, not a number. A decimal number is stored in normalized form as an exact decimal string; currency is extracted separately if requested. A date is normalized only when unambiguous. A repeating set is a list of records with the specified scalar columns; arbitrary nested structures and calculated fields are outside v1 and are explicitly rejected in the preview.

For a list, each row contains scalar cell values/statuses and a source. The list container has a separate complete / partial / unresolved status and a flag indicating whether the row enumeration is complete. complete means the full set and resolved cells; partial allows read cells alongside unresolved ones or an incomplete enumeration; unresolved means there are no reliable rows/cells. unresolved has a reason: missing/unreadable/ambiguous/invalid.

Order corresponds to the document. Identical content in two actual rows is not considered a duplicate; duplicates are removed only when reprocessing the same source. If the association of a cell with a row is unclear, it is not returned as belonging to an invented row. An empty complete list is allowed only when the justified absence of records is established; an unreadable table does not become an empty list.

## Profile Matching and Document Identification

Input: prepared pages and immutable snapshots of the current profile versions belonging only to the current user. The selected ID is always tied to the version passed in this call; a newer version from the database is not substituted after the model response. Output:

| Status | Meaning | Action |
| --- | --- | --- |
| matched | The document matches one profile; its current ID is specified | Proceed to extraction |
| no_profile | There is a meaningful description of the type, but no suitable configuration | Request instructions and confirmation of a new profile |
| uncertain | The type or choice between profiles is ambiguous | Offer to clarify the type/profile or send another image |
| unreadable | There is not enough content for recognition | Request a better image |
| mixed | There are signs of different documents in one set | Ask the user to send the documents separately |
| not_document | The input was not recognized as a document | Explain the refusal |

An arbitrary type name from the model does not automatically create a new persistent profile. When two configurations are equally applicable, the model does not choose between them based on record order. A manual choice is marked as user-selected and does not increase field confidence.

The model ID is validated against the provided set and owner. Self-assessed confidence is not used as a probability or sole threshold.

## Result for Each Requested Field

Fields: field ID, status, raw value, normalized value when conversion is permitted, references to source pages, and a supporting text excerpt. Evidence exists only for the duration of the job.

| Status | Meaning |
| --- | --- |
| extracted | A value was obtained that passed the contract and applicable checks, with no detected conflict |
| missing | The field was not found in the available complete set; its absence is justified |
| unreadable | The value cannot be read, or its absence cannot be established because of quality/incompleteness |
| ambiguous | There are several incompatible values or an ambiguous interpretation |
| invalid | The candidate did not pass the format/type check; the UI must explain that reliable extraction is not possible |

For a scalar field or cell, there is no accepted value for statuses other than extracted. This rule does not prohibit read cells within a partial list. Do not force a value for a required field. Normalization of dates/numbers is allowed only when unambiguous; names and numbers are not corrected by guesswork, transliterated, or stripped of leading zeros.

The presence of an evidence excerpt traces the model response; it does not prove that the response is true. In tests, values are compared against independent ground truth. In operation, the extracted state means a recognition result, not verification of authenticity or identity.

## Checks Before Responding

Strict schema; only requested field IDs; allowed types and statuses; no extra values; real page IDs; consistency across pages; validity of unambiguous normalization. A conflict is not resolved by voting across identical model requests.

Do not use universal masks for document numbers without a basis in a specific profile. An expired document is not the same as a misrecognized date. Job outcome: complete when all requested scalars are resolved and all lists are complete; partial when there is at least one accepted scalar, cell, or confirmed empty list, but an unresolved item/incomplete list remains; failed when there is none of these results. A sole partially read list with an accepted cell gives the job a partial outcome, not failed.

## Batch Processing

Preparation covers all pages and is not limited to the first N pages. For large documents, the model receives resource-limited batches with page IDs; merging must not lose order, omissions, or conflicts. If the full pass is not completed, complete or confident missing cannot be returned.

A JSON error may trigger one retry with a clarified contract within the overall deadline. A retry does not increase confidence and does not launch a cloud model. If the contract is violated again, a technical error is returned; arbitrary model text is not sent to the user.
