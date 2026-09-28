# T01a runtime feasibility report

Date: 2026-09-27. **The technical transition condition to T01b is met.** This is not a quality acceptance result, a frozen recognition configuration, or permission to start T02. The original T01c-before-T02 gate was superseded on 2026-09-28 by [S-14](../requirements/SOURCES.md#s-14--t01c-timing-and-acceptance-2026-09-28): T02 may start after T01b freeze. Benchmark preparation and the one sealed T01c/T07 run remain deferred until the completed Telegram product and joint E2E; recognition quality is not accepted by this report.

## Scope and reproducibility

All inference ran serially on this PC: Windows 11 Home build 26200, Ryzen 5 5600H, RTX 3060 Laptop 6,144 MiB, NVIDIA driver 581.80. The OS reported 14,528,572 KiB usable RAM; existing desktop applications remained running. Measurements report the sampled total GPU usage, server resident/private memory, and available system RAM separately. A sampled peak is a lower bound on the true instantaneous peak. These are single-run engineering measurements, not a latency SLA or accepted accuracy estimate.

- Runtime: official llama.cpp **b11221**, commit `136887b665180c13c6209a4ce0673637b6cd3afd`, version output `0.5.0-dev`, Windows x64 CUDA 12.4, Clang 20.1.8.
- Model: official Qwen3-VL-4B-Instruct Q4_K_M and FP16 mmproj, revision `1cd86afb9a95c410a6038ab3b40d8b578c892266`. All four downloaded artifacts matched upstream SHA-256; [artifact record](evidence/t01a/artifacts.json).
- Python 3.14.5; uv 0.12.19. Exploratory dependencies and transitive hashes are in [requirements.lock](../../tools/t01/requirements.lock).
- Twelve generated documents, 15 pages, six scripts, 75 requested values, two-sided card, two image-backed two-page PDFs. Each page has an image-file variant and simulated 1,280/2,560-px JPEGs; PDFs were actually rendered with PDFium at 150/200 DPI. [Generator and limits](../../tools/t01/README-fixtures.md).
- Development manifest SHA-256: `e19aaaea6879627e96badc03be920e8cac203f00141191553020722486480141`. The main agent independently recomputed all 68 artifact hashes. The fixture author also checked two byte-identical regenerations, all image dimensions/regions, and independent Poppler PDF rendering.

The human review required by [ACCEPTANCE_PLAN](ACCEPTANCE_PLAN.md) remains pending. The runs below are explicitly exploratory runtime/resource and legibility diagnostics. None is a calibration or sealed benchmark measurement. Generated originals and every variant remain in the development/tuning partition forever; they must not enter the sealed benchmark. No personal documents were used.

## Configuration comparison

Every row used one slot, context 4,096, 1,024 reserved output tokens, all language-model layers on the GPU, flash attention, batch 512 / microbatch 128, image minimum 128, greedy decoding, seed 42, disabled host prompt cache, and no automatic runtime fitting. Four requests per row used actual PDF renders and simulated JPEGs. Images, JSON schema, streaming, and raw pre-sampling log probabilities worked together in all rows. All responses were schema-valid and all four requests retained the output reserve.

| Vision placement | KV | Image maximum | Load s | PDF 150 / 200 DPI s | JPEG 1280 / 2560 px s | Sampled total GPU peak MiB | Server private peak MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CPU | q8_0 | 512 | 2.675 | 8.551 / 8.539 | 10.643 / 10.455 | 4068 | 4499 |
| CPU | f16 | 512 | 2.652 | 8.607 / 8.576 | 10.227 / 10.419 | 4264 | 4757 |
| GPU | q8_0 | 256 | 2.701 | 1.493 / 1.408 | 3.017 / 3.102 | 4844 | 4515 |
| GPU | q8_0 | 512 | 2.812 | 1.700 / 1.580 | 3.226 / 3.369 | 4941 | 4649 |
| GPU | f16 | 512 | 2.724 | 1.590 / 1.551 | 3.225 / 3.172 | 5169 | 4924 |
| GPU | q8_0 | 1024 | 2.716 | 2.092 / 2.003 | 3.718 / 3.790 | 4998 | 4874 |

The measured starting profile for T01b is **GPU vision, q8_0 K/V cache, image maximum 1,024, context 4,096, PDF 150 DPI, at most two pages in these probe prompts**. Higher image budget preserves more visual detail while remaining within the observed resource envelope; this is an engineering starting point, not a calibrated quality decision. Production prompts/profile schemas can be longer: they must enforce their own context admission rather than assume that every pair of pages fits. CPU vision is a measured fallback if desktop GPU contention increases; it is materially slower here.

## Runtime behavior and envelope

The selected profile's [behavior evidence](evidence/t01a/behavior-gpu-q8-1024.json) confirms:

- A 1,280-px synthetic image with schema, streaming, and log probabilities completed; 29 probability entries were present, including nonzero pre-sampling log probabilities. Upstream source establishes the meaning of `post_sampling_probs=false`; these probabilities are not independently calibrated confidence.
- Closing a stream after eight nonempty content chunks freed the single slot in **0.0735 s**, confirmed by `/slots` reporting `is_processing=false`.
- A **ReadTimeout** before the first content chunk closed the stream; slot idle was confirmed **0.6354 s** later. The exact internal preprocessing phase is unknown. This tests socket timeout recovery, not the product's cumulative wall-clock budget.
- Terminating this run's server and starting it again reached health in **3.1437 s including termination**, below the 10-second release window. A subsequent request succeeded, and idle was confirmed. No `X-Conversation-Id` resumable-stream header was sent.
- Runtime listened on loopback, required an ephemeral API key, used `--cache-ram 0`, and disabled the web UI. The probe removed the key and terminated its server at completion. This does not substitute for future product crash-supervision tests.

The [envelope experiment](evidence/t01a/fixtures-envelope-gpu-q8-1024.json) tested one, two, and three pages for each of PDF 150 DPI, PDF 200 DPI, JPEG 1280, and JPEG 2560. Two pages fit the prompt plus a 1,024-token output reserve in every group; three did not. A short successful three-page answer was deliberately **not** counted as a valid reserved-budget envelope. The check uses actual `prompt_n + cache_n + reserve <= context`.

Official b11221 server timings combine vision encoding and prompt evaluation. They do not separately expose server image encoding duration. A separate [CLI encoder probe](../../tools/t01/encoding_probe.py) measured an actual 150-DPI PDF render: CPU/q8/512 **6718 ms**, CPU/f16/512 **6858 ms**, GPU/q8/256 **128 ms**, GPU/q8/512 **193 ms**, GPU/f16/512 **195 ms**, GPU/q8/1024 **368 ms**. These are the CLI's encoder timings and must not be reported as server-specific durations; [raw numeric evidence](evidence/t01a/encoding-helper.json) labels the distinct path. Detailed prompt/generation rates and sampled RAM/VRAM are retained in the content-free evidence JSON.

## Development legibility and localization

The [12-case diagnostic](evidence/t01a/fixtures-development-gpu-q8-1024.json) returned strict JSON for all cases. Against generated reference values it copied **69 of 75 values exactly**: Arabic cases had five differences in total, and one Devanagari value differed. The other scripts, the two-sided card, and both multipage PDFs matched their generated references in this run. Neither Arabic case was wholly correct. This warning is recorded before building any sealed benchmark. Forced string extraction in this probe is not the production abstention contract, so these numbers are not accepted-value error/completeness metrics.

Localization produced syntactically valid normalized boxes in six probes, with IoU **0.283–0.320** against tight reference-value regions. This is insufficient evidence for trusting tight field crops. T01b should initially use the specified whole-page alternative-resolution reading for V2; localization can be reconsidered only with evidence. The official runtime warns that grounding needs an image minimum of at least 1,024; the tested minimum was 128. These measurements do not establish reliable grounding.

## Verification integrity and remaining gates

The measurement harness has behavior tests for invalid/extra JSON fields, distinction between schema compliance and exact content, insufficient context reserve, timeout/cancellation, content-free output, and refusing another request after unconfirmed slot release. Six tests pass. An independent GPT-6 Sol/high review identified measurement weaknesses; fixes included output-reserve validation, idle enforcement, timeout/chunk naming, keeping both restart resource records, and nonzero exit on a top-level failure. The requested model/effort are recorded; the collaboration tool did not separately expose actual runtime settings.

Human case review remains outstanding. Digital JPEG degradation is not actual Telegram transport or camera-photograph evidence. The latest task instruction defers real Telegram validation, so no Telegram message or external inference was performed. T01b still requires at least 20 reviewed tuning cases, the production core, verification-signal calibration, frozen configuration, and per-page times. T01c still requires its sealed 40/20/10 corpus and all accepted quality criteria. T02–T08 have not started.

## Reproduction commands

Executed from the implementation worktree. Use an external, nonsynchronized development-data directory; the examples below are the actual local paths used in this run. Never point this exploratory tooling at real user documents.

```powershell
python -m uv venv .venv-t01a --python C:\Python314\python.exe
python -m uv pip compile tools/t01/requirements.txt --generate-hashes --output-file tools/t01/requirements.lock --quiet
.venv-t01a\Scripts\python.exe tools/t01/download_artifacts.py --root C:\Users\nikit\AppData\Local\TgBotDocsDev
.venv-t01a\Scripts\python.exe -m pytest tools/t01/test_runtime_probe.py -q
.venv-t01a\Scripts\python.exe tools/t01/fixture_probe.py --root C:\Users\nikit\AppData\Local\TgBotDocsDev --manifest C:\Users\nikit\AppData\Local\TgBotDocs\t01a-fixtures-dev-v5\manifest.json --output C:\Users\nikit\AppData\Local\TgBotDocsDev\measurements\fixtures-development-gpu-q8-1024.json --config gpu-q8-1024 --mode development
.venv-t01a\Scripts\python.exe tools/t01/runtime_probe.py --root C:\Users\nikit\AppData\Local\TgBotDocsDev --output C:\Users\nikit\AppData\Local\TgBotDocsDev\measurements\behavior-gpu-q8-1024.json --config gpu-q8-1024 --mode behavior
```

`fixture_probe.py --mode matrix` was run serially for all six configuration IDs; `--mode envelope` and `--mode localization` used `gpu-q8-1024`. The downloader is a reusable version of the executed provisioning procedure and is also checked against the already downloaded artifacts. Its SHA-256 verification is mandatory before extraction. Fresh-machine installation and product packaging remain T08 work.

Official sources: [model repository](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/tree/1cd86afb9a95c410a6038ab3b40d8b578c892266), [runtime release](https://github.com/ggml-org/llama.cpp/releases/tag/b11221), [pinned server interface](https://github.com/ggml-org/llama.cpp/blob/b11221/tools/server/README.md), [disconnect/resumable-stream semantics](https://github.com/ggml-org/llama.cpp/blob/b11221/tools/server/README-dev.md). Runtime behavior claims above come from local measurements, not source documentation alone.
