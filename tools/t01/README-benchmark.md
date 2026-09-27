# T01c sealed benchmark preparation

This prepares the **sealed 70-case T01c benchmark** of [ACCEPTANCE_PLAN](../../docs/testing/ACCEPTANCE_PLAN.md): 40 readable, 20 difficult and 10 negative cases. It is preparation material, not a measurement. The generator never starts the model, contacts Telegram, reviews a case or makes an acceptance claim.

**No model run may touch these cases before the benchmark is sealed.** No diagnostics, prompt experiments, threshold sweeps or "quick checks" run on any benchmark file, image or render, and `--show-mismatches` never applies to them. The benchmark runs once per frozen configuration, after sealing, through the runner's `benchmark` command. A case whose individual failure details are later examined to change prompts, thresholds, signals or rules becomes a tuning case and is replaced (see "Replacing a case").

**Human review is pending for every case.** Ground truth is known by construction, but only a person can confirm that each delivered input shows the intended values in the intended places. Nothing in this tooling performs or attests review.

## Composition

Source specification: [benchmark-cases.json](benchmark-cases.json). All sources are new synthetic families with fictional people and organizations. The generator refuses case IDs, profile field IDs or printed values of four or more characters that occur in the development or tuning specifications, and profiles are worded independently of the tuning fixture profiles.

| Quality | Cases | Coverage |
| --- | --- | --- |
| Readable | bench-r01..r40 | Every script at least 6 cases and every category at least 5. Delivery: 24 image files, 8 PDFs, 8 Telegram photos (4 standard, 4 HD). Two two-sided cards delivered as two image files (r01, r02). Four multi-page PDFs; three carry a record list across the page boundary (r25, r26, r27), and in r27 one record is visibly split across the boundary with a "continued" marker. Layouts: stacked, inline, letter, receipt, card, certificate, plus two layouts and two table styles the tuning generator never produced (two-column form, boxed form; boxed table, record blocks). Field positions, label placement, font sizes and column orders vary. |
| Difficult | bench-d01..d20 | Printed originals photographed by a person with a phone camera. Conditions: rotation 4, perspective 3, dim/uneven lighting 3, glare 4, blur/defocus 3, partial cropping 3. Ten are delivered through the Telegram photo path (5 standard, 5 HD) and ten as camera originals sent as image files. Every script and all eight categories. |
| Negative | bench-n01..n10 | Not a document (abstract image), mixed documents as an image set, mixed documents in one PDF (the second page belongs to another document), blank input, illegible input, two equally applicable profiles, conflicting card sides, an instruction printed inside a document, a password-protected PDF, and a meaningful document with no suitable profile. |

Every case receives a library of three profiles owned by one synthetic user (`benchmark-synthetic-user`): the correct profile plus distractors of the next categories in the fixed order of `category_order` (cyclic), in a per-case hashed order so position never reveals the answer. Equal profiles get the receipt profile, its equally applicable twin (different ID and wording, same fields) and one distractor; mixed documents get both documents' profiles and one distractor; the no-profile case gets three unrelated categories.

The protected PDF uses real encryption and the public, non-secret review password `benchmark-review-only`, so a reviewer can open it. The password is never supplied at runtime; the expected result is an input refusal.

## 1. Generate

Requirements: the project environment (`python -m uv sync --locked`), Pillow with RAQM, and these local Windows fonts in `C:/Windows/Fonts`: `arial.ttf`, `tahoma.ttf`, `times.ttf`, `verdana.ttf`, `georgia.ttf`, `msyh.ttc`, `simsun.ttc`, `msgothic.ttc`, `YuGothM.ttc`, `Nirmala.ttc`. The generator checks every printed codepoint against the first face of its font. Fonts are not copied or committed.

From the repository root:

```powershell
.venv\Scripts\python.exe tools/t01/create_benchmark_set.py --output 'C:\Users\<user>\AppData\Local\TgBotDocs\t01c-benchmark-v1'
```

`--output` must be absolute, empty or nonexistent, and outside every Git checkout; existing files are never overwritten. A failed run can leave a partial directory without `plan.json`; do not use it. The generator imports rendering helpers from `create_development_set.py` without modifying it.

Output (about 30 s on the development PC):

| Path | Content |
| --- | --- |
| `plan.json` | `BenchmarkPlan` (`tgbotdocs.recognition.benchmark`): every case's canonical fields known before capture (origin, script, language, category, quality, scenario, delivery path, generated artifacts with SHA-256, page IDs, profile library, expected outcome), the pending capture descriptor and instruction, and reproducibility hashes (generator, specification, development helpers, benchmark module, fonts, package versions, RAQM, Python). Canonical JSON. |
| `<case>/` | Generated inputs (`<case>-pNN.png` image files, `<case>.pdf`), originals (`-original.png`, `-pNN-original.png`) and the reference sheet `<case>-reference.png` (page thumbnails with value boxes and every exact expected value next to its source crop). |
| `printable-originals.pdf` | The 20 difficult originals, one per A4 page, with a small case label in the margin outside the document area. |
| `capture-instructions.html` | One row per human capture (28): condition to reproduce, delivery path, destination file name, Telegram quality. |
| `README.md` | Package summary. |
| `inbox/camera/`, `inbox/telegram/` | Empty destinations for the captures. |

For identical specification, generator, font bytes and package versions, output is byte-identical (verified by comparing two fresh generations on the development PC). Keep the directory unchanged: ingest re-verifies every generated file hash.

