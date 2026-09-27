# T01b synthetic tuning preparation

This prepares a **25-case tuning review set**, not the sealed benchmark: all 12 frozen T01a documents and their original variants, plus 13 new independent synthetic sources. The source-family rule is strict: every original, electronic distortion, photo simulation, PDF and render belongs to tuning permanently. No benchmark cases are created. The generator does not start the model, contact Telegram, run calibration, or make an acceptance claim.

**Human review is pending for every case.** This is a concrete review package, not a reviewed ground-truth corpus. `eligible_for_quality_measurement` and `benchmark_eligible` are false. A person must verify every actual input variant, its glyphs, intended field locations, page/row association, visibility, matching/extraction expectations and candidate-profile applicability before a quality measurement. For unfamiliar scripts, compare the complete glyph sequence with a reference and record that method. Do not relabel an assistant's visual inspection as human review.

## Cases and provenance

| Cases | Quality class | Purpose |
| --- | --- | --- |
| dev-01 through dev-12 | Readable source design; human review pending | Frozen T01a originals, both simulated photo sizes, source PDF files, PDF renders and contact sheets |
| tune-13 | Readable source design; human review pending | New synthetic identity sample with a fictional subject label, no real name or identity |
| tune-14 through tune-17 | Difficult electronic simulations; visibility pending | Independently authored Arabic receipt, Chinese invoice/rows, Japanese letter and Devanagari application; rotation, blur, dim lighting and partial crop |
| tune-18 | Negative | Fully blank input; draft matching `unreadable`, no extraction |
| tune-19 | Negative | Abstract geometric image; draft matching `not_document`, no extraction |
| tune-20 | Negative | Two independently identified contracts in one submitted set; draft matching `mixed`; two different candidate descriptions; no accepted extraction |
| tune-21 | Negative | Two profiles with identical applicability and fields, distinct IDs; draft matching `uncertain`, no automatic selection |
| tune-22 | Negative | Two card sides with conflicting `card_id`; draft scalar status `ambiguous`, no accepted value for that field |
| tune-23 | Negative | Printed adversarial instruction; extract only requested reference/code and never execute the printed command or contact an endpoint |
| tune-24 | Negative | Real password-protected PDF; draft input refusal before matching/extraction |
| tune-25 | Negative | Meaningful form with zero configured candidate profiles; draft matching `no_profile`, no extraction |

There are 13 readable designs, four difficult electronic cases and eight negative cases; these numbers count logical source documents, not variants. Across the set, diversity labels cover Latin, Cyrillic, Arabic, Chinese, Japanese and Devanagari and identity, invoice, receipt, certificate, contract, application, letter and repeating rows. These are fixture diversity labels, not a coded product taxonomy or input whitelist. Blank/abstract inputs carry a matrix bucket for bookkeeping, not a claim that the image is a document of that category. The set does not cover every possible script/category/quality combination or every negative/resilience scenario.

Every value is synthetic. There are no real people, personal identifiers, addresses, signatures, customer documents, credentials or external endpoints. IDs and owner `1` in candidate profiles identify synthetic fixtures. The protected PDF uses the public, non-secret review password `synthetic-review-only`, solely to let a reviewer open this generated sample. A runtime test must submit it without that password and verify refusal; the PNG reference must never be substituted for the protected input.

Electronic distortions are declared with exact fixed parameters in `tuning-cases.json` and manifest. They are **not physical photographs** and cannot establish quality on arbitrary photographs, lighting, glare, perspective or camera blur. Likewise all photo JPEGs are explicitly **SIMULATED Telegram delivery**; no test-chat upload occurred. Physical capture and actual authorized Telegram delivery remain separate preparation work. The printable PDF supplies original source sheets for that work; printing/capture quality and page/variant provenance must be recorded afterward.

## Generate

Use the same Python environment as the development generator: Python 3.11+, Pillow with RAQM, ReportLab and pypdfium2, and the local Windows fonts listed in [README-fixtures](README-fixtures.md). No packages or fonts are installed or copied. The new generator imports rendering helpers without modifying the frozen development generator or its schema. Its CLI, source specification and documentation are separate files.

This command was run successfully on the development PC:

```powershell
& 'C:\Users\nikit\.codex\worktrees\local-product\TgBotDocs\.venv-t01a\Scripts\python.exe' `
  tools/t01/create_tuning_set.py `
  --development-manifest 'C:\Users\nikit\AppData\Local\TgBotDocs\t01a-fixtures-dev-v5\manifest.json' `
  --output 'C:\Users\nikit\AppData\Local\TgBotDocs\t01b-tuning-review-v3'
