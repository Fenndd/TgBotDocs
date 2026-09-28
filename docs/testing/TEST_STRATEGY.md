# Test Strategy

Status: implementation active, 2026-09-28. The [T01a runtime report](T01A_REPORT.md) records executed exploratory checks and measurement-harness tests. The T01b recognition core and T01 tooling have deterministic component tests (`python -m uv sync --locked`, then `.venv\Scripts\python.exe -m pytest -q` and `.venv\Scripts\python.exe -m ruff check src tests`); GPU checks run through the [T01 procedure](T01_PROCEDURE.md). T01b is frozen; product integration and final acceptance remain outstanding. This strategy reflects the deferred shared T01c/T07 benchmark run.

## Test Levels

1. **T01a–T01b — recognition foundation on the current PC.** Runtime feasibility, human-reviewed calibration, and a frozen core allow T02–T08 to proceed. The freeze does not accept recognition quality.
2. **T02 — walking skeleton.** With T01b frozen, the thinnest end-to-end path — sign-in, one image, a fixed profile, the recognition core, reply, and cleanup — runs on the development PC using a controlled Telegram substitute before the feature work of T03–T06.
3. **T02–T05 — component checks.** Deterministic transitions/contracts, PostgreSQL migrations and isolation, file preparation, parser timeout, model adapter, merging, and verification signals. External-system failures are reproduced with controlled substitutes: a fake Telegram API, a fake llama-server with scripted delays and failures, and a fake clock. A small suite runs against the pinned real llama-server to confirm streaming cancellation, the idle check, and restart.
4. **T06 — integration scenarios.** The state machine is tested model-based: random event sequences against the [transition table](../architecture/STATE_MACHINE.md) with its invariant checks. Scenario tests cover the sequential queue, two users, profiles, send/cancel/expiry, duplicates, late pages, stale updates after restart, delivery, and cleanup. Use controlled Telegram substitutes locally; do the final real Telegram test jointly with the developer when the complete product is available.
5. **T07 — local checks and deferred quality acceptance.** Functional scenarios, isolation, cleanup, and resilience checks may proceed with controlled substitutes. Defer the one sealed 70-case integrated benchmark until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer. That single run satisfies both T01c and T07 quality acceptance.
6. **T08 — delivery preparation and platform checks.** Local packaging and available platform checks may proceed after T07's local checks. Full handoff acceptance remains pending the joint Telegram E2E, shared benchmark, and native Linux x86-64/NVIDIA verification.

pytest with async support is planned for unit/component/integration tests, and Hypothesis for model-based state machine tests. The component-test commands above exist since T01b; T02 adds the application's own suites and records their commands after they run.

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
