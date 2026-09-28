# Operating Model and Initial Parameters

Status: v1 operating specification; revised on 2026-09-27 after the independent review (admission control, timer semantics, scheduler, runtime supervision and launch profile, operator alerts). Core deadlines and behavior have been accepted by the user; the protective settings below are engineering initial values that can be changed through configuration. Local implementation and checks are recorded in [STATUS](../../STATUS.md); quality, real Telegram and platform acceptance remain distinct. Transitions are specified in [STATE_MACHINE](../architecture/STATE_MACHINE.md).

## Processes

1. One Python bot process: long polling, dialogues, scheduler, and application logic. It supervises its child processes ([ADR-0005](../decisions/ADR-0005-runtime-supervision-and-packaging.md)).
2. One llama-server child process: selected weights, CUDA, one slot, one active model request.
3. Short-lived file-preparation child processes, so that a parser timeout can be terminated without hanging the bot.
4. PostgreSQL: personal settings and the minimum amount of owner data.

Child processes end with the bot: a Job Object on Windows; a parent-death signal and a container init on Linux. The model API listens only on loopback and requires an API key. PostgreSQL is not exposed to the network by default. Telegram is an allowed external channel; arbitrary URLs from documents and model responses are not opened.

## Parameters

| Parameter | Initial value / rule | Basis |
| --- | --- | --- |
| Authorization | Until /logout or restart; new password takes effect after restart | Accepted by the user |
| Active document per user | No more than one, including collection, waiting, queue, and processing | Accepted by the user |
| Waiting for pages/clarification | 15 minutes of inactivity; a meaningful reply/page resets the timer | Accepted by the user |
| Processing budget | 30 minutes, cumulative per document, charged only for the job's own work in matching, instruction compilation, and extraction, including page rendering, merging, verification, and retries, until the result is ready for delivery; waiting for the user or for the GPU is not charged | Accepted by the user; ED-003 |
| File size | Standard Bot API limit of 20 MB | Accepted by the user; service rejection is also handled |
| Pages and files per set | No fixed cap; a set that cannot finish within the budget even at the lower-bound per-page time is refused before recognition | ED-002 |
| Active inference | 1; instruction compilation uses the same scheduler | Sequential GPU use accepted |
| Turns between documents | One model call per active document per turn, in admission order; instruction compilation goes first | Accepted by the user (S-12-A1) |
| Admitted jobs | 8 non-terminal jobs globally; when all are taken, a new job is refused as Busy before download | Initial resource protection; ED-002 |
| Queue wait | Up to 15 minutes per queue entry, until the job's first call; a safety net behind admission control | Initial operating value |
| Album collection window | 2 seconds of silence; absolute collection wait of 15 minutes | Initial value; late parts are handled explicitly |
| Late album fragment memory | 15 minutes after the job ends | Initial value |
| Incorrect password | 5 attempts in 15 minutes per Telegram user ID, then blocked until the end of the window. 30 failed attempts in 15 minutes globally alert the operator. There is no global pause: it would let anyone block new sign-ins, while a leaked password exposes compute, not other users' data | Initial access protection; ED-009 |
| Profile drafts per instruction | Up to 10 | ED-001 |
| One model call | Up to 5 minutes and no longer than the remaining budget | Initial hang protection |
| Runtime release window | After cancellation, the slot must report idle within 10 seconds; otherwise llama-server is restarted | ADR-0005 |
| Retry for invalid JSON | 1; then a technical error | Contract control, not an increase in confidence |
| Result delivery | Up to 60 seconds, up to 3 attempts for an explicitly retryable error; uncertain delivery is not declared successful | Initial limit on temporary storage time |
| Concurrent downloads | 2 globally | Initial resource protection |
| Decoded image size | Refused above a configured pixel limit, initially the Pillow decompression-bomb threshold; ordinary phone photos are far below it | Untrusted-input protection |
| Expired-data check | At startup and then every minute | Engineering mechanism for enforcing deadlines |
| Cleanup retry | 5 attempts with exponential backoff over about 1 minute; then intake closes, the operator is alerted, and retries continue every minute | ED-006 |
| Working temporary directory | Total quota of 2 GiB; 2 GiB free-disk reserve; values configurable | PC protection; resource failure is explained to the user |
| Logs | Technical events only; local rotation, 7-day retention | Initial diagnostics without document contents |

These queue/resource limits do not silently shorten a document. Files are not truncated to the first pages. If the entire set cannot be processed, the result is not marked complete. Context, image token budget, render resolution, and batch size are selected in T01a based on measurements and recorded in the launch profile; the original file remains available until cleanup.

Admission uses the lower-bound per-page time (5th percentile) of the frozen recognition configuration, measured for each page kind in T01b and confirmed on the benchmark in T01c, to refuse clearly infeasible sets. The typical per-page time (median) is recorded for capacity planning. Both are configuration values tied to that configuration.

## Scheduler and Failures

