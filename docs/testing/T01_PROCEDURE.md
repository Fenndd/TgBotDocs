# T01b/T01c Operating Procedure

Status: T01b review, calibration, and freeze completed on 2026-09-28; see the [calibration report](T01B_CALIBRATION_REPORT.md). Benchmark tooling is implemented and tested, but T01c corpus preparation and the single sealed integrated run remain deferred until the complete product is available through Telegram and the final real-Telegram E2E can be done with the developer. T01c and T07 share that one run. This procedure applies [T01](../../specs/T01-recognition-baseline.md), [ACCEPTANCE_PLAN](ACCEPTANCE_PLAN.md), and [ADR-0004](../decisions/ADR-0004-abstention-and-verification.md); the engineering choices it relies on are ED-014–ED-016 in the [decision register](../requirements/OPEN_QUESTIONS.md).

## Locations on the development PC

| Item | Path |
| --- | --- |
| Data root: models, pinned runtime, measurements, scratch, benchmark ledger | `C:\Users\nikit\TgBotDocsData\dev` |
| Tuning package (25 cases) with `canonical-manifest.json` and `review-form.html` | `C:\Users\nikit\TgBotDocsData\corpora\t01b-tuning-review-v3` |
| Environment | `python -m uv sync --locked` in the checkout; commands below use `.venv\Scripts\python.exe` |

Keep all data outside `%LOCALAPPDATA%`: the Codex and Claude desktop apps silently redirect writes there into their own package folders, which other programs, including the browser, cannot see. The data root must stay on one path per PC: the benchmark ledger that enforces one run per frozen configuration lives in it. Never place real user documents in these directories.

## Stage 1 — Diagnostics (allowed now, not a quality result)

```powershell
.venv\Scripts\python.exe -m tgbotdocs.recognition.runner run --mode diagnostics `
  --manifest C:\Users\nikit\TgBotDocsData\corpora\t01b-tuning-review-v3\canonical-manifest.json `
  --data-root C:\Users\nikit\TgBotDocsData\dev `
  --output C:\Users\nikit\TgBotDocsData\dev\measurements\<name>.json [--show-mismatches]
```

The runner collects one policy-independent trace per case (V2 alternate readings included unless `--no-alternate`), replays the production decision for every calibration point, and writes a content-free report: per-point aggregate and group metrics, per-signal curves, per-case timings and calls, sampled resource peaks, and failures by code. `--show-mismatches` prints value comparisons for synthetic development/tuning cases to stderr only. Diagnostics are refused on the benchmark split. Prompt and parameter development may use these reports; they never count as calibration.

## Stage 2 — Human review of the tuning set (developer)

1. Open `review-form.html` from the tuning package in a desktop browser. It works offline and sends nothing.
2. For every case, open each model input at full size and compare it with the expected values, pages, rows, matching expectation, and candidate profiles. For a script you cannot read, compare the glyph sequence with the reference review sheet and choose `glyph_sequence_comparison`. Decide the visibility of every value in the four difficult cases from what is actually visible. Reject a case whose ground truth cannot be confirmed.
3. Enter your name, confirm the human-inspection attestation, and export `review-decisions.json`.
4. Apply and check:

```powershell
.venv\Scripts\python.exe -m tgbotdocs.recognition.corpus_cli review-apply `
  --manifest <package>\canonical-manifest.json --decisions <path>\review-decisions.json `
  --output <package>\reviewed-manifest.json
.venv\Scripts\python.exe -m tgbotdocs.recognition.corpus_cli status --manifest <package>\reviewed-manifest.json
```

`status` must report no calibration eligibility reasons. The tools only transcribe the reviewer's decisions; an assistant must never create or edit a decisions file.

## Stage 3 — Calibration and freeze

```powershell
.venv\Scripts\python.exe -m tgbotdocs.recognition.runner run --mode calibration `
  --manifest <package>\reviewed-manifest.json --data-root <data root> --output <data root>\measurements\calibration.json
.venv\Scripts\python.exe -m tgbotdocs.recognition.runner freeze --auto `
  --calibration <data root>\measurements\calibration.json --output <data root>\frozen\frozen-t01b.json
```

`freeze --auto` applies the pre-declared selection rule (ED-014): only points with zero incorrect accepted values, zero incorrect automatic profiles, and no unreplayable cases qualify; maximum readable completeness wins; ties prefer V2 off, then the higher V1 threshold, then the higher matching margin. It refuses when no point qualifies (`calibration_no_zero_error_point`: follow the ADR-0004 remediation order) and when the selected completeness is below 0.90 unless `--accept-below-target` is given deliberately. The frozen configuration binds runtime artifacts, launch profile, core settings, prompt identity, policy, dependency versions, the recognition code hash, calibration provenance, and admission per-page times (p5/p50/p95 by page kind). Any code, prompt, dependency, or runtime change afterwards invalidates it.

## Stage 4 — Deferred sealed benchmark preparation (developer and assistant)

Begin this stage only after the complete product is available through Telegram and the developer can participate in the final real-Telegram E2E. The benchmark remains required recognition-quality acceptance.

Follow [README-benchmark](../../tools/t01/README-benchmark.md) for the exact steps. In short:

1. Generate the 70-case plan with `tools/t01/create_benchmark_set.py --output <new directory outside Git>`.
2. Print `printable-originals.pdf` (20 difficult cases) and photograph each page with a phone as `capture-instructions.html` specifies; send the listed photos through a Telegram chat as compressed photos in the stated quality (standard or HD) and save the received largest size; send the 8 readable photo-path PNGs the same way. Place files in `inbox/camera/` and `inbox/telegram/` under the listed names.
3. `python -m tgbotdocs.recognition.benchmark ingest ...` hashes and validates the files and writes a review-pending canonical manifest.
4. Review it with `corpus_cli review-form` / `review-apply` exactly as in Stage 2. A rejected benchmark case must be replaced by a new case of the same category, script, and quality before measurement.
5. After Stage 3: `python -m tgbotdocs.recognition.benchmark seal` binds the reviewed manifest to the frozen configuration's hash.

No model run may touch benchmark cases before sealing, and a benchmark case whose individual failure details are examined to change prompts, thresholds, signals, or rules becomes a tuning case and must be replaced.

## Stage 5 — Deferred single integrated benchmark run (T01c and T07)

Run only after the complete product is available through Telegram, the final E2E can be performed with the developer, and Stage 4 is complete. Run the sealed set once through the integrated product with the frozen T01b configuration and T07's compiled profiles. This single result supplies both T01c recognition-quality acceptance and T07 integrated quality acceptance.

The current `tgbotdocs.recognition.runner benchmark` command is a core-only runner, not the integrated product check. Do not use it as a separate acceptance run: it consumes the single-run benchmark ledger and cannot be followed by another sealed T07 run. The integrated execution route and its command must be recorded after that product path has been implemented and verified; do not invent a command in advance. The report must include the inputs to the accepted criteria in [ACCEPTANCE_PLAN](ACCEPTANCE_PLAN.md). Failure follows the ADR-0004 remediation order on this PC.
