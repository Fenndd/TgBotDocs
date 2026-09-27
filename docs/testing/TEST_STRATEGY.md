# Test Strategy

Status: defined for subsequent development; revised on 2026-09-27 after the independent review (staged T01, walking skeleton, model-based state machine tests, runtime tests). There are no product tests or commands yet.

## Test Levels

1. **T01a–T01c — recognition on the current PC.** Runtime feasibility, calibration on the tuning set, and one sealed benchmark run; versions and parameters, strict results, independent ground truth, memory/time, [accepted criteria](ACCEPTANCE_PLAN.md).
2. **T02 — walking skeleton.** The thinnest end-to-end path — sign-in, one image, a fixed profile, the recognition core, reply, and cleanup — runs on the development PC before the feature work of T03–T06.
3. **T02–T05 — component checks.** Deterministic transitions/contracts, PostgreSQL migrations and isolation, file preparation, parser timeout, model adapter, merging, and verification signals. External-system failures are reproduced with controlled substitutes: a fake Telegram API, a fake llama-server with scripted delays and failures, and a fake clock. A small suite runs against the pinned real llama-server to confirm streaming cancellation, the idle check, and restart.
4. **T06 — integration scenarios.** The state machine is tested model-based: random event sequences against the [transition table](../architecture/STATE_MACHINE.md) with its invariant checks. Scenario tests then cover the sequential queue, two users, profiles, send/cancel/expiry, duplicates, late pages, stale updates after restart, delivery, and cleanup; finally a check with the real Telegram test bot.
5. **T07 — acceptance and resilience.** The sealed 70-case benchmark through the integrated pipeline with compiled profiles, fault injection, and leak checks.
6. **T08 — delivery reproducibility.** Clean launch and smoke test of the native Windows installation and of the Linux container path on a native Linux x86-64/NVIDIA host, versions, migrations, backup/restore, licenses, and guide.

pytest with async support is planned for unit/component/integration tests, and Hypothesis for model-based state machine tests. Actual commands are recorded in T02 after the environment is created and run; such commands are not claimed to exist now.

## Coverage Matrix

| Requirements | Main check |
| --- | --- |
| REQ-001/009/010/018/021/029 | T03/T06: access, English UI, personal confirmed profiles, multi-type instructions |
| REQ-002/003/011/015/019/030 | T04/T06: formats, photo and file paths, auto-start, pages, size, admission, timers |
| REQ-004/005/006/007/012/013/016/022/027/028 | T01/T05/T07: open types/languages, only requested fields/lists, merging, verification, accuracy, refusal |
| REQ-008/014/020/026 | T01/T02/T04/T06/T07: local processing within the PC's hardware, lifecycle, crash, stale updates, and cleanup |
| REQ-023/024/025 | T01/T02/T06: selected components, one instance/inference, scheduler |
| REQ-017/031/032 | T07/T08: quality criteria and both target platforms |

## Data and Result Integrity

Materials, ground truth, metric denominators, the sealed-benchmark rules, and continuation conditions are defined in [ACCEPTANCE_PLAN](ACCEPTANCE_PLAN.md). Real user documents do not become a test archive. Checking JSON format does not prove data is correct; a correct refusal does not replace useful extraction.

Documentation, official sources, and hardware were checked during planning; this does not count as product testing. Each future check receives one of these statuses: verified / not verified / failed. An unsuccessful Linux check is not hidden by a successful Windows check.
