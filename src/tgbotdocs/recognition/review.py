"""Human review tooling: a static review form and the transcription of human decisions.

Code never reviews, approves, or attests a case. The form only displays a corpus;
``apply_decisions`` only transcribes a decisions file that a human produced with it,
refusing anything incomplete, unattested, or bound to different manifest bytes.
Errors carry fixed codes and case IDs, never document values.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from pydantic import Field, StrictBool, StrictStr, ValidationError, model_validator

from .contracts import ContractModel
from .corpus import (CorpusCase, CorpusManifest, ExpectedList, ExpectedOutcome, ExpectedRow, ExpectedValue,
                     HumanReview, LoadedCorpus, case_review_digest, declared_denominators)

Method = Literal["script_reading", "glyph_sequence_comparison", "published_transcription"]
METHODS = ("script_reading", "glyph_sequence_comparison", "published_transcription")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def applicable_methods(case) -> tuple[str, ...]:
    """Review methods that can describe how this case's ground truth was checked.

    A published transcription exists only for permitted public materials (ACCEPTANCE_PLAN);
    synthetic and separately authorized cases are checked by reading or glyph comparison.
    """
    if case.origin.kind == "permitted_public":
        return METHODS
    return tuple(method for method in METHODS if method != "published_transcription")


class ReviewError(ValueError):
    """Fixed, content-free code; ``detail`` may name case IDs and counts only."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Canonical manifest bytes


def manifest_bytes(manifest: CorpusManifest) -> bytes:
    """Canonical JSON: sorted keys, compact separators, UTF-8."""
    payload = manifest.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_new_file(path: Path, data: bytes, verify: Callable[[Path], object] | None = None) -> None:
    """Create ``path``; an existing file is never overwritten.

    ``verify`` runs on the written file. If writing or verification fails, the new file is
    deleted before the error propagates, so no unverified output is left behind.
    """
    try:
        stream = path.open("xb")
    except FileExistsError:
        raise ReviewError("output_exists") from None
    except OSError:
        raise ReviewError("output_unwritable") from None
    try:
        with stream:
            stream.write(data)
        if verify is not None:
            verify(path)
    except BaseException as error:
        path.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise ReviewError("output_unwritable") from None
        raise


def expected_outcome_status(fields: tuple[ExpectedValue, ...], lists: tuple[ExpectedList, ...]) -> str:
    """The only outcome ``ExpectedOutcome`` accepts for a matched case with these values."""
    accepted = any(value.status == "extracted" for value in fields)
    accepted |= any(cell.status == "extracted" for value in lists for row in value.rows for cell in row.cells)
    accepted |= any(value.status == "complete" and not value.rows for value in lists)
    complete = all(value.status in ("extracted", "missing") for value in fields)
    complete &= all(value.status == "complete" for value in lists)
    return "failed" if not accepted else ("complete" if complete else "partial")


# ---------------------------------------------------------------------------
# Reviewable values: every expected value that carries a recorded reading


ValueKey = tuple[str, str | None, str | None]


def reviewable_values(case: CorpusCase) -> tuple[tuple[ValueKey, ExpectedValue], ...]:
    """(field_id, row source_key or None, column_id or None) for each extracted expectation."""
    if case.expected is None or case.expected.matching != "matched":
        return ()
    values: list[tuple[ValueKey, ExpectedValue]] = []
    values += [((value.field_id, None, None), value) for value in case.expected.fields if value.status == "extracted"]
    for listed in case.expected.lists:
        for row in listed.rows:
            values += [((listed.field_id, row.source_key, cell.field_id), cell)
                       for cell in row.cells if cell.status == "extracted"]
    return tuple(values)


# ---------------------------------------------------------------------------
# Decisions produced by a human with the review form


class ValueVisibility(ContractModel):
    field_id: StrictStr = Field(min_length=1)
    row_key: StrictStr | None = None
    column_id: StrictStr | None = None
    visibility: Literal["legible", "not_legible"]

    @model_validator(mode="after")
    def cell_identity(self):
        if (self.row_key is None) != (self.column_id is None):
            raise ValueError("cell_requires_row_and_column")
        return self

    @property
    def key(self) -> ValueKey:
        return (self.field_id, self.row_key, self.column_id)


