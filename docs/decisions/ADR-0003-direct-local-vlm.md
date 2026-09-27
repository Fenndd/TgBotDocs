# ADR-0003. Direct Local VLM as the Initial Architecture

Date: 2026-09-27. Status: accepted as the initial choice, subject to mandatory experimental verification. Basis: [S-07-A2](../requirements/SOURCES.md).

## Options

1. Direct Qwen3-VL-4B-Instruct Q4_K_M through llama.cpp.
2. Lighter Qwen3-VL-2B.
3. Separate OCR + VLM from the start of development.

**Option 1 was selected.** An open set of documents and free-form instructions require general-purpose interpretation. The model receives the image, so it is not limited by possible loss of information in intermediate OCR text. Separate OCR does not become mandatory without a measurable benefit.

## Specific Initial Candidate

Official `Qwen/Qwen3-VL-4B-Instruct-GGUF`, language component Q4_K_M, initially vision/mmproj FP16, llama.cpp with CUDA. If memory is insufficient, T01 compares placing vision on the CPU and using a smaller context/page batch; switching to another model or OCR requires review of the results with the developer.

[Official GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF) and the [multimodal API](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) confirm the format and runtime capabilities. Model weight size is not the same as required VRAM. Detailed comparison: [RECOGNITION_OPTIONS.md](../architecture/RECOGNITION_OPTIONS.md).

## Boundaries

- One active inference request; type identification, profile matching, instruction conversion, and extraction use the same local runtime.
- Classification and extraction are different contracts. An absent profile triggers dialogue, not extraction of all fields.
- A large PDF is processed by page/batch, and results are linked to the source pages.
- The model is not given tools, code execution, or arbitrary network access.
- JSON/type validation helps control the program but does not prove that the read characters are correct.
- A direct VLM can make mistakes; a schema, source reference, and repeated question to the same model do not provide an independent guarantee.

## Mandatory Verification

T01 measures accuracy, abstentions, time, RAM/VRAM on the current PC. Only successful results against the agreed criteria allow integration to continue. Failure requires a decision about settings/candidate/architecture; a hidden cloud fallback is prohibited.

The model was not downloaded or tested in the current task. The architectural path was accepted; this is not a claim of achieved quality.

## Clarification, 2026-09-27

T01 runs in three stages: runtime feasibility, calibration of the recognition core on the tuning set, and one sealed benchmark run ([T01](../../specs/T01-recognition-baseline.md)). Statuses returned by the model pass through the verification layer of [ADR-0004](ADR-0004-abstention-and-verification.md), which can only downgrade them. If T01 fails, remediation stays on the current PC (S-11-A1) in the order of ADR-0004; other models are compared only within this hardware.