```

Output must be an absolute empty/nonexistent directory outside every Git checkout; it must not overlap the frozen input directory. Existing assets are never overwritten. The generator verifies every frozen input asset hash before copying. `development/manifest.json` and all 68 original development assets are copied byte-for-byte; their original paths continue working within that directory. In the outer tuning manifest, those paths receive a `development/` prefix without altering copied files or their recorded hashes. New source IDs and values are independent of those 12 development sources. `--cases` can supply another synthetic specification with at least 12 independent new cases; source count and diversity validation still apply. Failed runs may leave a partial directory without a manifest; do not use it.

Output has `manifest.json`, `review.html`, `printable-originals.pdf`, the copied frozen development package, and each new case's original PNG, image-file variant, two simulated photo JPEGs and source-reference contact sheet. The protected PDF is an additional real input. Default output contains **145 hashed assets plus the manifest** and **30 original printable pages**. A4-like source pages print without distortion; card sources retain their aspect ratio and are centered on A4. Blank and abstract source pages remain blank/abstract rather than acquiring artificial document content. Use the manifest's `printable_originals.page_mapping` to identify such printed pages.

## Fixture manifest and canonical adaptation

Update 2026-09-28: the canonical adapter exists as `tools/t01/canonicalize_tuning.py` (profile library and user-style profile descriptions per ED-015); its output `canonical-manifest.json` and the human review form are described in [T01_PROCEDURE](../../docs/testing/T01_PROCEDURE.md). The paragraph below records the original package design.

The root recognition-core task owns canonical models and the adapter. This generator uses the existing development image-record format with small tuning metadata additions; it does not introduce a second production manifest API. `schema_version` is 1 for this fixture package and `canonical_manifest_adapter_status` is pending. The final model adapter must validate/convert the candidate profiles and draft ground truth before use. The case manifest with expected values must never be sent wholesale as an extraction prompt.

| Location | Meaning |
| --- | --- |
| `cases[].inputs` | Actual primary input paths; for tune-24 this is the protected PDF, not its review image |
| `cases[].pages[].images[]` | Image record with path, SHA-256, dimensions and pixel boxes; new cases place `source_original` first, followed by delivered variants |
| `images[].annotations[]` | Recorded source value and geometric location. New expected statuses are null with `visibility_status_review=pending_human_review`; frozen development annotation bytes/values are preserved |
| `cases[].source_family` | Every derivative stays within the same tuning family; never split into benchmark |
| `cases[].candidate_profiles` | Hand-authored fixture profile objects with ID, owner, version, name, applicability description, original instruction, fields and guidance; no document example values are copied into profile definitions |
| `cases[].profile_schema` | Explicitly marks candidate objects as pending canonical adapter validation |
| `cases[].expected_result` | Reviewed status is pending; matching and scalar/list expectations are draft contract expectations, not accepted model outputs |
| `expected_result.scalar_fields[].source_values` | Exact recorded value(s) with page IDs, including both conflicting card values |
| `status_draft`, `accepted_value_draft` | A draft expected result only. `ambiguous` has no accepted value; difficult/unexecuted extraction statuses stay null |
| `allowed_visibility_statuses_pending_review` | Difficult fields may be readable or unreadable after human inspection; this list is not a measured status or automatic label |
| `frozen_development` | Original manifest hash, copied manifest, IDs, and confirmation that all original variants remain in tuning |
| `reproducibility` | Generator/spec/helper/font hashes, actual package/RAQM versions, fixed transformation provenance |
| `artifacts` | Relative paths, SHA-256 and byte sizes of every output asset except the outer manifest |

All candidate scalar and list-cell types are `text` to preserve original Unicode and number/date strings without adding unsupported normalization rules. Tables become a one-level `rows` list with scalar columns. No generic document-number validator or universal category enum is introduced. Two equally applicable profiles have identical definitions except their IDs. The conflicting scalar shares one field ID across the card sides; the field must not be returned as two independent accepted values. A source reference value is still recorded when extraction should not run, so the reviewer can verify what the negative input contains without accepting it as a result.

Image boxes are half-open `[x0,y0,x1,y1]` pixels from the top-left. Electronic rotation transforms all four corners and stores an enclosing region; cropping translates/clips regions, and `source_partially_cropped` is a geometric fact, not a visibility/status judgment. A completely removed region has a null box. JPEG boxes derive from the delivered image dimensions, with outward rounding and a two-pixel margin. `maximum_longer_side_px` is a cap: no JPEG is upscaled beyond its available source resolution. Originals/reference sheets and actual delivered variants are distinct, so pristine references cannot accidentally be scored instead of difficult images.

## Required review and remaining work

Open `review.html`, compare source references with each input variant, and record reviewer, method and decisions in a separate review record tied to the manifest hash. Confirm printed adversarial text is present as document data, profile ambiguity and mixed-document grouping are meaningful, conflicting IDs appear on the stated sides, and the protected PDF refuses opening without a password. Determine actual visibility on difficult cases; do not infer `unreadable` from blur radius or `missing` from partial cropping. Every case must remain excluded from quality measurements while review is pending.

The fixture preparation alone does not complete T01b. Canonical conversion, reviewed ground truth, physical photograph and real Telegram delivery coverage, verification-signal calibration, risk-coverage curves and frozen parameters are outstanding. No sealed benchmark is generated or used. Reproducibility checks can compare two fresh outputs with identical input/source/font/package bytes; font coverage and successful decoding do not establish linguistic correctness or model quality.
