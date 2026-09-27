# Dialogue and Job State Machine

Status: v1 specification, 2026-09-27; the single reference for per-user states, events, timers, scheduling, and admission. [USER_FLOWS](../requirements/USER_FLOWS.md) describes the same behavior for users, and [OPERATIONS](../operations/OPERATIONS.md) holds the parameter values. Not yet verified through execution.

## Execution Model

- aiogram handlers do not change state. They check that the update comes from a private chat and put an event into the user's mailbox. aiogram processes updates concurrently by default (`handle_as_tasks=True`), so this indirection is what keeps each user's events in order.
- Each user has one actor: a task that takes events from the mailbox one at a time and applies transitions. A transition never waits for downloads, parsing, model calls, database writes, or sends. It starts them as separate operations, which report back as events; Cancel is therefore handled even while a long operation runs.
- Every job has a random ID and a generation number. A completion event carries the generation its operation started with; a completion for an older generation is discarded. Callback data carries the job ID, generation, and a per-process session nonce in a compact form within Telegram's 64-byte callback-data limit, so buttons from a previous process or a replaced pass answer "Session expired".
- Global components — the GPU scheduler, admission control, the download limiter, and the cleanup service — exchange events with actors and hold no per-user dialogue state.
- Timers use a monotonic clock, belong to a state, and are cancelled when the state is left.

## Session

| State | Event | Transition and effects |
| --- | --- | --- |
| signed_out | `/start` in a private chat | → awaiting_password; ask for the password |
| signed_out | Any other input | Reply "Send /start to sign in" at most once per minute; nothing is downloaded |
| awaiting_password | Text | Constant-time comparison with the configured password, then delete the message. Success → signed_in, show the menu; failure → count the attempt and stay, or lock per OPERATIONS |
| signed_in | `/start` | Show the menu and the status of the current job |
| signed_in | `/logout` | Cancel the job and discard drafts as with Cancel; → signed_out |
| Any | Process restart | All sessions are lost; users sign in again |

Updates from groups and channels do not reach actors: the bot answers once that a private chat is required and never asks for the password there.

## Document Job

A job is created by a file, an album part, or the Several pages button, only for a signed-in user without a job, and only after the pre-download admission check. Each job has an admission time.

| State | Timers | Events and transitions |
| --- | --- | --- |
| collecting | Several pages: 15 min inactivity. Album: 2 s quiet window, 15 min absolute | File: download through the limiter, validate the format by content, count pages. A single file that is not part of an album or Several pages → admission once validated. A file that cannot be downloaded or is invalid: a single file ends the job with the reason; an album is refused as a whole, because a set must be complete; in Several pages only that file is refused, and collection continues. An exhausted temporary quota ends the job with a resource error. Process: files present → admission; none → "no document". Album quiet window ends → admission. Cancel → cancelled. Inactivity → expired |
| admission | None | Size estimate (ED-002): the set cannot finish within the budget → rejected with an explanation; otherwise → queued |
| queued | Queue wait, per entry | First call granted → matching, or extracting when a profile is already selected. Cancel → cancelled. Expiry → expired |
| matching | Budget runs | matched with the verification margin → extracting; uncertain → awaiting_choice; no_profile → awaiting_instruction; unreadable, mixed, or not_document → finished (failed) with the reason |
| awaiting_choice | 15 min inactivity; budget paused | Profile chosen, marked user-selected → queued. New instruction → awaiting_instruction. Cancel → cancelled. Inactivity → expired |
| awaiting_instruction | 15 min inactivity; budget paused | Text → compiling. Existing profile chosen → queued. Cancel → cancelled. Inactivity → expired |
| compiling | Budget runs | Drafts → awaiting_confirmation. Questions → awaiting_instruction with the questions. Failure → awaiting_instruction with an error message |
| awaiting_confirmation | 15 min inactivity; budget paused | Save, in one transaction: one profile → queued with it as user-selected; several → awaiting_choice among them. Edit → awaiting_instruction in edit mode. Cancel draft → awaiting_instruction. Cancel → cancelled. Inactivity → expired |
| extracting | Budget runs | Batches in order through the scheduler; merging and verification → delivering. Budget exhausted → finished (error: time limit). Runtime or contract failure → finished (error) |
| delivering | 60 s window, up to 3 retries | All parts confirmed → finished. Send failed or unconfirmed → finished with failed or uncertain delivery |
| finished, rejected, cancelled, expired | None | Cleanup; the job disappears; an album's group ID is remembered for 15 minutes |

A job that returns to queued after a user decision keeps its admission time and its place in the turn order. A question the job must ask while a Settings draft is open is deferred as described in Settings Flow.

Input counts as activity only when the current state accepts it: a page in collecting, a button of the current generation, or text where text is expected. Activity resets the inactivity timer. Other input gets a short reminder of the expected action and does not reset the timer.

