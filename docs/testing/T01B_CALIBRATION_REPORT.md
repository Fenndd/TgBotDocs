# T01b Calibration Report

Date: 2026-09-28. Status: calibration verified and recognition configuration frozen; **recognition quality acceptance is pending the deferred T01c sealed benchmark**. This tuning result is not independent acceptance.

## Provenance

- Human reviewer: Nikita, reviewed tuning set at 01:41 on 2026-09-28 as recorded in STATUS. 22 verified cases; tune-17, tune-22, tune-23 excluded by the review.
- Reviewed manifest SHA-256: `022fd0b23dc7c081780c73af225b9928ec60592b2e8346fa1f18378a45dcfbc0`.
- Calibration: `C:\Users\nikit\TgBotDocsData\dev\measurements\t01b-calibration.json`; SHA-256 `ddde4d0d0652f542c1fef558fcd773d736f77da24b4e0a112041bbe2c33c38b0`.
- Frozen file: `C:\Users\nikit\TgBotDocsData\dev\frozen\frozen-t01b.json`; SHA-256 `dd1d01a0e8ff878a60b7b4bf61b6bcb20939cd5bd5695bed4eaa79a55ea633f6`.
- Report was eligible for calibration, covered all 22 cases, and recorded no environment changes during collection. The existing completed report was reused; no second GPU collection was needed.
- Verified command: `.venv\Scripts\python.exe -m tgbotdocs.recognition.runner freeze --auto --calibration C:\Users\nikit\TgBotDocsData\dev\measurements\t01b-calibration.json --output C:\Users\nikit\TgBotDocsData\dev\frozen\frozen-t01b.json`.

## Frozen Operating Point

Point 127: V1 minimum token probability **0.70**, V2 alternate view **enabled**, V3 declared validators **enabled**, matching margin **0.90**. V4 is the core merge contract; V5 is not enabled.

The predeclared ED-014 rule selected 85 accepted values with 0 errors and 16 automatic profiles with 0 errors; 0 unreplayable cases. Readable completeness is 68/75 = 0.906667. 21 cases completed; one encrypted PDF was explicitly refused. No below-target override was used.

Other tuning observations remain visible: 3 outcome mismatches; scalar readable completeness 0.888889, list-cell completeness 1.000000. Calibration selection requires zero wrong accepted values/profiles, not zero outcome mismatches. These remaining limitations must be checked in acceptance.

With zero errors among N=85 accepted values the exact 95% upper error bound is 0.034630; for N=16 automatic selections it is 0.170750. This does not guarantee future correctness.

## Risk and Coverage

All points replay the production decision from the same policy-independent traces. Coverage below is readable completeness; errors count incorrectly accepted values. The full report retains all combined points and group denominators.

| V1 threshold | V2 | Matching margin | Accepted values | Wrong values | Wrong profiles | Readable completeness |
| --- | --- | --- | --- | --- | --- | --- | --- |
| off | off | 0.9 | 92 | 7 | 0 | 0.906667 |
| 0.3 | off | 0.9 | 92 | 7 | 0 | 0.906667 |
| 0.5 | off | 0.9 | 88 | 3 | 0 | 0.906667 |
| 0.7 | off | 0.9 | 86 | 1 | 0 | 0.906667 |
| 0.8 | off | 0.9 | 85 | 1 | 0 | 0.893333 |
| 0.85 | off | 0.9 | 83 | 1 | 0 | 0.893333 |
| 0.9 | off | 0.9 | 83 | 1 | 0 | 0.893333 |
| 0.95 | off | 0.9 | 80 | 0 | 0 | 0.866667 |
| 0.97 | off | 0.9 | 79 | 0 | 0 | 0.853333 |
| 0.99 | off | 0.9 | 71 | 0 | 0 | 0.786667 |
| 0.995 | off | 0.9 | 70 | 0 | 0 | 0.773333 |
| 0.999 | off | 0.9 | 66 | 0 | 0 | 0.733333 |
| off | on | 0.9 | 87 | 2 | 0 | 0.906667 |
| 0.3 | on | 0.9 | 87 | 2 | 0 | 0.906667 |
| 0.5 | on | 0.9 | 86 | 1 | 0 | 0.906667 |
| 0.7 | on | 0.9 | 85 | 0 | 0 | 0.906667 |
| 0.8 | on | 0.9 | 84 | 0 | 0 | 0.893333 |
| 0.85 | on | 0.9 | 82 | 0 | 0 | 0.893333 |
| 0.9 | on | 0.9 | 82 | 0 | 0 | 0.893333 |
| 0.95 | on | 0.9 | 80 | 0 | 0 | 0.866667 |
| 0.97 | on | 0.9 | 79 | 0 | 0 | 0.853333 |
| 0.99 | on | 0.9 | 71 | 0 | 0 | 0.786667 |
| 0.995 | on | 0.9 | 70 | 0 | 0 | 0.773333 |
| 0.999 | on | 0.9 | 66 | 0 | 0 | 0.733333 |

V2 alone still accepts two wrong values; V1 alone reaches zero errors at 0.95 but readable completeness drops to 0.866667. V1 0.70 with V2 reaches zero errors without that loss. Matching-margin sweeps in the report have no wrong automatic profiles; the tie rule selects the higher margin 0.90.

## Frozen Per-page Times

Seconds per page for admission (p5 lower bound) and planning (p50). Only completed cases whose selected decision traversed every page contribute. Preparation is apportioned over pages; runtime calls over their included pages. V2 renders/calls are included. Small synthetic sample; these are not an SLA.

| Kind | Pages | p5 (s) | p50 (s) | p95 (s) |
| --- | --- | --- | --- | --- |
| jpeg | 8 | 11.310700 | 12.434723 | 17.676262 |
| pdf | 4 | 10.174577 | 12.282036 | 14.389891 |
| png | 7 | 8.783015 | 12.882234 | 20.801890 |

Collection wall time per case: p50 12.451 s, p95 23.376 s. Sampled device-wide GPU peak 5320 MiB; runtime RSS peak 2959.266 MiB. Samples are lower bounds; GPU memory is device-wide.

## Configuration and Remaining Checks

Qwen3-VL-4B Q4_K_M, FP16 projector, llama.cpp b11221; q8_0 K/V, context 4096, image tokens 128–1024, primary PDF 150 DPI and alternate PDF 200 DPI. Prompt t01b-3; code SHA-256 `33dc9022142a03adb8de99b8ae8e1172fbd9899e2c7709dda8bdce9742ec0cb4`; prompt SHA-256 `04265c6b0cc41bede5c5645cf80bea6431bb19364fabd2b70336999732fc6a54`. Recognition dependencies: httpx 0.28.1, pillow 12.3.0, pydantic 2.13.5, pydantic_core 2.46.5, pypdfium2 5.13.0, python 3.14.5.

The application must verify this identity on startup and use `FrozenConfiguration.core_settings()`. Any recognition code/prompt/dependency/runtime/policy change requires new calibration. Application integration must preserve decisions and exclude scheduler waiting from processing time.

T01c preparation and the single sealed run are deferred by S-14 until the complete product is available in Telegram. T02 may proceed after this freeze. The benchmark remains mandatory; recognition quality, real-Telegram E2E, and native Linux verification are not accepted or performed.
