# Operating Model and Initial Parameters

Status: v1 operating specification. Core deadlines and behavior have been accepted by the user; the protective settings below are engineering initial values that can be changed through configuration. Not yet verified through execution.

## Processes

1. One Python bot process: long polling, dialogues, queue, and application logic.
2. One local llama-server: selected weights, CUDA, one active model request.
3. PostgreSQL: personal settings, their versions, and the minimum amount of owner data.
4. A short-lived isolated PDF/image preparation process so that a parser timeout can be terminated without hanging the bot.

The model API listens only on loopback. PostgreSQL is not exposed to the network by default. Telegram is an allowed external channel; arbitrary URLs from documents and model responses are not opened.

## Parameters

| Parameter | Initial value / rule | Basis |
| --- | --- | --- |
| Authorization | Until /logout or restart; new password takes effect after restart | Accepted by the user |
| Active document per user | No more than one, including collection, waiting, queue, and processing | Accepted by the user |
| Waiting for pages/clarification | 15 minutes of inactivity; a meaningful reply/page resets the timer | Accepted by the user |
| Job processing | 30 minutes from the start of preparation; no extension by a separate message | Accepted by the user |
| File size | Standard Bot API limit of 20 MB | Accepted by the user; service rejection is also handled |
| Active inference | 1; profile creation uses the same scheduler | Sequential GPU use accepted |
| Waiting jobs | 8 globally; when full, reject as Busy before download | Initial resource protection |
| Queue wait | Up to 15 minutes; then cancel and delete the contents | Initial operating value |
| Album collection window | 2 seconds of silence; absolute collection wait of 15 minutes | Initial value; late parts are handled explicitly |
| Incorrect password | 5 attempts in 15 minutes per Telegram user ID, then blocked until the end of the window | Initial access protection |
| One model call | Up to 5 minutes and no longer than the remaining job time | Initial hang protection |
| Retry for invalid JSON | 1; then a technical error | Contract control, not an increase in confidence |
| Result delivery | Up to 60 seconds, up to 3 attempts for an explicitly retryable error; uncertain delivery is not declared successful | Initial limit on temporary storage time |
| Expired-data check | At startup and then every minute | Engineering mechanism for enforcing deadlines |
| Working temporary directory | Total quota of 2 GiB; 2 GiB free-disk reserve; values configurable | PC protection; resource failure is explained to the user |
| Logs | Technical events only; local rotation, 7-day retention | Initial diagnostics without document contents |

These queue/resource limits do not silently shorten a document. Files are not truncated to the first pages. If the entire set cannot be processed, the result is not marked complete. GPU context, resolution, and page-batch limits are selected in T01 based on measurements and recorded in the launch profile; the original file remains available until cleanup.

## Queue and Failures

FIFO for ready jobs; new documents do not displace another user's processing. While waiting for instructions, the GPU is released and the temporary document remains until the agreed TTL. A profile draft occupies the user's dialogue; another message while it is being processed does not create multiple competing saves.

There is no automatic cloud fallback when memory is insufficient. The job ends with a clear error and cleanup; error details do not include the document. A timeout/cancellation terminates the request and confirms that the runtime has been released before new work. If this cannot be done, the runtime is restarted and remains unavailable until its health is checked.

At startup, the safe absolute path of the temporary directory and ownership of leftover files by the application are checked first. Cleanup of crash leftovers runs regardless of PostgreSQL or model endpoint availability. Only after cleanup are the full configuration, database, migrations, and model checked; document intake is then enabled. Leftovers in use by the previous process require safely terminating the specific worker owned by the application. A cleanup failure blocks intake and requires operator remediation; it is not recorded as a successful deletion. The old process's queue and inputs are not restored.

## Delivery and Retries

During a run, a repeated update ID does not start a second document. For an album, a temporary record of the processed group is kept: a late page does not silently start a new job. After a restart, unfinished work is reset as agreed; the user starts a new session/submission. The application does not promise exactly-once processing across a crash boundary.

After all response parts are delivered, the data is deleted. On an error/uncertain delivery, the data is also deleted after the window expires: the user can retry the upload. Successfully delivered parts must not be sent automatically again as though they had not been delivered.

Cancel/logout records cancellation locally: no new sends, subsequent parts, or retries are started after that, and late inference results are discarded. A Telegram HTTP request already started may be accepted without a confirmation being received; it cannot be promised to have been recalled. It is counted as confirmed or uncertain delivery and does not trigger a retry after cancellation.

## Configuration and Delivery

Secrets: Telegram token, shared password, PostgreSQL access. Settings: local model endpoint, weights and temporary directory paths, timers, and quotas. Actual values are kept outside Git; a future .env.example will contain only names and safe examples.

The application does not download weights while processing a document. Weights and versions are installed in a separate preparation step. A backup includes database settings and necessary configuration, but no temporary documents; secret backup storage is a separate responsibility of the environment owner.

Processes and configuration are not created in this session. Commands will be added only after they have been verified in development tasks.
