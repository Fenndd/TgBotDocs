# Data Model

Status: v1 model for personal profiles and temporary documents. Field types are in [contracts](CONTRACTS.md); waiting rules are in the [operating model](../operations/OPERATIONS.md).

## Persistent PostgreSQL Data

| Entity | Contents | Invariants |
| --- | --- | --- |
| User | Telegram user ID, creation time | The identifier is needed as the profile owner; name, phone number, and username are not needed |
| ExtractionProfile | UUID, owner ID, reference to the current revision, dates | Always belongs to one user; is not a global document type |
| ProfileRevision | profile ID, version, name, description of applicable documents, original instruction, field schema, additional guidance, time | The entire revision is immutable after saving; matching and extraction use the same snapshot |
| Schema migration | Database schema version | Migrations are reproducible and do not require copying documents |

Updating a profile and switching its revision are performed in one transaction. Before job matching, a snapshot of candidate revisions is fixed; a model response with an ID is bound specifically to the revision passed in. The same revision is shown during clarification. Later edits do not change the scope or fields of the current job.

A stale preview conflict does not overwrite a newer change: the bot asks the user to open the current profile. Deleting a profile deletes its saved revisions; an already assigned job finishes with its temporary snapshot or is canceled by the user. If a profile is deleted before assignment, the selection is refreshed and clarified without silently applying the deleted configuration. Separate deactivation is not introduced in v1.

Saved configuration revisions remain until the profile is deleted. An unconfirmed draft is stored only in RAM until Cancel/restart or 15 minutes of inactivity. A dedicated operation to delete document history is not needed: there is no persistent history.

For the login option that lasts until restart, the authenticated session and password are not stored in the database. The password comes from local configuration; it must not be stored in documentation.

## Temporary Job Data

In RAM: authenticated sessions, dialogue, file list and their temporary Telegram IDs, queue, selected profile revision, candidate fields, results, and delivery states. On disk: originals and prepared pages in a separate job directory with a random name. Original filenames are not used as paths.

`Submission` contains one logical document made up of files; a PDF file may contain multiple pages. The order is determined by the order in which files are sent, and within a PDF by page order. An album is ordered by message ID. A stable page ID preserves the file/page correspondence and does not change during re-preparation.

Every operation checks owner ID: it is not possible to retrieve a profile, confirm a callback, add a page, cancel, or read another user's result. An external profile ID by itself is not authorization.

## Prohibitions

- Do not store source documents, OCR, extracted fields, evidence, or result history in PostgreSQL.
- Do not copy values read from a document into a profile as examples.
- Do not build a permanent database of reference images/embeddings from user documents.
- Do not save file IDs to resume processing after a restart.
- Do not treat a database backup as a way to archive documents.

A profile may contain sensitive text entered by the user; the preview must explicitly show the settings being saved. This does not authorize automatically transferring the contents of an uploaded document into the settings.
