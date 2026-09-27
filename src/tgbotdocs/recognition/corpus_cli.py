"""Corpus review commands: ``python -m tgbotdocs.recognition.corpus_cli {review-form,review-apply,status}``.

Output is content-free: case IDs, counts, hashes and fixed error codes only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .corpus import CorpusError, load_corpus
from .review import (ReviewError, apply_decisions, corpus_status, manifest_bytes, parse_decisions, sha256_bytes,
                     write_new_file, write_review_form)


EXPLANATIONS = {
    "readable_case_value_not_legible_reject_case": "a readable case promises that every present value is legible; "
    "mark the case rejected instead of recording a value as not legible",
    "benchmark_rejection_requires_replacement_case": "the 40/20/10 benchmark composition is never shrunk; prepare a "
    "new case of the same category, script and quality to replace each rejected case before measurement",
    "review_result_ineligible_for_calibration": "removing the rejected cases would leave a tuning set that is not "
    "eligible for calibration; prepare replacement cases first",
    "review_manifest_hash_mismatch": "the decisions were exported for different manifest bytes",
    "human_attestation_missing": "the reviewer did not attest to personally inspecting every case",
    "review_already_recorded": "only a manifest whose cases are all pending review can be transcribed",
}


def _read(path: Path, code: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise ReviewError(code) from None


def _load(path: Path):
    data = _read(path, "manifest_unavailable")
    corpus = load_corpus(path)
    if _read(path, "manifest_unavailable") != data:
        raise ReviewError("manifest_changed_while_loading")
    return corpus, sha256_bytes(data)


def _review_form(args) -> int:
    corpus, digest = _load(args.manifest)
    write_review_form(corpus, args.manifest, digest, args.output)
    print(json.dumps({"review_form": str(args.output), "manifest_sha256": digest, "cases": len(corpus.cases)}))
    return 0


def _review_apply(args) -> int:
    if args.output.resolve().parent != args.manifest.resolve().parent:
        raise ReviewError("reviewed_manifest_must_be_next_to_manifest")
    corpus, digest = _load(args.manifest)
    decisions = parse_decisions(_read(args.decisions, "review_decisions_unavailable"))
    reviewed, removed = apply_decisions(corpus.manifest, digest, decisions)
    data = manifest_bytes(reviewed)
    write_new_file(args.output, data)
    load_corpus(args.output)  # the written manifest must load with every artifact hash verified
    print(json.dumps({"reviewed_manifest": str(args.output), "sha256": sha256_bytes(data),
                      "verified_cases": len(reviewed.cases), "removed_rejected_case_ids": list(removed),
                      "purpose": reviewed.purpose}))
    return 0


def _status(args) -> int:
    corpus, digest = _load(args.manifest)
    print(json.dumps({"manifest_sha256": digest, "files_verified": corpus.files_verified,
                      **corpus_status(corpus.manifest)}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tgbotdocs.recognition.corpus_cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    form = commands.add_parser("review-form", help="write a static human review form next to the manifest")
    form.add_argument("--manifest", type=Path, required=True)
    form.add_argument("--output", type=Path, required=True)
    form.set_defaults(handler=_review_form)
    apply = commands.add_parser("review-apply", help="transcribe human review decisions into a new manifest")
    apply.add_argument("--manifest", type=Path, required=True)
    apply.add_argument("--decisions", type=Path, required=True)
    apply.add_argument("--output", type=Path, required=True)
    apply.set_defaults(handler=_review_apply)
    status = commands.add_parser("status", help="print content-free eligibility and composition")
    status.add_argument("--manifest", type=Path, required=True)
    status.set_defaults(handler=_status)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ReviewError as error:
        detail = f" ({error.detail})" if error.detail else ""
        explanation = f": {EXPLANATIONS[error.code]}" if error.code in EXPLANATIONS else ""
        print(f"error: {error.code}{detail}{explanation}", file=sys.stderr)
    except CorpusError as error:
        print(f"error: {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