class CaseDecision(ContractModel):
    case_id: StrictStr = Field(min_length=1)
    decision: Literal["verified", "rejected"]
    method: Method | None = None
    values: tuple[ValueVisibility, ...] = ()
    notes: StrictStr = ""


class ReviewDecisions(ContractModel):
    schema_version: Literal[1]
    manifest_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: StrictStr
    reviewer_attests_human_inspection: StrictBool
    reviewed_at: datetime
    cases: tuple[CaseDecision, ...]


def parse_decisions(data: bytes) -> ReviewDecisions:
    try:
        return ReviewDecisions.model_validate_json(data)
    except (ValidationError, ValueError):
        raise ReviewError("review_decisions_invalid") from None


def _reviewed_case(case: CorpusCase, decision: CaseDecision, decisions: ReviewDecisions) -> CorpusCase:
    if decision.method is None:
        raise ReviewError("review_method_required", case.case_id)
    if decision.method not in applicable_methods(case):
        raise ReviewError("review_method_not_applicable_to_origin", case.case_id)
    if case.expected is None:
        raise ReviewError("ground_truth_missing_reject_case", case.case_id)
    expected = {key: value for key, value in reviewable_values(case)}
    given = [value.key for value in decision.values]
    if len(given) != len(set(given)):
        raise ReviewError("review_decision_duplicate_value", case.case_id)
    if set(given) - set(expected):
        raise ReviewError("review_decision_unknown_value", case.case_id)
    if set(given) != set(expected):
        raise ReviewError("review_decisions_incomplete", case.case_id)
    hidden = {value.key for value in decision.values if value.visibility == "not_legible"}
    if hidden and case.quality == "readable":
        # A readable case promises every present value is legible; it cannot be scored otherwise.
        raise ReviewError("readable_case_value_not_legible_reject_case", case.case_id)

    def visible(value: ExpectedValue, key: ValueKey) -> ExpectedValue:
        if key not in hidden:
            return value
        return ExpectedValue(field_id=value.field_id, status="unreadable", present=True,
                             source_pages=value.source_pages, normalization=value.normalization)

    fields = tuple(visible(value, (value.field_id, None, None)) for value in case.expected.fields)
    lists = []
    for listed in case.expected.lists:
        rows = tuple(ExpectedRow(source_key=row.source_key, source_pages=row.source_pages,
                                 cells=tuple(visible(cell, (listed.field_id, row.source_key, cell.field_id))
                                             for cell in row.cells)) for row in listed.rows)
        cells = [cell for row in rows for cell in row.cells]
        if any(cell.status == "unreadable" for cell in cells):
            if any(cell.status == "extracted" for cell in cells):
                listed = ExpectedList(field_id=listed.field_id, status="partial", enumeration_complete=False, rows=rows)
            else:
                listed = ExpectedList(field_id=listed.field_id, status="unresolved", enumeration_complete=False,
                                      reason="unreadable", rows=rows)
        else:
            listed = listed.model_copy(update={"rows": rows})
        lists.append(listed)
    lists = tuple(lists)
    expected = case.expected
    if expected.matching == "matched":
        expected = ExpectedOutcome(matching="matched", profile_id=expected.profile_id,
                                   outcome=expected_outcome_status(fields, lists), fields=fields, lists=lists)
    try:
        updated = CorpusCase.model_validate({**case.model_dump(exclude={"review", "expected"}),
                                             "expected": expected, "review": HumanReview()})
        review = HumanReview(status="verified", reviewer=decisions.reviewer.strip(), method=decision.method,
                             reviewed_at=decisions.reviewed_at, reviewer_kind="human",
                             subject_sha256=case_review_digest(updated))
        return CorpusCase.model_validate({**updated.model_dump(exclude={"review"}), "review": review})
    except ValidationError:
        raise ReviewError("reviewed_case_invalid", case.case_id) from None


