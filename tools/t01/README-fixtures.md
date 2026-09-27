# T01a synthetic development fixtures

This generator creates 12 logical documents for the runtime feasibility experiment in [T01](../../specs/T01-recognition-baseline.md). It is exploratory tooling, not application code. All values are invented sample text; no real people, personal identifiers, addresses, signatures, credentials, or customer uploads are used. Categories and scripts provide test diversity, not a product taxonomy or input whitelist.

**Human review remains pending.** Generated ground truth is known by construction, but neither font coverage checks nor an assistant inspecting images replaces the independent human review required by [ACCEPTANCE_PLAN](../../docs/testing/ACCEPTANCE_PLAN.md). These fixtures are eligible for runtime/resource diagnostics only until reviewed. They are not the sealed acceptance benchmark and must never be promoted to that benchmark. They may later enter the tuning set together with all their variants.

## Scope and limits

| Cases | Script | Layouts and primary input |
| --- | --- | --- |
| dev-01, dev-07 | Latin | Invoice with two table rows, two-sided sample card; image files |
| dev-02, dev-08 | Cyrillic | Certificate as simulated 1,280-px photo, two-page contract PDF |
| dev-03, dev-09 | Arabic | Receipt as simulated 2,560-px photo, request form as image file |
| dev-04, dev-10 | Chinese | Application as image file, two-page inventory PDF with table rows |
| dev-05, dev-11 | Japanese | Letter as simulated 1,280-px photo, receipt as simulated 2,560-px photo |
| dev-06, dev-12 | Devanagari | Certificate as image file, letter as simulated 1,280-px photo |

Every page has an original PNG and two **SIMULATED Telegram photo** JPEGs whose longer sides are 1,280 and 2,560 px. Simulation uses Pillow LANCZOS resizing and JPEG quality 85 with 4:2:0 chroma subsampling. No image has been sent through Telegram, no Bot API behavior has been verified, and no camera photograph has been captured. Real delivery through an authorized test chat is a separate outstanding task. These digital images cannot establish quality on arbitrary photographs, lighting, glare, perspective, blur, or partial crops.

The two PDFs are real two-page, image-backed PDF files. Embedding Pillow-rendered pages preserves RAQM shaping; there is no searchable text layer. Their page size is 595.2 x 841.92 pt, an A4 approximation matching the 2,480 x 3,508 source aspect ratio. PDFium also renders every PDF page at 150 and 200 DPI. The card source is 2,560 x 1,600 px. The intentionally clean, large text gives an initial multilingual legibility signal, not evidence about dense/small print or a representative document population. English labels surround values in the specified script.

## Generate locally

Use Python 3.11 or later with Pillow including RAQM, ReportLab, and pypdfium2. The generator installs nothing and never contacts a network or starts inference. It validates every source-value Unicode codepoint against cmap format 4/12 of the selected font's first face, then requires RAQM for shaping. Font coverage does not certify typographical or linguistic correctness; compare rendered glyph sequences during human review. The default fonts directory is `C:/Windows/Fonts`; required files are `arial.ttf`, `msyh.ttc`, `msgothic.ttc`, and `Nirmala.ttc`. Fonts remain local and are not copied or committed.

From the repository root, the following command was executed successfully on the development PC:

```powershell
& 'C:\Users\nikit\.codex\worktrees\local-product\TgBotDocs\.venv-t01a\Scripts\python.exe' `
  tools/t01/create_development_set.py `
  --output 'C:\Users\nikit\AppData\Local\TgBotDocs\t01a-fixtures-dev-v5'
```

`--output` must be absolute and outside every Git checkout. The generator refuses existing nonempty directories, so originals are not overwritten. Use a fresh output directory for each generation. A failed run can leave a partial synthetic directory without a manifest; do not use it. An operator manages retention of this explicitly synthetic material. Do not reuse this directory or generator inputs for real documents. `--fonts-dir` selects a different local font directory; `--cases` selects a separately reviewed synthetic source specification.

