# ADR-0001. Local Processing on the Current PC

Date: 2026-09-27. Status: accepted for the current phase. Basis: direct user responses [S-04-A2/A3](../requirements/SOURCES.md).

## Context

The original idea proposed the ChatGPT API. Later, the user required a local LLM. In the current discussion, the user selected only their own PC; the server is to be discussed separately after a working product has been created.

## Boundaries Considered

1. The current PC or a preselected controlled server.
2. The current PC only for now, with server deployment later — the selected option.
3. Local images and an external LLM for derived text — not selected.

## Decision

Processing of images, OCR text, and extracted data by models runs locally on the current PC. External AI and a hidden cloud fallback are not part of the selected architecture. Telegram remains the external channel for documents and responses.

The future development outcome is a finished product ready for delivery to the customer. Selecting a server, scaling, and using a stronger self-hosted model are considered separately. This ADR does not select a specific model, runtime, or server platform.

## Consequences and Checks

- Technical candidates are evaluated against the current PC's 16 GiB RAM and 6 GiB VRAM.
- The ability to run and the quality must be measured in the next development phase; neither has been checked yet.
- Acceptance must verify data paths, the absence of external AI requests, and diagnostic leaks.
- Downloading weights/updates over the network and sending a document for inference are different actions; installation is not authorized by the current task.
- The unknown future server workload is not replaced with a fictional SLA.
- Portability and a launch guide are designed before delivery; readiness for a specific unknown server is not promised.

## Clarification, 2026-09-27

S-11-A1 makes the current PC's hardware (6 GiB VRAM, 16 GiB RAM) the limit for v1 recognition: if T01 fails, remediation stays on this PC, and a stronger GPU server is not a v1 escalation path. "Local" means self-hosted inference on the machine that runs the bot, with no external AI. The delivered product runs on the deployment machine with the configuration verified on this hardware class; a server for scaling or a stronger model remains a post-v1 topic (S-04-A3). The remediation order is in [ADR-0004](ADR-0004-abstention-and-verification.md).
