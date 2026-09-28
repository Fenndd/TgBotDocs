# T03 Progress and Open Verification

Date: 2026-09-28. Status: T03 local implementation and compiler checks verified; T04 is active. T02's local foundation checks are complete, and T01b remains frozen. Recognition quality is not accepted. The controlled product check made no real Telegram API request or benchmark run.

## Implemented Locally

- `ProductApplication` wires private-chat access, the menu, and Settings/profile dialogues through owner-scoped per-user actors. The access path covers password-message deletion, per-user lockout, a content-free global-surge alert, logout, restart/stale-update handling, and preventing document intake before sign-in.
- Profile and Settings work is routed through each user's actor. A profile is presented for explicit human review; saving requires the user's confirmation. The local profile schema and owner isolation remain separate from recognition quality claims.
- The instruction compiler separates three concerns: whether the instruction positively requests computing a new value; a complete audit of the requested document types, scalar fields, and list columns; and generation of a draft inventory. Reading a total or average already printed in a document is extraction, while a request to calculate a new value is unsupported. “Do not calculate” is a negative constraint, not a request for computation. Unsupported requirements must produce clarification without a partial inventory.
- The audit inventories every requested type, field, and list column before profile compilation. The compiler's private runtime grammar constrains positional arrays with `prefixItems`, `minItems`, and `maxItems`, and omits the `items` property for compatibility with the local grammar implementation. This private output grammar does not change the public profile shape, model runtime settings, or frozen recognition core/configuration.
- Saved drafts still require a human preview and explicit confirmation. A valid JSON response or a passing structural check is not treated as confirmation that the user requested the right extraction profile or as recognition-quality acceptance.

## Real-Model Checks and Pending Acceptance

A prior real-model negative example returned a partial profile despite unsupported nested-list/calculation requirements. The revised compiler separates calculation intent from full inventory audit. Focused probes now pass on the frozen runtime configuration hash `dd1d01a0e8ff878a60b7b4bf61b6bcb20939cd5bd5695bed4eaa79a55ea633f6`, with `environment_mismatches=[]`:

- “Extract the printed total and average. Do not calculate values.” produced one draft and no questions; input sizes were 165, 540, and 887 tokens across compiler calls.
- “Orders each with nested item rows” plus a request to calculate an average produced zero drafts and three clarification questions; input sizes were 164 and 539 tokens.
- A supported two-type invoice/certificate instruction produced two drafts and no questions; its flat list retained the two requested columns (text and number), and its calendar-date validator used `%Y-%m-%d`; input sizes were 177, 552, and 924 tokens.
- The model returned no owner, ID, or version fields; the application assigned those values and copied `original_instruction` from the user's input. These disposable compiler probes did not save profiles, and their runtime contexts were closed.

## Verified Checks and Review Corrections

- The profiles/Settings/product/access component suite passed: **20 tests in 4.01 seconds**.
- The combined `tests/application` and `tests/storage` suite passed against actual PostgreSQL: **120 tests in 17.20 seconds**, using the external credential flag. Ruff passed for `src`, `tests`, `migrations`, and the validation script; `git diff --check` passed.
- `scripts/check-profile-dialogue.py` passed with controlled transport and actual PostgreSQL: two profiles were saved, one list was preserved, three unsupported-instruction questions were produced, and Telegram calls were zero. Atomic draft save/readback, repeated-confirmation idempotence, and owner-scoped explicit deletion were verified; the owner had zero profiles afterwards. The runtime exited after the check.
- Review corrections in the current implementation include waiting for an in-flight save's actual result so Cancel cannot falsely claim that nothing changed, discarding draft text after terminal failures, keeping “Several pages” text out of compiler input, and allowing preview-send work to stop cleanly during shutdown. Regression coverage includes these cases.
- The independent bounded compiler review reported no confirmed P1/P2 findings and passed 41 tests in 0.85 seconds. It made no edits and did not run the GPU.

## Remaining Integration and Acceptance

T03's local implementation gate is complete and T04 is active. Profile snapshots against document work remain for T05; the Settings/job-question overlap rules remain for T06. The joint real-Telegram end-to-end test, the single required sealed 70-case T01c/T07 benchmark, and native Linux x86-64/NVIDIA verification remain unperformed. T01b's freeze enables implementation but accepts no recognition quality; the integrated benchmark remains required acceptance after the complete product is available through Telegram and the developer can join the real-Telegram test. See [T03 specification](../../specs/T03-access-and-profiles.md), [roadmap](../planning/ROADMAP.md), and [current project status](../../STATUS.md) for scope and handoff.
