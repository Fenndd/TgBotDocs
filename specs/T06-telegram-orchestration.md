# T06 — Telegram Flows, Queue, and Task Completion

Status: implementation and local checks are complete with controlled Telegram substitutes; one functional product run used the frozen model and real PostgreSQL. No real Telegram request was made; the joint real-Telegram E2E remains pending. See the [T06 progress report](../docs/testing/T06_PROGRESS_REPORT.md). Recognition quality remains unaccepted pending the deferred shared sealed T01c/T07 benchmark; the frozen recognition source and configuration are unchanged. Updated: 2026-09-28; specification revised after the independent review (state machine, scheduler priorities, admission, stale updates, rendering, operator alerts).

## Goal and Basis

Implement the complete [STATE_MACHINE](../docs/architecture/STATE_MACHINE.md): connect document intake, personal settings, sequential recognition, and English delivery of the result so cancellation/expiry/failure do not return a stale response or leave document contents behind.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-001/003–010/018–026; [USER_FLOWS](../docs/requirements/USER_FLOWS.md); [CONTRACTS](../docs/architecture/CONTRACTS.md); [DATA_MODEL](../docs/architecture/DATA_MODEL.md).

## Scope and Dependencies

- Depends on [T02](T02-application-foundation.md), [T03](T03-access-and-profiles.md), [T04](T04-document-intake.md), [T05](T05-recognition-pipeline.md), and the [OPERATIONS](../docs/operations/OPERATIONS.md) rules.
- One bot instance, long polling, private chats, one active GPU task, an in-application queue, and one unfinished document per user.
- Access remains valid until /logout or restart. After restart, the password from the configuration must be entered again; an authorized session is not restored from the database.
- Collection/clarification expires after 15 minutes of inactivity; the processing budget is 30 minutes of the job's own work. Admission, queue, and delivery follow STATE_MACHINE and OPERATIONS; the values are configurable.

## Implementation Result

1. The user sees available actions and a clear task status. A file is not downloaded before login and admission; a group does not receive results or the password flow.
2. Every session and job state, timer, and transition of STATE_MACHINE is implemented by the per-user actors; a transition checks the owner, task generation, and session nonce.
3. One matched profile continues processing; multiple matches prompt a choice. A new instruction goes through the compile/preview/confirm steps; one new profile is applied directly, several prompt a choice. Settings and a job overlap under the rules of STATE_MACHINE (S-13-A1): Settings is view-only while the job waits for the user, and a job question is deferred while a Settings draft is open.
4. The scheduler runs interactive calls first, then gives active documents turns, one model call each, in admission order (S-12-A1); it does not start cancelled/expired tasks. An error in one task does not break later tasks; the GPU is not used in parallel for classification, extraction, and profile conversion.
5. Admission answers Busy before download when all job slots are taken and refuses sets that cannot finish within the budget.
6. The English response contains only the selected fields/columns, values in the source writing system as `code` entities without link previews, and Missing/Unreadable/Ambiguous. A rejected invalid candidate is shown as Unreadable with its reason, never as an established fact.
7. A long response is split into numbered messages without losing records. The status remains partial until delivery of all parts is confirmed; a retry does not silently create a second complete result.
8. Cancel and /logout end the active private flow according to the agreed rule. Cancellation invalidates pending callbacks/responses; the worker stops or completes/resets before the next GPU task.
9. Every terminal outcome starts cleanup of originals, prepared pages, intermediate text/results, and temporary Telegram IDs. A cleanup failure is retried, then closes intake and alerts the operator; the bot never claims completed cleanup.
10. On restart, cleanup of leftovers runs before accepting new documents. Stale updates change nothing and trigger one restart notice per user; old buttons return Session expired, do not redownload the file, and do not change a new task; saved profiles are available after login.
11. Operator alerts are sent to configured IDs with content-free events.

## Acceptance and Checks

- Model-based tests over the STATE_MACHINE invariants with a fake clock, Telegram, runtime, and storage.
- End-to-end scenarios for a single file, album, Several pages, missing/ambiguous profile, multi-type preview/confirm, partial/zero result, and long list.
- Two users and two consecutive tasks do not mix pages, profiles, callbacks, or responses; the owner's second document is processed only according to the explicit active-task rule.
- Check Cancel during collection, queueing, waiting, inference, and delivery. After cancellation is committed, no new sends/retries occur, and a late inference response is discarded. A send that has already started may be delivered: check the race with a lost acknowledgement, without promising message retraction.
- Check overlapping Settings and job flows: an edit during processing, a deferred job question, and view-only Settings while the job waits.
- Check the budget pause while waiting for the user, turn-taking between a long and a short document, a resumed job's return to its place, Busy and size refusals, and the queue-wait safety net.
- Check expiry, /logout, restart with stale updates, a stale password message, unavailability of Telegram/model/database, and an error midway through delivery; do not report complete for a full result that was not sent.
- Confirm cleanup and absence of content in logs/backup/alerts for every terminal outcome; the profile remains separate from the temporary document.

## Completion Conditions and Exclusions

Admission, queue, delivery timeout, activity, and logout policies are defined in STATE_MACHINE, OPERATIONS, and USER_FLOWS. Run local scenarios with controlled Telegram substitutes during development. Defer the final real-Telegram E2E until the complete product is available and the developer can participate; that check is not complete before then.

Excluded: groups, webhook, multiple instances, durable document queue, background recovery of an old upload, broadcasts, or external actions based on recognized content.
