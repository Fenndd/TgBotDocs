# T01 — Direct Recognition Check on the Current PC

Status: ready for implementation as three consecutive development tasks, T01a, T01b, and T01c. Date: 2026-09-27; revised after the independent review. No experiment is run in the planning session.

## Goal and Basis

Check the user-selected Qwen3-VL-4B-Instruct GGUF Q4_K_M through local llama.cpp on the current PC, and decide on measurements whether to build the product around it. Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-002/005/007/011–014/016/022/031; [ADR-0003](../docs/decisions/ADR-0003-direct-local-vlm.md); [ADR-0004](../docs/decisions/ADR-0004-abstention-and-verification.md); [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md); [CONTRACTS](../docs/architecture/CONTRACTS.md). The user selected the model and the direct path in the fourth round (S-07-A2); remediation after a failure stays on this PC (S-11-A1).

## Common Boundaries

- Windows 11 Home x64, Ryzen 5 5600H, 16 GiB RAM (about 13.9 GiB available to the OS), RTX 3060 Laptop GPU with 6 GiB VRAM. Do not count OS memory as free process memory.
- One GPU task at a time; measurements are serialized.
- Processing stays local; document information is not sent to external AI services, logs, or backup. Use synthetic or permitted examples; do not retain real originals as a benchmark corpus without a separate basis. Personal-data handling and deletion comply with [SECURITY](../docs/security/SECURITY.md).
- Versions, hashes, and parameters are recorded as they are used; nothing is invented in advance. Commands are added only after they have run.

## T01a — Runtime Feasibility

Scope: a pinned llama.cpp build (release or commit, CUDA version, driver) and the official GGUF and mmproj files with SHA-256 hashes, launched with the profile in [OPERATIONS](../docs/operations/OPERATIONS.md). No application code.

1. Measure peak VRAM and RAM, load time, image encoding time, and prompt processing and generation speed for: mmproj on GPU and on CPU; f16 and q8_0 KV cache; several image token budgets; PDF pages rendered at 150 and 200 DPI; photos at 1,280 and 2,560 px.
2. Determine the resource envelope: how many pages of each kind fit one call together with the prompt and a reserved output budget.
3. Verify the runtime behavior the design relies on: schema-constrained output with images; raw token probabilities together with images and a schema; release of the slot after a streaming call is cancelled, as reported by the slots endpoint, and the release time; behavior at timeout; restart and health-check time; whether the model can localize a field region for the second-reading signal.
4. Run a development set of 10–15 documents that covers all six scripts of the script matrix, two sides of a card, a multi-page PDF, and both Telegram image paths. This gives a qualitative legibility signal; it is not a benchmark. These documents may later join the tuning set, never the benchmark.

Result: a feasibility report with the envelope, the selected launch profile, and the verified runtime behaviors. Continue to T01b if at least one configuration within the PC's limits processes one A4 page at 150 DPI or one 1,280-px photo per call with the prompt and output budget, schema-constrained output works with images, and cancellation is confirmable or a restart completes within the release window. Otherwise, the report lists the within-PC options of S-11-A1 for the developer. A script that is never read correctly on the development set is reported before the benchmark is built.

## T01b — Recognition Core and Calibration

Scope: the recognition core as the future production module of T05, not a throwaway script. It includes the model adapter (streaming, cancellation, probabilities), page preparation with pypdfium2 and Pillow in a child process, matching and extraction prompts under the v1 contract, lazy batches and merging, validation, the verification layer, and a command-line runner over a case manifest. It uses the toolchain of [ADR-0005](../docs/decisions/ADR-0005-runtime-supervision-and-packaging.md). Profiles are hand-authored fixtures in the canonical schema; the instruction compiler arrives in T03, and T07 measures again with compiled profiles.

1. Prepare the tuning set (ACCEPTANCE_PLAN) and its ground truth.
2. Implement the contract, merging, and signals V1–V4; add V5 only if needed and within the PC's resources.
3. Calibrate thresholds and the enabled signals on the tuning set; produce risk–coverage curves.
4. Freeze versions, prompts, thresholds, parameters, and the manifest format; measure per-page times of the frozen configuration for admission control.

Result: the frozen configuration, the calibration report, and the per-page times.

## T01c — Benchmark Gate

1. Prepare the sealed 70-case benchmark (40 readable, 20 difficult, 10 negative) with delivery paths and reviewed ground truth. Preparation may run in parallel with T01a and T01b; benchmark cases are never used for tuning.
2. Run the benchmark once with the frozen configuration.
3. Report per ACCEPTANCE_PLAN: incorrectly accepted values, incorrect automatic profiles, completeness with its denominator, zero-error bounds, per-group metrics, lists, refusals, resources, p50/p95 times, per-page times, and failures. The external English response must not add unrequested fields.

Pass: continue to T02. Failure: record the verified negative result, analyze errors on the tuning set and replaced cases, and follow the remediation order of ADR-0004 on this PC. When those options are exhausted, the developer decides whether to narrow the v1 scope or revise the criteria. Conclusions must not be substituted by lowering the threshold retroactively.

## Checks and Completion Criteria

- Each stage is reproducible from the recorded versions, inputs, and parameters.
- Invalid or incomplete JSON or a contract violation does not count as successful extraction; format compliance does not count as proof that values are correct.
- The runner deletes temporary renders and intermediate outputs after each case; only manifests, metrics, and content-free logs remain. Cancellation and deadlines in product flows are verified in T02–T06.
- The recognition core and the runner of T01b become product code for T05 and T07. The exploratory scripts of T01a are not product code.

## Exclusions

Telegram bot, database, instruction compiler, state machine, customer server, a stronger GPU server (S-11-A1), load SLA, fine-tuning, installation of all alternatives, and a mandatory comparison with a hybrid path are out of scope. One successful example does not prove arbitrary documents; a T01 result does not mean the product is ready.
