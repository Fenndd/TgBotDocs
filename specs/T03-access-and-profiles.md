# T03 — Access and Personal Extraction Profiles

Status: specification ready; execution after T02. Date: 2026-09-27. Code and environment are not created in the planning session.

## Goal and Basis

An authorized user creates personal profiles from an ordinary instruction, reviews a preview, and confirms saving. A profile defines applicability, fields/lists, and instructions; there is no closed built-in catalog.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-004–006/009/010/018/021/027/029/030. Dependencies: [T02](T02-application-foundation.md), [USER_FLOWS](../docs/requirements/USER_FLOWS.md), [CONTRACTS](../docs/architecture/CONTRACTS.md), [DATA_MODEL](../docs/architecture/DATA_MODEL.md), [OPERATIONS](../docs/operations/OPERATIONS.md).

## Scenarios and Boundaries

1. In a private chat, /start requests the shared password from .env. Until the correct response, there is no download, inference, or settings access. Attempt limits apply; login remains active until restart/logout, and a new password takes effect after restart.
2. The user sends an ordinary instruction. It defines the data to extract, not commands, external access, or a retention policy.
3. The selected local VLM returns a draft: name, document description, scalar fields and lists of records with columns, and additional instructions. Unclear parts are clarified, not silently discarded.
4. Preview shows the full interpretation. Save confirms; Edit changes the draft; Cancel does not change saved data. A draft in RAM expires after 15 minutes of inactivity and does not survive restart.
5. Saving a new version is atomic. Repeated confirmation does not create a duplicate. A stale preview does not overwrite a newer version.
6. Viewing, editing, and deletion are available only to the owner. Deletion requires explicit confirmation and deletes saved versions; an assigned job continues with its temporary snapshot or is canceled by the user. Separate deactivation is not needed.
7. Before document matching, the candidate versions are fixed, including descriptions, fields, and instructions. The model ID is linked to the version provided; a new schema must not be substituted from the database after matching.
8. If a profile is missing/ambiguous, the same dialogue is used. A setting can still be saved after the document expires, but processing requires a new upload.

Saved setting versions remain until the profile is deleted; documents and extracted values are not copied into them. Profile selection/matching is integrated in T05/T06; T03 provides confirmed settings and interfaces.

## Result and Checks

- Migrations contain User, ExtractionProfile, and immutable ProfileRevision according to DATA_MODEL; passport values are not present in the storage schema.
- Two users have fully isolated list/view/edit/preview/confirm/select/delete operations; using another user's ID is rejected without revealing their data.
- Incorrect password, brute-force lockout, access before password entry, logout, new login/restart, and password change are checked.
- The preview does not add unrequested fields; instructions for a list include the required columns; unsupported nesting/calculations are explained explicitly.
- Transaction failure, double confirmation, and stale preview do not result in partial saving or loss of a newer version.
- Editing descriptions/fields during matching and extraction does not mix versions. Deletion before assignment and after assignment are checked separately.
- After restart, profiles are retained and sessions/drafts are absent; document contents and secrets are absent from profiles, logs, and backup.
- Actual tests and commands are recorded after they are run in the development task.

## Exclusions

General settings/admin roles, web portal, JSON import/export, dialogue archive, customer server, and full recognition implementation are out of scope. A structural contract does not prove that the model correctly understood an instruction: this is checked with examples and confirmed by the user in the interface.
