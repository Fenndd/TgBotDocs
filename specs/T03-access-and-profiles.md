# T03 — Access and Personal Extraction Profiles

Status: specification ready; execution after T02. Date: 2026-09-27; revised after the independent review (multi-type instructions, optimistic versions, Settings during an active job, access hardening). Code and environment are not created in the planning session.

## Goal and Basis

An authorized user creates personal profiles from an ordinary instruction, reviews a preview, and confirms saving. A profile defines applicability, fields/lists, optional validators, and instructions; there is no closed built-in catalog.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-004–006/009/010/018/021/027/029/030. Dependencies: [T02](T02-application-foundation.md), [USER_FLOWS](../docs/requirements/USER_FLOWS.md), [STATE_MACHINE](../docs/architecture/STATE_MACHINE.md), [CONTRACTS](../docs/architecture/CONTRACTS.md), [DATA_MODEL](../docs/architecture/DATA_MODEL.md), [OPERATIONS](../docs/operations/OPERATIONS.md), [SECURITY](../docs/security/SECURITY.md).

## Scenarios and Boundaries

1. In a private chat, /start requests the shared password from the configuration. Until the correct response, there is no download, inference, or settings access. The comparison is constant-time, and the password message is deleted. Per-user attempt limits apply, and a global surge alerts the operator; login remains active until restart/logout, and a new password takes effect after restart.
2. The user sends an ordinary instruction. It defines the data to extract, not commands, external access, or a retention policy.
3. The selected local VLM returns drafts, one per described document type up to the configured maximum. Each draft has a name, document description, scalar fields and lists of records with columns, optional validators, and additional instructions. Unclear parts are clarified, not silently discarded; an instruction with too many types is answered with a request to split it.
4. One preview shows the full interpretation of all drafts. Save confirms all of them; Edit changes the drafts; Cancel does not change saved data. A draft in RAM expires after 15 minutes of inactivity, at the end of its job, or on restart.
5. Saving is atomic: all drafts of one preview or none. Repeated confirmation does not create duplicates. An edit is saved only if the previewed version is still current, so a stale preview does not overwrite a newer version.
6. Viewing, editing, and deletion are available only to the owner. Deletion requires explicit confirmation. While the document job waits for the user's answer, Settings is view-only; while it is queued or processed, profiles can be changed, and the job keeps its snapshot (S-13-A1, STATE_MACHINE).
7. Before document matching, in-memory snapshots of the candidate profiles are taken. The index returned by the model is linked to the snapshot; a new schema must not be substituted from the database after matching.
8. If a profile is missing/ambiguous, the same compile/preview dialogue runs inside the job flow (STATE_MACHINE). If the job ends while the preview is open, the drafts are discarded; profiles can be created from Settings when no job is active.

Saved profiles remain until they are deleted; documents and extracted values are not copied into them, and previous versions are not retained. Profile selection/matching is integrated in T05/T06; T03 provides confirmed settings and interfaces.

## Result and Checks

- Migrations contain User and ExtractionProfile with a version number according to DATA_MODEL; passport values are not present in the storage schema.
- Two users have fully isolated list/view/edit/preview/confirm/select/delete operations; using another user's ID is rejected without revealing their data.
- Incorrect password, per-user lockout, the global-surge alert, deletion of the password message, access before password entry, logout, new login/restart, and password change are checked.
- The preview does not add unrequested fields; instructions for a list include the required columns; unsupported nesting/calculations are explained explicitly; a validator appears only when the instruction implies the format.
- An instruction that covers two document types, such as the passport and residence permit example of the source brief, yields two drafts in one preview and two profiles after Save.
- Transaction failure, double confirmation, and stale preview do not result in partial saving or loss of a newer version.
- A profile changed or deleted while a job is queued, matching, or extracting affects only later documents, and the job keeps its snapshot; a change attempted while the job waits for an answer is refused; a job question that arises while a draft is open is deferred until the draft is closed.
- After restart, profiles are retained and sessions/drafts are absent; document contents and secrets are absent from profiles, logs, and backup.
- Actual tests and commands are recorded after they are run in the development task.

## Exclusions

General settings/admin roles, web portal, JSON import/export, dialogue archive, profile history, customer server, and full recognition implementation are out of scope. A structural contract does not prove that the model correctly understood an instruction: this is checked with examples and confirmed by the user in the interface.