Generation produces 15 source pages, 30 simulated photo variants, 8 PDF renders, 2 PDFs, 12 review contact sheets, a local `review.html` gallery, and `manifest.json`: 68 hashed assets plus the manifest. Contact sheets show whole-page thumbnails with field boxes, followed by every exact reference value alongside a readable source-image crop. The HTML gallery shows exact reference strings and full-page sources, with expandable sections for every JPEG and PDF render. The reference and crop come from the same generator, and their agreement is not independent review. Paths inside the manifest and gallery are relative to their parent directory.

## Manifest version 1

| Location | Meaning |
| --- | --- |
| `schema_version`, `purpose` | Development manifest format version and declared scope |
| `synthetic_only`, `human_review_status`, `eligible_for_quality_measurement` | Provenance and pending review; measurement eligibility initially false |
| `actual_telegram_delivery`, `arbitrary_photograph_evidence` | Both false; simulations are never recorded as delivery evidence |
| `reproducibility` | Generator/source SHA-256, Python/package/RAQM versions, first font face and font SHA-256, PDF settings, exact resize/JPEG settings |
| `cases[]` | Logical document ID, origin/permission, script/language, scenario, primary delivery path, review state/method, instruction, expected profile/response, pages, PDF, input paths, review sheet |
| `cases[].inputs[]` | Primary diagnostic input: a PDF path or one image path per logical page/side |
| `cases[].expected_profile` | Fixture-only field selection, not a canonical production `ProfileRevision` |
| `cases[].expected_response[]` | Page association and exact scalar/cell values, expected `extracted` status, no normalization; development expectations, not the production response schema |
| `cases[].pages[].images[]` | Each PNG/JPEG/PDF render: path, SHA-256, image kind, dimensions, simulation flag, optional DPI or JPEG settings, per-image annotations |
| `images[].annotations[]` | Field or `rows[index].column`, exact value, expected status, normalization; tight value region as `bbox_px`; optional row/column association |
| `artifacts[]` | Every asset's relative path, SHA-256, byte count; manifest excludes itself to avoid a circular hash |

Bounding boxes use half-open `[x0, y0, x1, y1]` coordinates in pixels with origin at the top-left: use `image.crop(tuple(bbox_px))`. Source boxes enclose the shaped value's ink, not its label. Scaled-image boxes use outward rounding and a two-pixel margin to account for resizing. Always use the annotation from the actual image variant; do not apply source boxes to JPEGs or PDF renders. No bounding box is a measured model-localization result.

For a qualitative legibility exercise, select one known image record, request its fields without providing expected values, compare returned Unicode strings and page/row associations against its annotations, and examine missing/wrong values per script. For localization, compare predicted boxes with that image's recorded regions and inspect crops. A JSON/schema success alone does not prove correctness. Keep resource results distinct from quality evidence, and report review status. The manifest contains synthetic ground truth and must not be passed wholesale as an extraction prompt.

## Review and reproducibility

A person must inspect every input variant used for quality measurement, confirm each reference value is visibly present in its intended place, and record reviewer, method, and case status in a separate review record linked to the manifest hash. If the reviewer cannot read a script, compare its full glyph sequence with a reference rendering of the recorded value and name that method. Do not alter frozen source values after an error to make an extraction appear correct. This initial set contains present readable fields only; unreadable/negative cases and calibration are outside its scope.

For identical source, generator, font bytes, and package versions, filenames, image bytes, PDFs (`invariant=1`), annotations, and manifest are deterministic. Reproducibility across different rendering engines/fonts/package versions is not promised; those hashes and versions are recorded. To verify a run, decode each image, check dimensions/box bounds, reopen PDFs and check page counts, recompute every `artifacts[].sha256`, and compare two fresh generations. No project-wide test suite or application is introduced by this tooling.
