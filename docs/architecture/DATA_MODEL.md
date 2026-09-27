# Data Model

Status: v1 model for personal profiles and temporary documents; profile storage simplified on 2026-09-27 (ED-007). Field types are in [contracts](CONTRACTS.md); states and timers are in the [state machine](STATE_MACHINE.md) and the [operating model](../operations/OPERATIONS.md).

## Persistent PostgreSQL Data

| Entity | Contents | Invariants |
| --- | --- | --- |
| User | Telegram user ID, creation time | The identifier is needed as the profile owner; name, phone number, and username are not needed |
| ExtractionProfile | UUID, owner ID, version number, name, description of applicable documents, original instruction, field schema with optional validators, additional guidance, creation and update times | Always belongs to one user; is not a global document type; the version number increases with every saved change |
| Schema migration | Database schema version | Migrations are reproducible and do not require copying documents |

A profile change is saved only if the version the user previewed is still current (optimistic concurrency): the update succeeds only when the stored version equals the previewed one, and it increments the version in the same transaction. A stale preview does not overwrite a newer change: the bot asks the user to open the current profile. Drafts produced from one instruction (ED-001) are inserted in one transaction: all or none. Repeated confirmation of the same preview does not create duplicates.

Previous versions are not retained. No feature reads profile history, and keeping old versions would preserve text that the user deliberately removed. A job uses immutable in-memory snapshots of the candidate profiles, taken before matching; the model response is bound to that snapshot, the same snapshot is shown during clarification, and later database changes do not affect the job. Jobs do not survive a restart, so snapshots need no persistent storage.

Profiles can be changed while a document job is queued or being processed, but not while the job waits for the user's answer (S-13-A1). A job takes its snapshot when its matching starts; a later change or deletion affects only later documents, and a job already assigned to a deleted profile finishes with its snapshot. A profile created for the current document inside the job flow is saved the same way and applied to that document as user-selected. Deleting a profile deletes its row. Separate deactivation is not introduced in v1.

An unconfirmed draft is stored only in RAM until Cancel, restart, the end of its job, or 15 minutes of inactivity. A dedicated operation to delete document history is not needed: there is no persistent history.

For the login option that lasts until restart, the authenticated session and password are not stored in the database. The password comes from local configuration; it must not be stored in documentation.

## Temporary Job Data

In RAM: authenticated sessions, dialogue, file list and their temporary Telegram IDs, queue, profile snapshots, candidate fields, verification-signal values, results, and delivery states. On disk: originals and prepared pages in a separate job directory with a random name. Original filenames are not used as paths. Pages are rendered per batch and deleted after use ([CONTRACTS](CONTRACTS.md)).

`Submission` contains one logical document made up of files; a PDF file may contain multiple pages. The order is determined by the order in which files are sent, and within a PDF by page order. An album is ordered by message ID. A stable page ID preserves the file/page correspondence and does not change during re-preparation.

Every operation checks owner ID: it is not possible to retrieve a profile, confirm a callback, add a page, cancel, or read another user's result. An external profile ID by itself is not authorization.

## Prohibitions

- Do not store source documents, OCR, extracted fields, evidence, or result history in PostgreSQL.
- Do not copy values read from a document into a profile as examples.
- Do not build a permanent database of reference images/embeddings from user documents.
- Do not save file IDs to resume processing after a restart.
- Do not treat a database backup as a way to archive documents.

A profile may contain sensitive text entered by the user; the preview must explicitly show the settings being saved. This does not authorize automatically transferring the contents of an uploaded document into the settings.