The GPU scheduler runs one model call at a time: interactive instruction-compilation calls first; active documents then take turns, one model call each, in admission order (S-12-A1, STATE_MACHINE). A long document does not block short ones; under load it takes longer in wall-clock time, but its budget counts only its own work. While a job waits for the user, the GPU is released and the temporary document remains until the inactivity timer expires.

There is no automatic cloud fallback or stronger server when memory is insufficient. The job ends with a clear error and cleanup; error details do not include the document. Model calls are streamed. A timeout or cancellation closes the stream, and the next call starts only after the llama-server slot reports idle; if it does not within the release window, the supervisor restarts llama-server, and the runtime stays unavailable until its health check passes. Queued jobs stay queued during a restart unless their own deadlines expire. If the runtime or the database stays unavailable, new jobs are refused as temporarily unavailable until both are healthy (STATE_MACHINE).

At startup, the safe absolute path of the temporary directory and ownership of leftover files by the application are checked first, and child processes recorded by the previous run are terminated. Cleanup of crash leftovers runs regardless of PostgreSQL or model endpoint availability. Only after cleanup are the full configuration, database, migrations, and model checked; long polling then starts. Updates created before this start are handled in stale mode (STATE_MACHINE). A cleanup failure keeps intake closed and alerts the operator; it is not recorded as a successful deletion. The old process's queue and inputs are not restored.

## Delivery and Retries

During a run, a repeated update ID does not start a second document. For an album, a temporary record of the processed group is kept: a late page does not silently start a new job. After a restart, unfinished work is reset as agreed; the user starts a new session/submission. The application does not promise exactly-once processing across a crash boundary.

Result parts are sent in order and honor Telegram's `retry_after` responses. After all response parts are delivered, the data is deleted. On an error/uncertain delivery, the data is also deleted after the window expires: the user can retry the upload. Successfully delivered parts must not be sent automatically again as though they had not been delivered.

Cancel/logout records cancellation locally: no new sends, subsequent parts, or retries are started after that, and late inference results are discarded. A Telegram HTTP request already started may be accepted without a confirmation being received; it cannot be promised to have been recalled. It is counted as confirmed or uncertain delivery and does not trigger a retry after cancellation.

## Operator Alerts

The optional setting `OPERATOR_TELEGRAM_IDS` lists Telegram users who receive content-free technical alerts from the bot (ED-006): startup completed or failed, intake closed or reopened, runtime restarted or unavailable, database unavailable, a surge of failed password attempts, and repeated delivery errors. An alert contains an event code, time, and random job ID only. An operator must have started a chat with the bot and gets no access to other users' data. Without configured operators, the same events go only to the log. There is no health endpoint in v1: the product has no public HTTP server (ADR-0002), alerts and logs are the operational signal, and the service manager restarts a failed bot.

## Model Runtime Launch Profile

T01a pins the exact flags for the selected llama-server build. The profile includes:

- `--host 127.0.0.1`, a configured port, and `--api-key` from the secrets configuration;
- `--parallel 1`; context size, `--image-min-tokens`/`--image-max-tokens`, flash attention, KV-cache type, and GPU layer placement measured in T01a;
- `--cache-ram 0`, because the host-memory prompt cache (8,192 MiB by default) would keep states derived from earlier documents in RAM after their jobs end and compete for the PC's 16 GiB;
- `--no-webui`, no `--props`, low log verbosity, and no request or prompt logging;
- the slots endpoint stays enabled for the idle check.

Requests use streaming, greedy decoding with a fixed seed, schema-constrained output, a bounded output length, and token probabilities ([ADR-0004](../decisions/ADR-0004-abstention-and-verification.md)). Prompt caching within the single slot may reuse a document's pages between its consecutive calls when no other document's call intervenes; the next call overwrites the slot. The client never sends headers that disable disconnect-cancellation.

## Configuration and Delivery

Secrets: Telegram token, shared password, PostgreSQL access, llama-server API key. Settings: local model endpoint, weights and temporary directory paths, timers, quotas, admission per-page times, launch profile, and optional operator IDs. Actual values are kept outside Git and outside the source tree used by development assistants; the application reads its external `.env` through `--config` or `TGBOTDOCS_CONFIG`. The tracked [example](../../.env.example) contains safe placeholders and the random-password guidance; [CONFIGURATION](CONFIGURATION.md) describes validation.

The application does not download weights while processing a document. Weights and versions are installed in a separate preparation step. The application database backup contains only users, current profiles and the migration version; see [BACKUP_RESTORE](BACKUP_RESTORE.md). Temporary documents, logs, evidence and secrets are excluded. Protect external configuration/admin credentials separately under the environment owner's responsibility. Packaging per platform: ADR-0005.

Current commands and verified limits are in [RUNBOOK](RUNBOOK.md), [INSTALL_WINDOWS](INSTALL_WINDOWS.md), [INSTALL_LINUX](INSTALL_LINUX.md) and the [local joint-test guide](LOCAL_PC_JOINT_TEST.md). Instructions do not substitute for native platform or joint Telegram verification.