The 30-minute processing budget (ED-003) is charged only for the job's own work: its model calls, page rendering, merging, verification signals, and retries in matching, compiling, and extracting. Waiting for the user or for the GPU is not charged. When the budget is exhausted in matching, compiling, or extracting, the running call is cancelled and the job finishes with a time-limit error. A runtime failure or a repeated contract violation in these states also finishes the job with an error, except that a failed instruction compilation returns to awaiting_instruction.

## Cancellation and Late Events

- Cancel and `/logout` increment the generation and move the job to cancelled from any state. A running download or parser is terminated. A running model call is cancelled through the scheduler, which confirms that the slot is idle, or restarts the runtime, before the next call. Late results carry the old generation and are discarded.
- In delivering, parts that have not started are not sent. A send already started may complete; its delivery is uncertain, and nothing is retried after cancellation.
- A late fragment of the same album before delivering starts increments the generation, cancels the current pass, discards the job's open instruction draft (a Settings draft is unaffected), and returns the job to collecting with the new fragment; the budget already charged stays charged. After delivering starts, the fragment is not downloaded: the bot says the result was for an incomplete album and offers Several pages.
- A new separate file while a job exists is not downloaded; the bot offers to wait or to Cancel and resend.

## Settings Flow

Settings allows viewing, creating, editing, and deleting profiles. Creating and editing use the same compile → preview → Save/Edit/Cancel steps with a 15-minute inactivity timer on the draft; Save uses optimistic concurrency ([DATA_MODEL](DATA_MODEL.md)).

Settings and a document job may overlap (S-13-A1) under one rule: at most one flow waits for the user's input at a time (ED-013).

- While the job waits for the user — collecting through Several pages, awaiting_choice, awaiting_instruction, or awaiting_confirmation — Settings is view-only, and the bot asks the user to answer the document first or to Cancel it.
- While the job is in admission, queued, matching, compiling, extracting, or delivering, profiles can be created, edited, and deleted. The job keeps the snapshot taken when its matching started; a later change or deletion affects only later documents, and Save says so.
- If the job needs the user while a Settings draft is open, its question is deferred: the bot says that the document is waiting, shows the question when the draft is saved or cancelled, and starts the job's inactivity timer then. The processing budget stays paused meanwhile.
- While a Settings draft is open, a single file or an album can start a job, whose first question is deferred the same way; Several pages starts only after the draft is closed.
- The menu's Cancel acts on the document job; a draft has its own Cancel in its preview. `/logout` ends both.

## GPU Scheduler

The scheduler runs one model call at a time and picks the next call:

1. Interactive calls first: instruction compilation for a job or for Settings. They are text-only and bounded by the call timeout.
2. Then document calls, in turns (S-12-A1). Jobs that have a next call ready — matching, an extraction batch, or a verification re-read — form a ring in admission order; after each call, the next job in the ring gets the GPU. A job waiting for the user leaves the ring and returns to its place when it resumes. A long document therefore does not block short ones; its wall-clock time grows with load, but its budget counts only its own calls.

Before every call, the scheduler confirms that the previous call has finished or that its cancellation released the slot (ADR-0005). Queue wait is measured from entering queued until the job's first call starts; with turn-taking it is normally at most one call per other active job.

## Admission Control

Admission uses the job-slot limit and the lower-bound per-page time of the frozen recognition configuration (OPERATIONS):

- Before any download for a new job: if the number of non-terminal jobs has reached the maximum, the bot answers Busy and downloads nothing.
- After collection, when the page count is known: if the page count multiplied by the lower-bound per-page time, plus fixed overhead, exceeds the processing budget, the job is rejected with an explanation that the document cannot be processed within the time limit on this machine; nothing is truncated.

## Dependency Unavailability

When the database or the model runtime stays unavailable after the supervisor's restart attempt, new jobs are refused as temporarily unavailable before download, the operator is alerted, and health checks continue; intake reopens when both are healthy. Queued jobs keep waiting within their own deadlines. A job that cannot read profile snapshots finishes with a temporary error. A Save that cannot reach the database is not reported as saved; the preview stays open so the user can retry within its timer.

## Restart and Stale Updates

Startup order: cleanup of leftovers and orphaned child processes, then configuration, database, migrations, and runtime checks, then long polling. An update created before the process start — messages by date, callbacks by their session nonce — is stale (ED-005): it changes no state, and nothing is downloaded. Each affected user gets one notice that the bot restarted and earlier input was not processed. A stale text message equal to the configured password is deleted and does not sign the user in.

## Cleanup

Every terminal state starts cleanup of the job directory and in-memory job data. A failed deletion is retried with backoff (OPERATIONS). If it still fails, intake closes for everyone, the operator is alerted, retries continue every minute, and intake reopens automatically when the leftovers are gone (ED-006). Users who try to submit meanwhile are told that the bot is temporarily unavailable.

## Invariants for Tests

Model-based tests drive random event sequences through the actor with a fake clock, Telegram, runtime, and storage, and check that:

- a user has at most one job, and at most one flow waits for the user's input;
- no model call runs for a cancelled job or an old generation, and at most one call runs at a time;
- nothing is downloaded before sign-in and admission;
- every terminal state leads to cleanup;
- timers, the budget, and scheduler order follow this document.
