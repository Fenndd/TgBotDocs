"""Human review tooling. Decisions and attestations below are synthetic test data, not a human review."""
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
import os
import re
import shutil
import subprocess

import pytest

from tgbotdocs.recognition import corpus_cli
from tgbotdocs.recognition.contracts import ExtractionProfile, ListField, ScalarField
from tgbotdocs.recognition.corpus import (Artifact, CorpusCase, CorpusManifest, ExpectedList, ExpectedOutcome,
                                          ExpectedRow, ExpectedValue, Origin, case_review_digest,
                                          declared_denominators, load_corpus)
from tgbotdocs.recognition import review
from tgbotdocs.recognition.review import manifest_bytes, parse_decisions, reviewable_values

SCRIPTS = ("Latin", "Cyrillic", "Arabic", "Chinese", "Japanese", "Devanagari")
CATEGORIES = ("identity", "invoice", "receipt", "certificate", "contract", "application", "letter", "repeating_rows")
CODE = ScalarField(id="code", label="Code", description="Printed code", type="text")
ROWS = ListField(id="rows", label="Rows", description="Printed rows",
                 columns=(ScalarField(id="item", label="Item", description="Item", type="text"),
                          ScalarField(id="qty", label="Qty", description="Quantity", type="text")))


def extracted(field_id, value, pages=(1,)):
    return ExpectedValue(field_id=field_id, status="extracted", present=True, value=value, source_pages=pages)


def make_case(root, index, quality, value="VALUE"):
    case_id = f"case-{index:02d}"
    files = {"input": (f"{case_id}.png", "image_file"), "sheet": (f"{case_id}-review.png", "reference")}
    artifacts = []
    for identity, (path, kind) in files.items():
        data = f"synthetic {path}".encode()
        (root / path).write_bytes(data)
        artifacts.append(Artifact(id=identity, path=path, sha256=hashlib.sha256(data).hexdigest(), kind=kind))
    profile = ExtractionProfile(id=f"profile-{index}", owner="synthetic-user", version=1, name=f"Profile {index}",
                                description="Synthetic", original_instruction="Read", fields=(CODE, ROWS))
    if quality == "negative":
        expected = ExpectedOutcome(matching="not_document", outcome="refused")
    else:
        rows = tuple(ExpectedRow(source_key=f"row-{n}", source_pages=(1,),
                                 cells=(extracted("item", f"{value}-item-{n}"), extracted("qty", str(n))))
                     for n in (1, 2))
        expected = ExpectedOutcome(matching="matched", profile_id=profile.id, outcome="complete",
                                   fields=(extracted("code", value),),
                                   lists=(ExpectedList(field_id="rows", status="complete", enumeration_complete=True,
                                                       rows=rows),))
    return CorpusCase(case_id=case_id, origin=Origin(family_id=case_id, kind="synthetic", permission_basis="synthetic",
                                                     original_sha256=hashlib.sha256(case_id.encode()).hexdigest()),
                      script=SCRIPTS[index % 6], language="en", category=CATEGORIES[index % 8], quality=quality,
                      scenario="synthetic_test", delivery_path="image_file", artifacts=tuple(artifacts),
                      input_artifact_ids=("input",), page_ids=(1,), profiles=(profile,), expected=expected)


def write_manifest(root, *, split="tuning", count=24, value="VALUE"):
    root.mkdir(parents=True, exist_ok=True)
    qualities = ["readable"] * (count - 8) + ["difficult"] * 4 + ["negative"] * 4
    cases = tuple(make_case(root, index, quality, value) for index, quality in enumerate(qualities))
    manifest = CorpusManifest(schema_version=1, split=split, purpose="review_preparation", cases=cases,
                              denominators=declared_denominators(cases))
    path = root / "manifest.json"
    path.write_bytes(manifest_bytes(manifest))
    return path, manifest


def decisions_for(manifest, path, **changes):
    cases = [{"case_id": case.case_id, "decision": "verified", "method": "script_reading", "notes": "",
              "values": [{"field_id": key[0], "row_key": key[1], "column_id": key[2], "visibility": "legible"}
                         for key, _ in reviewable_values(case)]} for case in manifest.cases]
    data = {"schema_version": 1, "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "reviewer": "Synthetic test reviewer", "reviewer_attests_human_inspection": True,
            "reviewed_at": "2026-09-27T12:30:00+03:00", "cases": cases}
    data.update(changes)
    return data


