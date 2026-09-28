# Sources and Status of Claims

Analysis date: 2026-09-28. This document contains links and analysis conclusions, not a copy of the task or conversation.

## S-01 — Initial Idea

- Provided file: `C:/CodeProj/TT.txt`, outside the repository.
- SHA-256: `28B3D1DD67AB7BBB783625A546930C1C2DF405F4E0420B279D3EFA4505F38179`.
- The text was read in full. The file was not changed or copied into the project.
- Mention of an API key and server is part of the idea, not permission to use secrets, create resources, or transfer data.
- Passport and residence permit illustrate configurations; they are not a closed list of types.

## S-02 — Conversation “Introduction to Product Architecture”

[Pinned conversation](chatgpt-conversation://6ab6de5e-c80c-83ed-af7d-0531ee43f45b), ID `6ab6de5e-c80c-83ed-af7d-0531ee43f45b`.

All four available user messages were read. The reading tool returned the whole page without a next cursor. Two long AI responses, about classification and extraction, were limited to their first 20,000 characters each; their endings were not checked. Direct user clarifications are fully available. AI suggestions are not considered user decisions.

| Part | Direct statement | Implication |
| --- | --- | --- |
| S-02-U1 | The developer wants to understand the architecture, do reviews independently, and learn through practice | Explain the purpose, options, and consequences of decisions |
| S-02-U2.1 | OCR can make mistakes; a text LLM cannot see the original photo | Justify accuracy checks; the pipeline has not yet been selected |
| S-02-U2.2 | The type must not be identified incorrectly; if an LLM examines the document, it must be local | A cloud LLM for the document is ruled out |
| S-02-U2.3 | Multiple pages/files are required, including both sides of a card | One document is not the same as one message |
| S-02-U2.4 | Ordinary, imperfect phone photographs are needed | Acceptance must include real distortions |
| S-02-U2.5 | “There definitely must not be a size limit” | Do not replace the preference with a limit of our own without a decision |
| S-02-U3 | “I have no corrections or clarifications”; request to analyze classification and leave the choice open | This is not a choice of all subsequent AI recommendations |
| S-02-U4 | Request to analyze extraction in detail | Continue the design taking this discussion into account |

## S-03 — Current Task

Prepare the foundation before specific implementation; agree on important decisions; split development tasks across files; do not implement the project in this session; remove the unnecessary task-copy file and do not move `TT.txt` there.

## S-04 — First Round of Answers, 2026-09-27

- **S-04-A1:** “Arbitrary documents already in the first version.” No closed catalog of types was selected.
- **S-04-A2:** “Only my PC; we will discuss the server separately” — answer to the question about local placement of processing without external AI services.
- **S-04-A3:** The current PC is used for now. The task is a finished working product for handover to the customer; the customer's server has not yet been selected. A server will be needed later for scaling and possibly a more capable self-hosted LLM. The number of users and wait time are unknown.

This is not permission to install models, begin implementation, or purchase a server in the current session.

## S-05 — Second Round of Answers, 2026-09-27

- **S-05-A1:** The following scenario was accepted: a single image/PDF starts processing automatically; an album is a set of pages; several separate files are collected in “Several pages” mode with a “Process” button. One set corresponds to one document; different documents are sent separately.
- **S-05-A2:** Each user has their own extraction settings.
- **S-05-A3:** Temporary files on disk are allowed. Settings and necessary access data are stored persistently; originals, OCR text, and results are deleted after a response/cancellation/error/timeout. Content is not included in logs and backup. Telegram copies are outside this boundary.

## S-06 — Third Round of Answers, 2026-09-27

- **S-06-A1:** Personal profiles from text instructions, with preview and confirmation before saving; multiple profiles and clarification when selection is ambiguous.
- **S-06-A2:** Partial English text response: readable fields and Missing / Unreadable / Ambiguous statuses without guesses; for a doubtful type, clarify the type/profile or request a new photo. A JSON file is not required for the first version.
- **S-06-A3:** Standard Bot API; the user explicitly accepts Telegram's 20 MB download limit. This clarifies the earlier preference in S-02-U2.5; it does not silently change it. A local Bot API Server is not needed for the first version.

## S-07 — Fourth Round of Answers, 2026-09-27

- **S-07-A1:** Python + aiogram + PostgreSQL selected.
- **S-07-A2:** Direct Qwen3-VL-4B-Instruct Q4_K_M via llama.cpp selected; first, check it on the PC. If quality/resources are insufficient, the experiment results require review with the developer, not a hidden replacement.
- **S-07-A3:** One bot instance, long polling, one recognition task at a time on the GPU, an application queue, and private chats only were accepted. After an emergency restart, unfinished documents are deleted and must be sent again by the user; profiles are retained.

## S-08 — Fifth Round of Answers, 2026-09-27

- **S-08-A1:** Extraction of individual fields and lists of records with columns. Arbitrary calculations and free-form reports are not added.
- **S-08-A2:** Documents in any language are required; the operational wording is clarified in S-09-A1.
- **S-08-A3:** Sign-in lasts until restart or /logout; a password change takes effect on restart; one unfinished document per user; 15 minutes of inactivity for collection/clarification and 30 minutes for processing, then an error and cleanup. Parameters are configurable.

## S-09 — Sixth Round of Answers, 2026-09-27

- **S-09-A1:** Any language without a whitelist; attempt extraction while preserving the script and honestly report uncertainty/inability to read. A diverse acceptance sample does not mean all languages in the world have been tested.
- **S-09-A2:** The following test set was accepted: 40 readable documents, 20 challenging photographs, 10 negative cases. Zero incorrectly accepted values/profiles on the set; at least 90% of requested fields/cells in the readable portion. Failure requires improvement/review with the developer, without promising 100% accuracy on any future documents.
- **S-09-A3:** Target platforms are Windows and Linux x86-64 with an NVIDIA GPU. The delivery includes reproducible launch, configuration, migrations, and licenses; both platforms are checked before handover. The specific server/scaling comes later, with no purchase/configuration now.

## S-10 — Decision Authority, 2026-09-27

Direct developer statement after the independent pre-development review:

- **S-10-A1:** The original customer provided the core product idea and the initial requirements (S-01). From this point onward, the developer makes all product, architecture, implementation, and engineering decisions; additional customer approval is not required unless the developer explicitly says otherwise.
- **S-10-A2:** Where documents refer to customer or developer approval, or leave final authority unclear, the developer is the final decision-maker.
- **S-10-A3:** The core purpose and explicit constraints of the original brief are preserved unless the developer explicitly decides to change them.
- **S-10-A4:** Purely technical details that follow from the requirements, constraints, and engineering practice are decided by the implementing agent and documented with their reasoning. They are not presented as developer answers, and the developer can override them.

## S-11 — T01 Escalation Path, 2026-09-27

- **S-11-A1:** If T01 shows that the selected configuration does not meet the accepted criteria on the current PC, remediation stays within this PC's hardware (6 GiB VRAM, 16 GiB RAM): configuration tuning, abstention and verification signals, a local OCR cross-check, and other self-hosted models that fit this hardware. Moving inference to a stronger model on a separate GPU server is not a permitted escalation path. Once these options are exhausted, narrowing the v1 scope or revising the acceptance criteria requires a separate explicit developer decision.

## S-12 — Scheduling Between Documents, 2026-09-27

- **S-12-A1:** When several documents are active, the GPU alternates between them: after each model call, the next active document gets a turn, so short documents are not blocked by a long one. The accepted consequence: under load, a long document takes longer in wall-clock time and keeps its temporary files longer, while its 30-minute budget counts only its own processing.

## S-13 — Profile Changes During Processing, 2026-09-27

- **S-13-A1:** Profiles can be edited while the user's document is queued or being processed, but not while the bot waits for the user's answer about that document. An edit does not affect a document already in progress, which keeps its snapshot of the profiles. A question about the document waits until an open profile draft is saved or cancelled. This replaces the earlier engineering choice of read-only Settings during a whole job (ED-004).

## S-14 — T01c Timing and Acceptance, 2026-09-28

Direct developer decision:

- **S-14-A1:** Defer T01c benchmark preparation and the sealed run until the complete product is available through Telegram.
- **S-14-A2:** T02 may proceed after T01b is reviewed, calibrated, and frozen; T01c is not a prerequisite for starting T02.
- **S-14-A3:** Freezing T01b does not accept recognition quality. The T01c benchmark remains required acceptance against the existing criteria.
- **S-14-A4:** Continue T02–T08 in order after the T01b freeze. Local T07 resilience checks and T08 preparation may proceed before the final real-Telegram end-to-end test and deferred benchmark, but they do not complete those acceptance checks.
- **S-14-A5:** Perform the final real-Telegram end-to-end test jointly with the developer after the complete product is available through Telegram.

## S-15 — Local Dependency Installation Authorization, 2026-09-28

Direct developer instruction:

- Install missing PostgreSQL and any subsequent dependencies needed on the current PC autonomously, without asking again. Official native PostgreSQL 18.6 ZIP is installed and the local database is verified. This authorization covers local dependencies only; it does not authorize remote resources or messages.

## S-16 — Development Continuation and Usage Guard, 2026-09-28

Direct developer instruction:

- While the developer is absent, continue independent work and defer decisions that require the developer.
- Make small, logical changes; run the relevant checks and commit each verified unit. Local dependency installation remains authorized under S-15; this grants no authority for remote resources or messages.
- Monitor the five-hour usage window. When less than 10% remains, save the precise stop point and stop all work. Resume in the same thread only after the usage window resets and wait an additional two minutes.

## S-17 — Completion Task and Dependency Installation, 2026-09-28

Direct developer instruction to Claude Code:

- Continue implementation to the finished product under the existing requirements, specifications, architecture, roadmap and instructions, autonomously and in order; use subagents and parallel work where tasks are independent or an independent review improves quality; commit logical, verified units.
- Work only on this PC; local services may be started. No deployment, no push, and no final real-Telegram E2E: that test is performed together with the developer.
- Do not change product scope, acceptance criteria or fundamental architecture to pass tests; stop at a genuine developer decision gate and state the decision needed.
- Missing dependencies such as Docker or WSL may be installed without asking. This session is not elevated; enabling Windows virtualization features and rebooting remain the developer's action.

## E-01 — Hardware Check

Only hardware specifications were read using Windows CIM and `nvidia-smi`, on 2026-09-27:

- Windows 11 Home x64, version 10.0.26200.
- AMD Ryzen 5 5600H, 6 cores / 12 threads.
- 16 GiB RAM installed; the OS reports about 13.9 GiB of physical memory available to it.
- NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB VRAM, driver 581.80; integrated AMD Radeon Graphics is also present.

These are specifications, not benchmark results. Models were not run; the suitability of a specific model has not yet been proven.

## Recording Rule

Direct requirements are preserved in meaning. Proposals are marked as proposals. Accepted decisions include their rationale and consequences; significant architectural choices are recorded as ADRs. No answer does not mean agreement. The current explicit instruction takes precedence over the old idea. Engineering decisions made under S-10-A4 are labeled ED in the [decision register](OPEN_QUESTIONS.md).