def apply_decisions(manifest: CorpusManifest, manifest_sha256: str,
                    decisions: ReviewDecisions) -> tuple[CorpusManifest, tuple[str, ...]]:
    """Transcribe human decisions; returns the reviewed manifest and the removed case IDs."""
    if decisions.manifest_sha256 != manifest_sha256:
        raise ReviewError("review_manifest_hash_mismatch")
    if decisions.reviewer_attests_human_inspection is not True:
        raise ReviewError("human_attestation_missing")
    if not decisions.reviewer.strip():
        raise ReviewError("reviewer_name_missing")
    if decisions.reviewed_at.tzinfo is None:
        raise ReviewError("review_timestamp_timezone_required")
    if manifest.sealed:
        raise ReviewError("sealed_manifest_is_immutable")
    recorded = [case.case_id for case in manifest.cases if case.review.status != "pending"]
    if recorded:
        raise ReviewError("review_already_recorded", ",".join(recorded))
    by_id = {}
    for decision in decisions.cases:
        if decision.case_id in by_id:
            raise ReviewError("review_decision_duplicate_case", decision.case_id)
        by_id[decision.case_id] = decision
    unknown = sorted(set(by_id) - {case.case_id for case in manifest.cases})
    if unknown:
        raise ReviewError("review_decision_unknown_case", ",".join(unknown))
    missing = [case.case_id for case in manifest.cases if case.case_id not in by_id]
    if missing:
        raise ReviewError("review_decisions_incomplete", ",".join(missing))
    rejected = tuple(case.case_id for case in manifest.cases if by_id[case.case_id].decision == "rejected")
    if rejected and manifest.split == "benchmark":
        # The accepted 40/20/10 composition is never shrunk; a replacement case must be prepared first.
        raise ReviewError("benchmark_rejection_requires_replacement_case", ",".join(rejected))
    cases = tuple(_reviewed_case(case, by_id[case.case_id], decisions)
                  for case in manifest.cases if by_id[case.case_id].decision == "verified")
    if not cases:
        raise ReviewError("review_result_empty")
    purpose = "quality_measurement" if all(case.review.status == "verified" for case in cases) else manifest.purpose
    try:
        reviewed = CorpusManifest(schema_version=manifest.schema_version, split=manifest.split, purpose=purpose,
                                  cases=cases, denominators=declared_denominators(cases), sealed=False,
                                  frozen_configuration_sha256=manifest.frozen_configuration_sha256)
    except ValidationError:
        raise ReviewError("reviewed_manifest_invalid") from None
    if manifest.split == "tuning":
        reasons = reviewed.eligibility_reasons("calibration")
        if reasons:
            raise ReviewError("review_result_ineligible_for_calibration", ",".join(reasons))
    return reviewed, rejected


# ---------------------------------------------------------------------------
# Status


def corpus_status(manifest: CorpusManifest) -> dict:
    """Content-free counts and eligibility reasons."""
    def count(attribute: str) -> dict[str, int]:
        return dict(sorted(Counter(getattr(case, attribute) for case in manifest.cases).items()))

    return {
        "split": manifest.split,
        "purpose": manifest.purpose,
        "sealed": manifest.sealed,
        "cases": len(manifest.cases),
        "by_quality": count("quality"),
        "by_script": count("script"),
        "by_category": count("category"),
        "by_delivery_path": count("delivery_path"),
        "reviews": dict(sorted(Counter(case.review.status for case in manifest.cases).items())),
        "pending_review_case_ids": [case.case_id for case in manifest.cases if case.review.status == "pending"],
        "denominators": manifest.denominators.model_dump(),
        "eligibility": {mode: list(manifest.eligibility_reasons(mode)) for mode in ("calibration", "benchmark")},
    }


