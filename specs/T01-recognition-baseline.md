# T01 — Direct Recognition Check on the Current PC

Status: ready for implementation as a separate next task. Date: 2026-09-27. This is the first technical development task; no experiment is run in the planning session.

## Goal and Basis

Check the user-selected Qwen3-VL-4B-Instruct GGUF Q4_K_M through local llama.cpp on the current PC. Obtain measurements of memory, time, and direct extraction quality from original pages before building the product around the model.

Basis: [PRODUCT_SPEC](../docs/requirements/PRODUCT_SPEC.md), REQ-002/005/007/011–014/016/022; [recognition options and hardware](../docs/architecture/RECOGNITION_OPTIONS.md); [test strategy](../docs/testing/TEST_STRATEGY.md). The user selected the model and direct path in the fourth round; alternatives are not a mandatory part of T01.

## Scope and Dependencies

- Direct visual input: an image or images of PDF pages and an extraction instruction. Do not introduce a mandatory separate OCR.
- Windows 11 Home x64, 16 GiB RAM (about 13.9 GiB available to the OS), RTX 3060 Laptop GPU 6 GiB VRAM. Do not count OS memory as free process memory.
- One GPU task at a time. First measure one configuration without competing recognition.
- Prepare materials and independent ground truth according to the accepted [ACCEPTANCE_PLAN](../docs/testing/ACCEPTANCE_PLAN.md): 40 readable + 20 difficult + 10 negative cases, zero incorrectly accepted values/profiles, and ≥90% completeness for readable fields/cells. Contract — [CONTRACTS](../docs/architecture/CONTRACTS.md). The set and criteria do not need to be agreed again; specific ground truth is reviewed by a person before the benchmark measurement.
- Specific versions of llama.cpp, weights, and the vision component are needed, as well as image, context, and generation parameters. These are recorded during implementation; versions are not invented now.
- Use synthetic/permitted examples for the experiment; personal-data handling and deletion must comply with [SECURITY](../docs/security/SECURITY.md). Do not retain real originals as a benchmark corpus without a separate basis.

## Expected Result and Sequence

1. Record artifact versions/hashes, license, CPU/GPU configuration, vision component, and baseline memory usage. Explain the selected settings.
2. Check one readable document: a local visual request, execution of the instruction, and obtaining a response conforming to the contract.
3. Check PNG/JPEG, a multi-page PDF, both sides of one card, and another document type outside passports/residence permits. Include agreed rotations, perspective, shadow/glare, blur, and cropping.
4. Check an unreadable field, a missing field, ambiguous characters, conflicting values across pages, and a doubtful type. A refusal/partial result must be distinguishable from successful reading.
5. Measure load time, first and repeated request, processing time per document, peak RAM/VRAM, errors, and stability on a longer set. State the page count/resolution and context for each case.
6. Compare results with ground truth; show incorrectly accepted values, omissions, refusals, partial results, and correct full responses separately. The external English response must not add unrequested fields.
7. Prepare a report with the limits of the verified configuration and a conclusion: continue with the selected path, change parameters, or return a significant choice for agreement.

If the configuration does not fit or does not meet the criteria, this is a verified negative result, not permission to automatically choose another model, cloud, or hybrid. CPU/GPU allocation and reducing context/resolution are considered with an impact assessment; significant changes require agreement.

## Checks and Completion Criteria

- The experiment is reproducible from the described versions, inputs, and parameters; actual commands are added only after implementation and verification.
- Processing remains local; document information is not sent to external AI services, logs, or backup.
- Invalid/incomplete JSON or a contract violation does not count as successful extraction; format compliance does not count as proof that values are correct.
- Deletion of temporary originals and derived data on completion/error is confirmed; cancellation and TTL are checked in the available experimental interface or explicitly remain unverified until integration.
- Actual measurements for the accepted set and a report on the criteria are available. On success, work may proceed to T02; on failure, record the negative result and return a significant revision to the developer. Conclusions must not be substituted by lowering the threshold retroactively.

## Exclusions

Telegram bot, database, profiles, customer server, load SLA, fine-tuning, installation of all alternatives, and mandatory comparison with hybrid are out of scope. One successful example does not prove arbitrary documents; a T01 result does not mean the product is ready.