## 2. Capture (a person)

Follow `capture-instructions.html`. Each capture is exactly one JPEG at the stated path.

1. **Print** `printable-originals.pdf` on A4 at 100% scale (no "fit to page"). Keep the case label outside the photo.
2. **Difficult cases, camera rows** (`inbox/camera/<case>.jpg`): photograph the printed page with the phone camera reproducing the stated condition once (rotation, oblique perspective, dim or uneven light, glare spot, soft focus or motion, or the stated side cut off). Copy the original camera file from the phone (USB or an original-quality export), never a messenger copy. It must be larger than 2,560 px on its longer side.
3. **Difficult cases, Telegram rows** (`inbox/telegram/<case>.jpg`): photograph the printed page the same way, send the photo to a private test chat (for example Saved Messages) as a compressed **photo**, not as a file, with HD off for `standard` and on for `hd`, then save the received photo from Telegram (Telegram Desktop: Save image as).
4. **Readable photo cases** (`inbox/telegram/<case>.jpg`): send the generated `<case>/<case>-original.png` through the same chat as a compressed photo with the stated quality, and save the received photo. No printing.
5. Turn off camera location tagging or strip location metadata; ingest refuses files with GPS data. Do not rename, edit, crop or re-encode captures.

Ingest checks what it can: a standard Telegram photo is at most 1,280 px on its longer side; an HD photo is larger than 1,280 and at most 2,560 px; a camera original is larger than 2,560 px. It cannot prove that a file really passed through Telegram or came from a camera; the person placing the file is responsible for that, and the review confirms it.

## 3. Ingest

```powershell
.venv\Scripts\python.exe -m tgbotdocs.recognition.benchmark ingest --plan <dir>\plan.json --output <dir>\benchmark-manifest.json --registry <tuning canonical-manifest.json>
```

`--inbox` defaults to `<dir>\inbox`; `--registry` may repeat and names every historical development/tuning canonical manifest to check split separation against. Ingest refuses when the plan misses the accepted composition, a generated file changed, a capture is missing, an unexpected file is present (only `Thumbs.db`, `desktop.ini` and `.DS_Store` are ignored), a capture is not a decodable JPEG of the planned size class, carries GPS metadata, or duplicates another file. On success it writes a canonical `CorpusManifest` next to `plan.json`: split `benchmark`, purpose `review_preparation`, `sealed=false`, every review pending. Camera and Telegram captures of difficult cases carry `physical_capture=true`; files from `inbox/telegram/` are `kind="photo"` with `telegram_delivery_verified=true`. Output is content-free: counts, sealing state, pending reviews and the manifest SHA-256, or a fixed error code with case IDs and relative paths.

## 4. Human review

Review uses the corpus review tooling of T01b (`python -m tgbotdocs.recognition.corpus_cli`; see its documentation once integrated):

1. `review-form --manifest <dir>\benchmark-manifest.json --output <dir>\review-form.html` writes a static form next to the manifest.
2. The person opens it, inspects every input artifact against its reference sheet, confirms every expected value, page, row association, matching status and profile applicability, records visibility for difficult cases, chooses the method (`script_reading`, `glyph_sequence_comparison` or `published_transcription`), and exports `review-decisions.json` with the attestation. For scripts the reviewer cannot read, compare the complete glyph sequence with the reference and record that method.
3. `review-apply --manifest <dir>\benchmark-manifest.json --decisions review-decisions.json --output <dir>\reviewed-manifest.json` applies only the person's decisions.

A difficult value that is not legible in the actual capture becomes `unreadable` through the review decisions, not by assumption. A rejected benchmark case is not dropped: see "Replacing a case".

## 5. Seal (after the configuration is frozen)

Sealing happens only after T01b has frozen the configuration (`python -m tgbotdocs.recognition.runner freeze ...`) and never before every case is human-verified:

```powershell
.venv\Scripts\python.exe -m tgbotdocs.recognition.benchmark seal --manifest <dir>\reviewed-manifest.json --config <frozen-configuration.json> --output <dir>\sealed-manifest.json --registry <tuning canonical-manifest.json>
```

Seal re-verifies every artifact hash, requires every benchmark eligibility condition except sealing itself (human-verified ground truth, purpose `quality_measurement`, 40/20/10 composition, verified Telegram delivery, physical photographs, at least ten difficult photo-path cases), refuses an already sealed manifest, and writes a new manifest with `sealed=true` and `frozen_configuration_sha256` = SHA-256 of the frozen configuration's canonical JSON bytes (sorted keys, compact separators, UTF-8). The runner's `benchmark` command then checks that hash, the registry separation and its run ledger, and runs the frozen configuration once.

## Replacing a case

If a case is rejected in review, or its individual failure details are examined after a benchmark run, replace it with a new case of the same category, script and quality class before the next acceptance run: edit the entry in `benchmark-cases.json` (new ID, new family, new values), generate into a fresh directory, copy the unchanged captures (unchanged cases generate byte-identical files; ingest verifies their hashes), capture the replacement, and repeat ingest, review and sealing. Never shrink the 40/20/10 composition and never lower a threshold retroactively. A replaced case moves to tuning with all its variants.

## Limits

Synthetic documents printed and photographed by one person on one phone reproduce real photography only partly; results do not prove quality on arbitrary documents. Retention of the package is managed by the operator; it contains no real personal data. The Telegram size checks are consistency checks, not proof of delivery.
