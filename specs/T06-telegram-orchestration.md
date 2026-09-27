# T06 — Telegram Flows, Queue, and Task Completion

Status: specification ready; execution after T02–T05. Date: 2026-09-27. No implementation is created in the planning session.

## Goal and Basis

Connect document intake, personal settings, sequential recognition, and English delivery of the result so cancellation/expiry/failure do not return a stale response or leave document contents behind.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-001/003–010/018–026; [USER_FLOWS](../docs/requirements/USER_FLOWS.md); [CONTRACTS](../docs/architecture/CONTRACTS.md); [DATA_MODEL](../docs/architecture/DATA_MODEL.md).

## Scope and Dependencies

- Depends on [T02](T02-application-foundation.md), [T03](T03-access-and-profiles.md), [T04](T04-document-intake.md), [T05](T05-recognition-pipeline.md), and the OPERATIONS rules.
- One bot instance, long polling, private chats, one active GPU task, an in-application queue, and one unfinished document per user.
- Access remains valid until /logout or restart. After restart, the password from the configuration must be entered again; an authorized session is not restored from the database.
- Collection/clarification expires after 15 minutes of inactivity; processing is limited to 30 minutes. Queue and delivery follow [OPERATIONS](../docs/operations/OPERATIONS.md); the values are configurable.

## Implementation Result

1. The user sees available actions and a clear task status. A file is not downloaded before login; a group does not receive results or the password flow.
2. The state machine distinguishes collection, queue, matching, waiting for a profile/clarification, extraction, delivery, and terminal outcomes. A transition checks the owner and task generation.
3. One matched profile continues processing; multiple matches prompt a choice. A new instruction goes through preview/confirm; saving the profile continues separately if the document has already expired and must be resubmitted.
4. The queue does not start cancelled/expired tasks. An error in one task does not break later tasks; the GPU is not used in parallel for classification, extraction, and profile conversion.
5. The English response contains only the selected fields/columns, values in the source writing system, and Missing/Unreadable/Ambiguous. A rejected invalid candidate is not printed as an established fact.
6. A long response is split into numbered messages without losing records. The status remains partial until delivery of all parts is confirmed; a retry does not silently create a second complete result.
7. Cancel and /logout end the active private flow according to the agreed rule. Cancellation invalidates pending callbacks/responses; the worker stops or completes/resets before the next GPU task.
8. Every terminal outcome starts cleanup of originals, prepared pages, intermediate text/results, and temporary Telegram IDs. Cleanup failure blocks a false message that cleanup has completed.
9. On restart, cleanup of leftovers runs before accepting new documents. Old buttons return Session expired, do not redownload the file or change a new task; saved profiles are available after login.

## Acceptance and Checks

- End-to-end scenarios for a single file, album, Several pages, missing/ambiguous profile, preview/confirm, partial/zero result, and long list.
- Two users and two consecutive tasks do not mix pages, profiles, callbacks, or responses; the owner's second document is processed only according to the explicit active-task rule.
- Check Cancel during collection, queueing, waiting, inference, and delivery. After cancellation is committed, no new sends/retries occur, and a late inference response is discarded. A send that has already started may be delivered: check the race with a lost acknowledgement, without promising message retraction.
- Check expiry, /logout, restart, unavailability of Telegram/model/database, and an error midway through delivery; do not report complete for a full result that was not sent.
- Confirm cleanup and absence of content in logs/backup for every terminal outcome; the profile remains separate from the temporary document.

## Completion Conditions and Exclusions

Queue/delivery timeout, activity, and logout policies are defined in OPERATIONS/USER_FLOWS. Scenarios receive actual automated/manual checks, including a Telegram test; there are currently no successful product checks.

Excluded: groups, webhook, multiple instances, durable document queue, background recovery of an old upload, broadcasts, or external actions based on recognized content.

