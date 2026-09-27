# Test Strategy

Status: defined for subsequent development. There are no product tests or commands yet.

## Test Levels

1. **T01 — quality of the selected recognition on the current PC.** Local direct VLM, versions and parameters, strict results, independent ground truth, memory/time, [accepted criteria](ACCEPTANCE_PLAN.md).
2. **T02–T05 — component checks.** Deterministic transitions/contracts, PostgreSQL migrations and isolation, file preparation, parser timeout, model adapter. External-system failures are reproduced with controlled substitutes.
3. **T06 — integration scenarios.** Sequential queue, two users, profiles, send/cancel/expiry, duplicates, late pages, delivery, and cleanup; then a check with the real Telegram test bot.
4. **T07 — acceptance and resilience.** 70-case benchmark set, integrated pipeline, fault injection, and leak checks.
5. **T08 — delivery reproducibility.** Clean launch and smoke test on Windows and Linux x86-64/NVIDIA, versions, migrations, backup/restore, licenses, and guide.

pytest with async support is planned for unit/component/integration tests. Actual commands are recorded in T02 after the environment is created and run; such commands are not claimed to exist now.

## Coverage Matrix

| Requirements | Main check |
| --- | --- |
| REQ-001/009/010/018/021/029 | T03/T06: access, English UI, personal confirmed profiles |
| REQ-002/003/011/015/019/030 | T04/T06: formats, auto-start, pages, size, timers |
| REQ-004/005/006/007/012/013/016/022/027/028 | T01/T05/T07: open types/languages, only requested fields/lists, accuracy, refusal |
| REQ-008/014/020/026 | T02/T04/T06/T07: local processing, lifecycle, crash, and cleanup |
| REQ-023/024/025 | T01/T02/T06: selected components, one instance/inference |
| REQ-017/031/032 | T07/T08: quality criteria and both target platforms |

## Data and Result Integrity

Materials, ground truth, metric denominators, and continuation conditions are defined in [ACCEPTANCE_PLAN](ACCEPTANCE_PLAN.md). Real user documents do not become a test archive. Checking JSON format does not prove data is correct; a correct refusal does not replace useful extraction.

Documentation, official sources, and hardware were checked during planning; this does not count as product testing. Each future check receives one of these statuses: verified / not verified / failed. An unsuccessful Linux check is not hidden by a successful Windows check.