# ---------------------------------------------------------------------------
# Review form


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _value_text(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _artifact_html(artifact) -> str:
    path = _e(artifact.path)
    flags = []
    if artifact.delivery_simulated:
        flags.append("simulated delivery")
    if artifact.physical_capture:
        flags.append("physical capture")
    if artifact.telegram_delivery_verified:
        flags.append("Telegram delivery verified")
    caption = f"<code>{path}</code> · {_e(artifact.kind)}" + "".join(f" · {_e(flag)}" for flag in flags)
    if PurePosixPath(artifact.path).suffix.lower() in IMAGE_SUFFIXES:
        body = f'<a href="{path}" target="_blank" rel="noopener"><img src="{path}" alt="{_e(artifact.id)}" loading="lazy"></a>'
    else:
        body = f'<a class="file" href="{path}" target="_blank" rel="noopener">Open {_e(artifact.kind)} file</a>'
    return f"<figure>{body}<figcaption>{caption}</figcaption></figure>"


def _field_rows(field, prefix: str = "") -> str:
    rows = (f"<tr><td><code>{_e(prefix + field.id)}</code></td><td>{_e(field.label)}</td><td>{_e(field.type)}</td>"
            f"<td>{_e(field.description)}</td></tr>")
    for column in getattr(field, "columns", ()):
        rows += _field_rows(column, prefix + field.id + " › ")
    return rows


def _profile_html(profile) -> str:
    fields = "".join(_field_rows(field) for field in profile.fields)
    guidance = f"<p><b>Guidance:</b> {_e(profile.guidance)}</p>" if profile.guidance else ""
    return (f'<div class="profile"><h4>{_e(profile.name)} <small><code>{_e(profile.id)}</code></small></h4>'
            f"<p>{_e(profile.description)}</p>{guidance}"
            "<table><thead><tr><th>Field</th><th>Label</th><th>Type</th><th>Description</th></tr></thead>"
            f"<tbody>{fields}</tbody></table></div>")


def _values_html(case: CorpusCase, index: int, difficult: bool) -> str:
    expected = case.expected
    if expected is None:
        return "<p class=warn>No ground truth recorded; this case must be rejected.</p>"
    if expected.matching != "matched":
        return "<p>No extraction is expected for this matching status.</p>"
    rows = []
    reviewable = {id(value) for _, value in reviewable_values(case)}
    counter = 0

    def row(value: ExpectedValue, field: str, row_key: str | None, column: str | None) -> str:
        nonlocal counter
        pages = ", ".join(str(page) for page in value.source_pages) or "—"
        attributes = f'data-field="{_e(field)}"'
        if row_key is not None:
            attributes += f' data-row="{_e(row_key)}" data-column="{_e(column)}"'
        if id(value) in reviewable:
            name = f"c{index}-v{counter}"
            counter += 1
            checked = "" if difficult else " checked"
            control = (f'<label><input type="radio" name="{name}" value="legible"{checked}> legible</label> '
                       f'<label><input type="radio" name="{name}" value="not_legible"> not legible</label>')
            row_class = "value"
        else:
            control = "—"
            row_class = "fixed"
        allowed = "".join(f"<div>also: <bdi>{_e(_value_text(item))}</bdi></div>" for item in value.allowed_values)
        return (f'<tr class="{row_class}" {attributes}><td><code>{_e(field)}</code></td>'
                f"<td>{_e(row_key or '')}</td><td>{_e(column or '')}</td><td>{_e(value.status)}</td>"
                f'<td dir="auto"><bdi>{_e(_value_text(value.value))}</bdi>{allowed}</td><td>{pages}</td>'
                f"<td>{control}</td></tr>")

    for value in expected.fields:
        rows.append(row(value, value.field_id, None, None))
    for listed in expected.lists:
        rows.append(f'<tr class="list"><td colspan="7"><code>{_e(listed.field_id)}</code>: list {_e(listed.status)}, '
                    f"enumeration complete: {_e(listed.enumeration_complete)}, {len(listed.rows)} rows</td></tr>")
        for item in listed.rows:
            for cell in item.cells:
                rows.append(row(cell, listed.field_id, item.source_key, cell.field_id))
    return ("<table><thead><tr><th>Field</th><th>Row</th><th>Column</th><th>Status</th><th>Expected value</th>"
            "<th>Pages</th><th>Visibility</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _case_html(case: CorpusCase, index: int) -> str:
    difficult = case.quality == "difficult"
    artifacts = {artifact.id: artifact for artifact in case.artifacts}
    inputs = "".join(_artifact_html(artifacts[identity]) for identity in case.input_artifact_ids)
    references = "".join(_artifact_html(a) for a in case.artifacts if a.kind == "reference")
    others = "".join(_artifact_html(a) for a in case.artifacts
                     if a.kind != "reference" and a.id not in case.input_artifact_ids)
    profiles = "".join(_profile_html(profile) for profile in case.profiles) or "<p>No candidate profiles.</p>"
    expected = case.expected
    if expected is None:
        matching = "<p class=warn>Expected result: not recorded.</p>"
    else:
        name = next((p.name for p in case.profiles if p.id == expected.profile_id), None)
        profile = f" · profile <code>{_e(expected.profile_id)}</code> ({_e(name)})" if expected.profile_id else ""
        matching = (f"<p>Expected matching: <b>{_e(expected.matching)}</b>{profile} · expected outcome: "
                    f"<b>{_e(expected.outcome)}</b></p>")
    hint = ("Difficult case: choose the visibility of every value as it appears in the model input."
            if difficult else "Visibility defaults to legible. A readable case with a value that is not legible "
            "must be rejected instead.")
    methods = "".join(f'<option value="{m}">{m.replace("_", " ")}</option>' for m in applicable_methods(case))
    return f"""
<section class="case" id="case-{index}" data-case="{_e(case.case_id)}" data-index="{index}">
<h2>{_e(case.case_id)} <small>{_e(case.quality)} · {_e(case.category)} · {_e(case.script)} ({_e(case.language)}) ·
delivery {_e(case.delivery_path)} · scenario {_e(case.scenario)} · pages {len(case.page_ids)} ·
current review {_e(case.review.status)}</small></h2>
<h3>Model input (page order = file order, then pages within each file)</h3><div class="gallery">{inputs}</div>
<h3>Reference review aids (never model input)</h3><div class="gallery">{references or "<p>None.</p>"}</div>
<details><summary>Other variants and originals (not model input)</summary><div class="gallery">{others or "<p>None.</p>"}
</div></details>
<h3>Candidate profiles</h3>{profiles}
<h3>Expected result</h3>{matching}<p class="hint">{hint}</p>{_values_html(case, index, difficult)}
<fieldset class="decision"><legend>Decision for {_e(case.case_id)}</legend>
<label><input type="radio" name="c{index}-decision" value="verified"> verified</label>
<label><input type="radio" name="c{index}-decision" value="rejected"> rejected</label>
<label>Method <select name="c{index}-method"><option value="">— choose —</option>{methods}</select></label>
<label class="notes">Notes <textarea name="c{index}-notes" rows="2"></textarea></label>
</fieldset></section>"""


_STYLE = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#ddd;--warn:#a40000;--accent:#0b57d0}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--muted:#aaa;--line:#444;--warn:#ff8080;--accent:#8ab4f8}}
body{margin:0 auto;max-width:1200px;padding:16px;font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header,section.case,footer{border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:16px 0}
h2 small,h4 small{color:var(--muted);font-weight:normal;font-size:.8em}
.gallery{display:flex;flex-wrap:wrap;gap:12px}
figure{margin:0;max-width:100%}
figure img{max-width:min(560px,100%);max-height:720px;border:1px solid var(--line);background:#fff}
figcaption{font-size:.8em;color:var(--muted);word-break:break-all}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
td[dir=auto]{font-size:1.1em}
tr.list td{background:rgba(127,127,127,.12)}
.warn,.hint{color:var(--warn)}
.hint{color:var(--muted)}
fieldset{border:1px solid var(--line);display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.notes{flex-basis:100%;display:flex;gap:8px}.notes textarea{flex:1}
footer{position:sticky;bottom:0;background:var(--bg)}
button{font-size:1em;padding:6px 16px}
#status{color:var(--muted)}
"""

_SCRIPT = """
(function () {
  "use strict";
  var MANIFEST_SHA256 = %(sha)s;
  var button = document.getElementById("export");
  var status = document.getElementById("status");
  function pad(n) { n = Math.floor(Math.abs(n)); return (n < 10 ? "0" : "") + n; }
  function timestamp(d) {
    var offset = -d.getTimezoneOffset();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" +
      pad(d.getMinutes()) + ":" + pad(d.getSeconds()) + (offset >= 0 ? "+" : "-") + pad(offset / 60) + ":" +
      pad(offset %% 60);
  }
  function checked(scope, name) {
    var input = scope.querySelector('input[name="' + name + '"]:checked');
    return input ? input.value : null;
  }
  function collect() {
    var missing = [];
    var reviewer = document.getElementById("reviewer").value.trim();
    if (!reviewer) { missing.push("reviewer name"); }
    var attested = document.getElementById("attest").checked;
    if (!attested) { missing.push("human inspection attestation"); }
    var cases = [];
    document.querySelectorAll("section.case").forEach(function (section) {
      var index = section.getAttribute("data-index");
      var caseId = section.getAttribute("data-case");
      var decision = checked(section, "c" + index + "-decision");
      var method = section.querySelector('select[name="c' + index + '-method"]').value || null;
      var notes = section.querySelector('textarea[name="c' + index + '-notes"]').value;
      var values = [];
      if (!decision) { missing.push(caseId + ": decision"); }
      if (decision === "verified") {
        if (!method) { missing.push(caseId + ": method"); }
        section.querySelectorAll("tr.value").forEach(function (row) {
          var input = row.querySelector("input:checked");
          if (!input) { missing.push(caseId + ": visibility of " + row.getAttribute("data-field")); return; }
          values.push({
            field_id: row.getAttribute("data-field"),
            row_key: row.hasAttribute("data-row") ? row.getAttribute("data-row") : null,
            column_id: row.hasAttribute("data-column") ? row.getAttribute("data-column") : null,
            visibility: input.value
          });
        });
      }
      cases.push({case_id: caseId, decision: decision, method: decision === "verified" ? method : null,
                  values: values, notes: notes});
    });
    return {missing: missing, data: {schema_version: 1, manifest_sha256: MANIFEST_SHA256, reviewer: reviewer,
            reviewer_attests_human_inspection: attested, reviewed_at: null, cases: cases}};
  }
  function update() {
    var result = collect();
    button.disabled = result.missing.length > 0;
    status.textContent = result.missing.length ? result.missing.length + " item(s) incomplete, first: " +
      result.missing.slice(0, 3).join("; ") : "Complete. Export writes review-decisions.json.";
  }
  document.addEventListener("input", update);
  document.addEventListener("change", update);
  button.addEventListener("click", function () {
    var result = collect();
    if (result.missing.length) { update(); return; }
    result.data.reviewed_at = timestamp(new Date());
    var blob = new Blob([JSON.stringify(result.data, null, 2) + "\\n"], {type: "application/json"});
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "review-decisions.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  });
  update();
})();
"""


def render_review_form(manifest: CorpusManifest, manifest_sha256: str, manifest_name: str) -> str:
    """Static, self-contained HTML; artifact paths stay relative to the manifest directory."""
    cases = "".join(_case_html(case, index) for index, case in enumerate(manifest.cases))
    csp = ("default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
           "connect-src 'none'; form-action 'none'; base-uri 'none'")
    script = _SCRIPT % {"sha": json.dumps(manifest_sha256)}
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Corpus human review</title><style>{_STYLE}</style></head><body>
<header><h1>Corpus human review</h1>
<p>Manifest <code>{_e(manifest_name)}</code> · sha256 <code>{_e(manifest_sha256)}</code> · split {_e(manifest.split)} ·
purpose {_e(manifest.purpose)} · {len(manifest.cases)} cases</p>
<p>Only a person may complete this form. Open every model input at full size and compare it with the expected
result: the intended values are visible in the intended places, pages and rows are associated correctly, the
matching expectation and candidate profiles make sense, and statuses match what is visible. For a script you cannot
read, compare the complete glyph sequence with a reference rendering and choose that method. Reject a case whose
ground truth cannot be confirmed. The form works offline and sends nothing; export saves a local file.</p></header>
{cases}
<footer><label>Reviewer name <input id="reviewer" type="text" autocomplete="off"></label>
<label><input id="attest" type="checkbox"> I am a human and personally inspected every case above</label>
<button id="export" type="button" disabled>Export review-decisions.json</button> <span id="status"></span></footer>
<script>{script}</script></body></html>
"""


def write_review_form(corpus: LoadedCorpus, manifest_path: Path, manifest_sha256: str, output: Path) -> None:
    if output.resolve().parent != manifest_path.resolve().parent:
        raise ReviewError("review_form_must_be_next_to_manifest")
    content = render_review_form(corpus.manifest, manifest_sha256, manifest_path.name)
    write_new_file(output, content.encode("utf-8"))

