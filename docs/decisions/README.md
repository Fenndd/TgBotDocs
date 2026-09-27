# Significant Decisions Log

Basis date: 2026-09-27. Accepted decisions are linked to the developer's direct answers in [SOURCES](../requirements/SOURCES.md).

| ADR | Status | Subject |
| --- | --- | --- |
| [ADR-0001](ADR-0001-local-processing.md) | Accepted; clarified by S-11 | Local self-hosted processing; v1 recognition fits the current PC's hardware |
| [ADR-0002](ADR-0002-application-stack.md) | Accepted; composition refined by ADR-0005 | Python/aiogram/PostgreSQL, standard Bot API, long polling, and a single instance |
| [ADR-0003](ADR-0003-direct-local-vlm.md) | Accepted with mandatory experiment | Direct Qwen3-VL-4B Q4_K_M / llama.cpp and a condition for reconsideration |
| [ADR-0004](ADR-0004-abstention-and-verification.md) | Accepted engineering decision (S-10-A4) | Downgrade-only verification signals, calibration on the tuning set, and the T01 remediation order on the current PC |
| [ADR-0005](ADR-0005-runtime-supervision-and-packaging.md) | Accepted engineering decision (S-10-A4) | Child-process supervision, streaming cancellation, database access mode, packaging for Windows and Linux, and toolchain |

Main product decisions that do not require a separate ADR are recorded in the [decision register](../requirements/OPEN_QUESTIONS.md).

The accepted architecture does not mean that the product has been implemented or that model quality has been proven. When reconsidering a choice, preserve the rationale for the previous choice and its status, and link to the superseding record. The current system is described in [ARCHITECTURE](../architecture/ARCHITECTURE.md).
