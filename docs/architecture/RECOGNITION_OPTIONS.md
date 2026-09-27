# Local Recognition Options

Status: overview of the alternatives considered. Direct Qwen3-VL-4B Q4_K_M / llama.cpp was selected — [ADR-0003](../decisions/ADR-0003-direct-local-vlm.md). Official sources were checked on 2026-09-27; models were not downloaded or run. Alternatives considered after a T01 failure must fit the current PC's hardware (S-11-A1); the remediation order is in [ADR-0004](../decisions/ADR-0004-abstention-and-verification.md).

## Basis and Boundaries

- v1 accepts arbitrary documents, user instructions, and ordinary phone photos: [sources](../requirements/SOURCES.md), [specification](../requirements/PRODUCT_SPEC.md).
- Current PC: Windows 11 Home x64, Ryzen 5 5600H, 16 GiB installed RAM (about 13.9 GiB of physical memory available to the OS), RTX 3060 Laptop GPU with 6144 MiB VRAM. This is not a measurement of free memory or a benchmark.
- Local processing runs on this PC. The customer's server, workload, and acceptable response time are not yet known.
- The user's latest confirmed decisions: a single file is processed automatically; an album forms a set; `Several pages` mode is completed with the `Process` button; one set represents one document; profiles are personal.
- Temporary files on disk are allowed. The original, OCR, and result are deleted after a response, error, cancellation, or TTL; content is not placed in logs or backups. The TTLs are defined in [OPERATIONS](../operations/OPERATIONS.md).

## Direct VLM and Separate OCR

**Direct VLM** receives the original page images and the user's instruction. It can read text and interpret field layout at the same time. This avoids requiring that only OCR text be passed on, but it does not eliminate reading errors or invented values.

**OCR/document parser + interpreter** first obtains text and layout, then extracts the required fields. Layout may help with long documents and finding the source excerpt. If the interpreter sees only OCR text, the user's concern about lost characters remains. The option of also passing the original is a separate hypothesis to test.

An OCR+VLM combination **has not been proven necessary**: general-purpose VLMs have direct visual input and OCR capabilities. A comparison of the direct and combined paths should show whether quality and verifiability justify the extra memory, latency, and complexity. [Qwen3-VL model card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), [official repository](https://github.com/QwenLM/Qwen3-VL).

## Candidates for a Future Experiment

| Candidate | Runtime and purpose | Verified data | What is not proven |
| --- | --- | --- | --- |
| Qwen3-VL-2B-Instruct, official GGUF Q4_K_M | llama.cpp with CUDA; general-purpose direct visual input and user instruction | Language GGUF 1.11 GB; vision component FP16 819 MB or Q8 445 MB; Apache-2.0 | Sufficiency for small text, exact numbers, ambiguous fields, and imperfect photos |
| Qwen3-VL-4B-Instruct, official GGUF Q4_K_M | Same runtime; comparison with a larger model under the same contract | Language GGUF 2.5 GB; vision FP16 836 MB or Q8 454 MB; Apache-2.0 | Advantage on our documents, ability to fit entirely in VRAM, and acceptable speed |
| PaddleOCR-VL-1.6, 0.9B | Official PaddleOCR/PaddlePaddle pipeline; alternative parsing of page text and structure | Text, tables, formulas, charts, seals; full pipeline and limited Transformers path; Apache-2.0 | Extraction of arbitrary user-defined fields without a separate interpreter and memory usage of the full pipeline |

The sizes in the table are file sizes in decimal GB/MB, **not RAM/VRAM requirements**. Additional memory is needed for vision, context/KV-cache, computation, and page processing. The 4B model in FP16 has an 8.05 GB language file: a full-GPU variant at this precision does not fit in 6 GiB VRAM. Quantization and CPU/GPU distribution require separate verification.

Official model cards and files:

- [Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct), [GGUF](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF), [file sizes](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/tree/main).
- [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), [GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF), [file sizes](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/tree/main).
- [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6).

## Runtime, Pages, and Structured Output

For Qwen, the official GGUF confirms compatibility with llama.cpp and CUDA/CPU. llama.cpp has a Windows path and a local HTTP API; the vision component can run on the CPU. This is a fallback way to distribute the load, not a promise of speed. [Windows/CUDA](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md), [multimodal API](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

Qwen supports multiple images. The proposed PDF path is local conversion of pages to images; joint or batched submission will be determined by the experiment. The model's advertised large context does not prove that such context is available on the current PC. Combining sides, page order, and resolution of value conflicts remain the application's responsibility.

llama.cpp constrains the response to a subset of JSON Schema through `response_format`. The expected structure should also be described in the prompt: the schema is not added to it automatically. Valid JSON does not guarantee correct values. The internal contract may be common to arbitrary fields, but the specific schema requires agreement. [JSON Schema documentation](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md).

PaddleOCR accepts PDFs and lists of images, processes pages, and returns blocks, coordinates, and content. Its JSON is a recognition structure, not ready-to-use user fields. Merging results is supported, but the application is responsible for the semantics of a single document. [Pipeline documentation](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html).

PaddleOCR-VL-1.6 specifies PaddlePaddle ≥3.2.1 and PaddleOCR ≥3.6.0; the limited Transformers example requires Transformers ≥5.0.0. For the PaddlePaddle/Transformers GPU path, the documentation specifies CC ≥7.0 and CUDA ≥11.8. vLLM/SGLang/FastDeploy do not run natively on Windows; a Docker path is provided. A recommendation for RTX 3060 does not prove suitability for a 6 GiB Laptop GPU. Components are not being installed now.

The llama.cpp runtime uses MIT; PaddleOCR uses Apache-2.0. Product delivery requires licenses/notices for the selected artifacts and a review of shipped dependencies. [llama.cpp LICENSE](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE), [PaddleOCR LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE).

## Criteria for a Future Experiment

1. The same agreed dataset with ground-truth types and exact fields: documents beyond passports/residence permits, different languages and layouts, both sides of an ID card, a multi-page PDF, and phone image distortions.
2. Check the type and each field separately: incorrect values, omissions, guesses, appropriate abstention, conflicts between pages, and the link between a value and its source page/excerpt.
3. Measure the selected direct 4B first; comparison with a combined path is possible after an agreed review and is not required for T01. Record quantization, resolution, number of pages, context, and runtime.
4. Measure peak RAM/VRAM, time for first processing and repeat requests, time per document, and stability on long sets. Do not substitute model file size or someone else's benchmark for a result.
5. Check the JSON contract, model errors, temporary-data cleanup after response/error/cancellation/TTL, and absence of content in logs/backups.
6. Use the adopted [quality criteria](../testing/ACCEPTANCE_PLAN.md); derive server requirements after measurements and clarification of the workload.

The staged experiment is defined in [T01](../../specs/T01-recognition-baseline.md), and the verification signals are in ADR-0004.

Speed, quality, fit, and data cleanup have **not yet been verified by execution**. The method, model, and runtime were selected by the user; suitability must be confirmed by T01. This overview does not authorize installing models or starting implementation during the planning session.
