# Significant Decisions Log

Basis date: 2026-09-27. Accepted decisions are linked to the developer's direct answers in [SOURCES](../requirements/SOURCES.md).

| ADR | Status | Subject |
| --- | --- | --- |
| [ADR-0001](ADR-0001-local-processing.md) | Accepted | Processing on the developer's PC; customer's server at a later stage |
| [ADR-0002](ADR-0002-application-stack.md) | Accepted | Python/aiogram/PostgreSQL, standard Bot API, long polling, and a single instance |
| [ADR-0003](ADR-0003-direct-local-vlm.md) | Accepted with mandatory experiment | Direct Qwen3-VL-4B Q4_K_M / llama.cpp and a condition for reconsideration |

Main product decisions that do not require a separate ADR are recorded in the [decision register](../requirements/OPEN_QUESTIONS.md).

The accepted architecture does not mean that the product has been implemented or that model quality has been proven. When reconsidering a choice, preserve the rationale for the previous choice and its status, and link to the superseding record. The current system is described in [ARCHITECTURE](../architecture/ARCHITECTURE.md).