def run(args, capsys):
    code = corpus_cli.main([str(arg) for arg in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def apply(tmp_path, path, data, capsys, name="reviewed.json"):
    decisions = tmp_path / "review-decisions.json"
    decisions.write_text(json.dumps(data), encoding="utf-8")
    output = path.parent / name
    return (*run(["review-apply", "--manifest", path, "--decisions", decisions, "--output", output], capsys), output)


def case_decision(data, case_id):
    return next(case for case in data["cases"] if case["case_id"] == case_id)


@pytest.fixture
def corpus(tmp_path):
    return write_manifest(tmp_path / "corpus")


def test_review_form_is_static_escaped_and_complete(tmp_path, capsys):
    path, manifest = write_manifest(tmp_path / "corpus", value="<img src=x onerror=alert(1)>")
    form = path.parent / "review-form.html"
    code, out, _ = run(["review-form", "--manifest", path, "--output", form], capsys)
    assert code == 0 and "<img src=x" not in out
    page = form.read_text(encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.dumps(digest) in page and "connect-src 'none'" in page
    assert "<img src=x onerror" not in page and "&lt;img src=x onerror=alert(1)&gt;" in page
    assert not re.search(r"(?:src|href)=\"(?:https?:|//)", page)
    assert all(f'data-case="{case.case_id}"' in page for case in manifest.cases)
    assert 'src="case-00.png"' in page and 'src="case-00-review.png"' in page
    assert page.count('<tr class="value"') == sum(len(reviewable_values(case)) for case in manifest.cases)
    assert "I am a human and personally inspected every case above" in page
    assert '<button id="export" type="button" disabled>' in page
    # Readable values default to legible; difficult values have no default.
    readable = page.split('data-case="case-00"')[1].split("</section>")[0]
    difficult = page.split('data-case="case-16"')[1].split("</section>")[0]
    assert readable.count('value="legible" checked') == 5 and "checked" not in difficult


def test_review_form_location_and_overwrite(corpus, tmp_path, capsys):
    path, _ = corpus
    code, _, err = run(["review-form", "--manifest", path, "--output", tmp_path / "form.html"], capsys)
    assert code == 2 and "review_form_must_be_next_to_manifest" in err
    existing = path.parent / "review-form.html"
    existing.write_text("keep", encoding="utf-8")
    code, _, err = run(["review-form", "--manifest", path, "--output", existing], capsys)
    assert code == 2 and "output_exists" in err and existing.read_text(encoding="utf-8") == "keep"


def test_apply_transcribes_human_decisions(corpus, tmp_path, capsys):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    case_decision(data, "case-03").update(decision="rejected", method=None, values=[])
    case_decision(data, "case-05")["method"] = "glyph_sequence_comparison"
    code, out, err, output = apply(tmp_path, path, data, capsys)
    assert code == 0, err
    report = json.loads(out)
    assert report["removed_rejected_case_ids"] == ["case-03"]
    assert report["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    reviewed = load_corpus(output).manifest
    assert reviewed.purpose == "quality_measurement" and len(reviewed.cases) == 23
    assert reviewed.eligibility_reasons("calibration") == ()
    assert reviewed.denominators == declared_denominators(reviewed.cases)
    case = {case.case_id: case for case in reviewed.cases}["case-05"]
    assert (case.review.status, case.review.reviewer_kind, case.review.method) == ("verified", "human",
                                                                                   "glyph_sequence_comparison")
    assert case.review.reviewer == "Synthetic test reviewer" and case.review.subject_sha256 == case_review_digest(case)
    assert case.review.reviewed_at.utcoffset().total_seconds() == 3 * 3600
    assert case.expected == manifest.cases[5].expected  # all legible: ground truth unchanged


def test_not_legible_values_become_unreadable_and_lists_degrade(corpus, tmp_path, capsys):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    first = case_decision(data, "case-16")["values"]
    for value in first:  # the scalar and one cell of row-1
        if value["row_key"] is None or (value["row_key"], value["column_id"]) == ("row-1", "item"):
            value["visibility"] = "not_legible"
    for value in case_decision(data, "case-17")["values"]:
        value["visibility"] = "not_legible" if value["row_key"] else "legible"
    code, _, err, output = apply(tmp_path, path, data, capsys)
    assert code == 0, err
    cases = {case.case_id: case for case in load_corpus(output).manifest.cases}
    partial = cases["case-16"].expected
    assert (partial.fields[0].status, partial.fields[0].value, partial.fields[0].present) == ("unreadable", None, True)
    assert (partial.lists[0].status, partial.lists[0].enumeration_complete) == ("partial", False)
    assert [c.status for c in partial.lists[0].rows[0].cells] == ["unreadable", "extracted"]
    assert partial.outcome == "partial"
    unresolved = cases["case-17"].expected
    assert (unresolved.lists[0].status, unresolved.lists[0].reason) == ("unresolved", "unreadable")
    assert unresolved.fields[0].status == "extracted" and unresolved.outcome == "partial"
    before = declared_denominators(manifest.cases).known_readable_values
    after = declared_denominators(tuple(cases.values())).known_readable_values
    assert after == before - 2 - 4


@pytest.mark.parametrize("change, code", [
    (lambda d: d.update(manifest_sha256="0" * 64), "review_manifest_hash_mismatch"),
    (lambda d: d.update(reviewer_attests_human_inspection=False), "human_attestation_missing"),
    (lambda d: d.update(reviewer="   "), "reviewer_name_missing"),
    (lambda d: d.update(reviewed_at="2026-09-27T12:30:00"), "review_timestamp_timezone_required"),
    (lambda d: d["cases"].pop(), "review_decisions_incomplete"),
    (lambda d: d["cases"].append(dict(d["cases"][0], case_id="case-99")), "review_decision_unknown_case"),
    (lambda d: d["cases"].append(dict(d["cases"][0])), "review_decision_duplicate_case"),
    (lambda d: d["cases"][0]["values"].pop(), "review_decisions_incomplete"),
    (lambda d: d["cases"][0]["values"].append({"field_id": "other", "visibility": "legible"}),
     "review_decision_unknown_value"),
    (lambda d: d["cases"][0].update(method=None), "review_method_required"),
    (lambda d: d["cases"][0].update(decision="approved"), "review_decisions_invalid"),
    (lambda d: d["cases"][0]["values"][0].update(visibility="not_legible"), "readable_case_value_not_legible"),
    (lambda d: [case.update(decision="rejected") for case in d["cases"][:5]], "ineligible_for_calibration"),
    (lambda d: [case.update(decision="rejected") for case in d["cases"]], "review_result_empty"),
])
def test_apply_refuses_incomplete_or_unattested_decisions(corpus, tmp_path, capsys, change, code):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    change(data)
    exit_code, _, err, _ = apply(tmp_path, path, data, capsys)
    assert exit_code == 2 and code in err
    assert not (path.parent / "reviewed.json").exists()
    assert "VALUE" not in err


def test_readable_not_legible_error_explains_rejection(corpus, tmp_path, capsys):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    data["cases"][0]["values"][0]["visibility"] = "not_legible"
    _, _, err, _ = apply(tmp_path, path, data, capsys)
    assert "case-00" in err and "mark the case rejected" in err


def test_benchmark_rejection_requires_replacement(tmp_path, capsys):
    path, manifest = write_manifest(tmp_path / "benchmark", split="benchmark")
    data = decisions_for(manifest, path)
    data["cases"][0].update(decision="rejected")
    code, _, err, _ = apply(tmp_path, path, data, capsys)
    assert code == 2 and "benchmark_rejection_requires_replacement_case" in err and "same category" in err


def test_reviewed_manifest_cannot_be_reviewed_again_or_overwritten(corpus, tmp_path, capsys):
    path, manifest = corpus
    assert apply(tmp_path, path, decisions_for(manifest, path), capsys)[0] == 0
    reviewed = path.parent / "reviewed.json"
    before = reviewed.read_bytes()
    code, _, err, _ = apply(tmp_path, path, decisions_for(manifest, path), capsys)
    assert code == 2 and "output_exists" in err and reviewed.read_bytes() == before
    again = load_corpus(reviewed).manifest
    code, _, err, _ = apply(tmp_path, reviewed, decisions_for(again, reviewed), capsys, name="twice.json")
    assert code == 2 and "review_already_recorded" in err


def test_apply_verifies_artifact_bytes(corpus, tmp_path, capsys):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    (path.parent / "case-00.png").write_bytes(b"changed after review")
    code, _, err, _ = apply(tmp_path, path, data, capsys)
    assert code == 2 and "artifact_hash_mismatch" in err


def test_status_is_content_free(corpus, capsys):
    path, _ = corpus
    code, out, _ = run(["status", "--manifest", path], capsys)
    status = json.loads(out)
    assert code == 0 and "VALUE" not in out
    assert status["cases"] == 24 and status["reviews"] == {"pending": 24}
    assert status["by_quality"] == {"difficult": 4, "negative": 4, "readable": 16}
    assert sum(status["by_script"].values()) == 24 and len(status["by_category"]) == 8
    assert status["by_delivery_path"] == {"image_file": 24}
    assert len(status["pending_review_case_ids"]) == 24 and status["files_verified"] is True
    assert "human_review_or_ground_truth_pending" in status["eligibility"]["calibration"]
    assert "benchmark_not_sealed_and_frozen" in status["eligibility"]["benchmark"]


def test_review_form_offers_only_methods_applicable_to_origin(tmp_path, capsys):
    path, manifest = write_manifest(tmp_path / "corpus")
    form = path.parent / "review-form.html"
    assert run(["review-form", "--manifest", path, "--output", form], capsys)[0] == 0
    page = form.read_text(encoding="utf-8")
    assert all(case.origin.kind == "synthetic" for case in manifest.cases)
    assert 'value="published_transcription"' not in page
    assert page.count('<option value="script_reading">') == len(manifest.cases)
    assert page.count('<option value="glyph_sequence_comparison">') == len(manifest.cases)
    public = make_case(tmp_path / "corpus", 0, "readable")
    public = public.model_copy(update={"origin": public.origin.model_copy(update={"kind": "permitted_public"})})
    assert review.applicable_methods(public) == review.METHODS


def test_published_transcription_refused_for_synthetic_case(corpus, tmp_path, capsys):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    case_decision(data, "case-02")["method"] = "published_transcription"
    code, _, err, output = apply(tmp_path, path, data, capsys)
    assert code == 2 and "review_method_not_applicable_to_origin (case-02)" in err and "public materials" in err
    assert not output.exists()


class _FailingStream:
    """Writes a few bytes, then fails like a full disk."""

    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stream.close()

    def write(self, data):
        self.stream.write(data[:10])
        raise OSError("synthetic write failure")


@pytest.mark.parametrize("failure", ["verify", "write"])
def test_failed_output_is_removed_and_retry_succeeds(corpus, tmp_path, capsys, monkeypatch, failure):
    path, manifest = corpus
    data = decisions_for(manifest, path)
    if failure == "verify":
        original = corpus_cli.load_corpus

        def check(target, **kwargs):  # an artifact changes between the input load and the post-write check
            if target.name == "reviewed.json":
                raise corpus_cli.CorpusError("artifact_hash_mismatch")
            return original(target, **kwargs)
        monkeypatch.setattr(corpus_cli, "load_corpus", check)
    else:
        opener = type(path).open

        def failing_open(self, mode="r", *args, **kwargs):
            stream = opener(self, mode, *args, **kwargs)
            return _FailingStream(stream) if self.name == "reviewed.json" and mode == "xb" else stream
        monkeypatch.setattr(type(path), "open", failing_open)
    code, _, err, output = apply(tmp_path, path, data, capsys)
    assert code == 2 and ("artifact_hash_mismatch" if failure == "verify" else "output_unwritable") in err
    assert not output.exists()
    monkeypatch.undo()
    code, _, err, output = apply(tmp_path, path, data, capsys)
    assert code == 0, err
    assert output.exists()


# ---------------------------------------------------------------------------
# The form's own export code, run in node against a minimal DOM shim

NODE = shutil.which("node")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

DOM_SHIM = r"""
const fs = require("fs");
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
function El(node, parent) {
  this.tagName = node.tag; this.attrs = node.attrs; this.parent = parent; this.listeners = {};
  this.checked = "checked" in node.attrs; this.disabled = "disabled" in node.attrs; this.textContent = "";
  this.value = node.tag === "textarea" ? node.text : (node.attrs.value !== undefined ? node.attrs.value : "");
  this.children = node.children.map((child) => new El(child, this));
  if (node.tag === "select") {
    const options = this.children.filter((c) => c.tagName === "option");
    const chosen = options.find((o) => "selected" in o.attrs) || options[0];
    this.value = chosen ? chosen.attrs.value : "";
  }
}
El.prototype.getAttribute = function (name) { return name in this.attrs ? this.attrs[name] : null; };
El.prototype.hasAttribute = function (name) { return name in this.attrs; };
El.prototype.addEventListener = function (type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); };
El.prototype.descendants = function* () { for (const c of this.children) { yield c; yield* c.descendants(); } };
El.prototype.querySelectorAll = function (selector) {
  const m = /^([a-z]+)?(?:\.([\w-]+))?(?:\[([\w-]+)="([^"]*)"\])?(:checked)?$/.exec(selector);
  if (!m) { throw new Error("unsupported selector " + selector); }
  const out = [];
  for (const el of this.descendants()) {
    if (m[1] && el.tagName !== m[1]) { continue; }
    if (m[2] && !(el.getAttribute("class") || "").split(/\s+/).includes(m[2])) { continue; }
    if (m[3] && el.getAttribute(m[3]) !== m[4]) { continue; }
    if (m[5] && !el.checked) { continue; }
    out.push(el);
  }
  return out;
};
El.prototype.querySelector = function (selector) { return this.querySelectorAll(selector)[0] || null; };
const root = new El(input.tree, null);
const blobs = {};
let exported = null;
let downloadName = null;
const document = {
  body: { appendChild() {} },
  listeners: {},
  getElementById(id) { return root.querySelector("[id=\"" + id + "\"]"); },
  querySelectorAll(selector) { return root.querySelectorAll(selector); },
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  createElement() { return { click() { exported = blobs[this.href]; downloadName = this.download; }, remove() {} }; },
};
function Blob(parts) { this.text = parts.join(""); }
const URL = {
  createObjectURL(blob) { const key = "blob:" + Object.keys(blobs).length; blobs[key] = blob.text; return key; },
  revokeObjectURL() {},
};
new Function("document", "Blob", "URL", "setTimeout", input.script)(document, Blob, URL, function () {});
function fire() { (document.listeners.change || []).forEach((fn) => fn()); }
const button = document.getElementById("export");
const disabled = [];
for (const step of input.steps) {
  if (step.op === "value") { document.getElementById(step.id).value = step.value; }
  else if (step.op === "check") { document.getElementById(step.id).checked = step.checked; }
  else if (step.op === "radio") {
    for (const el of root.querySelectorAll("input[name=\"" + step.name + "\"]")) {
      el.checked = el.getAttribute("value") === step.value;
    }
  } else if (step.op === "select") { root.querySelector("select[name=\"" + step.name + "\"]").value = step.value; }
  else if (step.op === "click") { button.listeners.click.forEach((fn) => fn()); }
  fire();
  disabled.push(button.disabled);
}
process.stdout.write(JSON.stringify({disabled: disabled, exported: exported, download: downloadName}));
"""


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "attrs": {}, "children": [], "text": ""}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: "" if v is None else v for k, v in attrs}, "children": [], "text": ""}
        self.stack[-1]["children"].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        while len(self.stack) > 1:
            if self.stack.pop()["tag"] == tag:
                break

    def handle_data(self, data):
        self.stack[-1]["text"] += data


def run_form(tmp_path, page, steps, tz):
    parser = _Tree()
    parser.feed(page)
    script = re.search(r"<script>(.*)</script>", page, re.S).group(1)
    harness = tmp_path / "harness.js"
    harness.write_text(DOM_SHIM, encoding="utf-8")
    state = tmp_path / "form-state.json"
    state.write_text(json.dumps({"tree": parser.root, "script": script, "steps": steps}), encoding="utf-8")
    result = subprocess.run([NODE, str(harness), str(state)], capture_output=True, text=True, encoding="utf-8",
                            timeout=60, env={**os.environ, "TZ": tz}, check=True)
    return json.loads(result.stdout)


def render_form(path, capsys):
    form = path.parent / "review-form.html"
    assert run(["review-form", "--manifest", path, "--output", form], capsys)[0] == 0
    return form.read_text(encoding="utf-8")


@pytest.mark.skipif(NODE is None, reason="node is not available to run the form script")
@pytest.mark.parametrize("tz, offset_minutes", [("Asia/Kolkata", 330), ("America/Sao_Paulo", -180)])
def test_form_export_is_gated_and_round_trips_through_review_apply(corpus, tmp_path, capsys, tz, offset_minutes):
    path, manifest = corpus
    page = render_form(path, capsys)
    required = [{"op": "value", "id": "reviewer", "value": " Synthetic test reviewer "},
                {"op": "check", "id": "attest", "checked": True}]
    difficult = []
    for index, case in enumerate(manifest.cases):
        rejected = case.case_id == "case-03"
        required.append({"op": "radio", "name": f"c{index}-decision", "value": "rejected" if rejected else "verified"})
        if not rejected:
            required.append({"op": "select", "name": f"c{index}-method",
                             "value": "glyph_sequence_comparison" if index == 5 else "script_reading"})
        if case.quality == "difficult":
            difficult += [{"op": "radio", "name": f"c{index}-v{n}",
                           "value": "not_legible" if index == 16 and n == 0 else "legible"}
                          for n in range(len(reviewable_values(case)))]
    toggles = [({"op": "select", "name": "c0-method", "value": ""},
                {"op": "select", "name": "c0-method", "value": "script_reading"}),
               ({"op": "value", "id": "reviewer", "value": "   "},
                {"op": "value", "id": "reviewer", "value": "Synthetic test reviewer"}),
               ({"op": "check", "id": "attest", "checked": False},
                {"op": "check", "id": "attest", "checked": True})]
    steps = [{"op": "click"}] + required + difficult + [step for pair in toggles for step in pair] + [{"op": "click"}]
    result = run_form(tmp_path, page, steps, tz)
    complete_at = 1 + len(required) + len(difficult)
    # Export stays disabled (an early click exports nothing) until the last required item is chosen.
    assert all(result["disabled"][:complete_at - 1]) and result["disabled"][complete_at - 1] is False
    assert result["disabled"][complete_at:] == [True, False] * len(toggles) + [False]
    assert result["download"] == "review-decisions.json" and result["exported"]
    data = json.loads(result["exported"])
    decisions = parse_decisions(result["exported"].encode("utf-8"))
    assert decisions.reviewed_at.utcoffset().total_seconds() == offset_minutes * 60
    assert datetime.fromisoformat(data["reviewed_at"]).tzinfo is not None
    assert case_decision(data, "case-03") == {"case_id": "case-03", "decision": "rejected", "method": None,
                                              "values": [], "notes": ""}
    code, out, err, output = apply(tmp_path, path, data, capsys)
    assert code == 0, err
    assert json.loads(out)["removed_rejected_case_ids"] == ["case-03"]
    cases = {case.case_id: case for case in load_corpus(output).manifest.cases}
    assert cases["case-05"].review.method == "glyph_sequence_comparison"
    assert cases["case-16"].expected.fields[0].status == "unreadable"
    assert cases["case-00"].review.reviewer == "Synthetic test reviewer"


@pytest.mark.skipif(NODE is None, reason="node is not available to run the form script")
def test_form_export_requires_difficult_visibility(corpus, tmp_path, capsys):
    path, manifest = corpus
    page = render_form(path, capsys)
    steps = [{"op": "value", "id": "reviewer", "value": "Synthetic test reviewer"},
             {"op": "check", "id": "attest", "checked": True}]
    for index, _ in enumerate(manifest.cases):
        steps += [{"op": "radio", "name": f"c{index}-decision", "value": "verified"},
                  {"op": "select", "name": f"c{index}-method", "value": "script_reading"}]
    steps.append({"op": "click"})
    result = run_form(tmp_path, page, steps, "UTC")
    assert all(result["disabled"]) and result["exported"] is None
