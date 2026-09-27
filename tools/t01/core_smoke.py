"""Technical smoke of production modules on the synthetic dev-01 fixture.

This deliberately cannot produce a calibration/benchmark pass. Human corpus
review is pending. Prints only content-free counts, timings and fixed errors.
"""
import argparse
import asyncio
import dataclasses
import json
from pathlib import Path
import tempfile

from tgbotdocs.recognition.adapter import ModelAdapter, ModelError
from tgbotdocs.recognition.contracts import ExtractionProfile, ListField, ScalarField
from tgbotdocs.recognition.core import CoreSettings, RecognitionCore
from tgbotdocs.recognition.preparation import PreparationError
from tgbotdocs.recognition.runtime import LocalRuntime, RuntimeFiles, RuntimeProfile
from tgbotdocs.recognition.verification import VerificationPolicy
from tgbotdocs.recognition import prompts


class MeasuredAdapter(ModelAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.counts, self.calls = [], []

    async def count_input_tokens(self, *args, **kwargs):
        count = await super().count_input_tokens(*args, **kwargs)
        self.counts.append(count)
        return count

    async def generate(self, *args, **kwargs):
        reply = await super().generate(*args, **kwargs)
        self.calls.append({"prompt_tokens": reply.prompt_tokens, "generated_tokens": reply.generated_tokens,
                           "probabilities_aligned": reply.probabilities_aligned, "duration_s": reply.duration_s})
        return reply


async def run(args):
    root = args.development
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    assert case["id"] == "dev-01" and manifest["synthetic_only"] is True
    profile = ExtractionProfile(id="dev-invoice", owner="synthetic", version=1,
        name="Invoice", description="An invoice with supplier, date, reference, total and line items.",
        original_instruction="Read reference, supplier, date, total and each item, quantity and amount.",
        fields=tuple(ScalarField(id=name, label=name.title(), description=f"Printed {name}", type="text")
                     for name in ("reference", "supplier", "date", "total")) + (
            ListField(id="rows", label="Items", description="Invoice line items", columns=tuple(
                ScalarField(id=name, label=name.title(), description=f"Printed item {name}", type="text")
                for name in ("item", "quantity", "amount"))),))
    runtime_profile = RuntimeProfile()
    report = {"purpose": "technical_diagnostic_not_quality_measurement", "human_review": "pending",
              "calibrated": False, "runtime_profile": dataclasses.asdict(runtime_profile), "alternate_view": args.alternate}
    original_parse = prompts.parse_batch
    def diagnostic_parse(*values):
        try:
            return original_parse(*values)
        except ValueError as error:
            detail = ([{"type": e["type"], "loc": e["loc"], "message": e["msg"]} for e in error.errors(include_input=False)]
                      if hasattr(error, "errors") else type(error).__name__ + ":" + str(error))
            report.setdefault("contract_errors", []).append(detail)
            raise
    prompts.parse_batch = diagnostic_parse
    files = RuntimeFiles(args.runtime / "llama-server.exe", args.models / "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
                         args.models / "mmproj-Qwen3VL-4B-Instruct-F16.gguf")
    async with LocalRuntime(files, runtime_profile) as runtime:
        adapter = MeasuredAdapter(runtime.adapter_settings, restart=runtime.restart)
        try:
            core = RecognitionCore(adapter, CoreSettings(runtime=runtime_profile,
                verification=VerificationPolicy(check_alternate_view=args.alternate), matching_margin=.1))
            with tempfile.TemporaryDirectory(prefix="tgbotdocs-core-smoke-") as directory:
                result = await core.recognize(tuple(root / name for name in case["inputs"]), (profile,),
                                              scratch=Path(directory), selected_profile=profile if args.manual else None)
                report.update({"matching_status": result.matching.status, "metrics": result.metrics,
                               "temporary_renders_removed": not any(Path(directory).iterdir())})
                if result.recognition:
                    accepted = {f.field_id: f.accepted_value for f in result.recognition.fields if f.status == "extracted"}
                    for listing in result.recognition.lists:
                        for index, row in enumerate(listing.rows):
                            accepted.update({f"{listing.field_id}[{index}].{cell.field_id}": cell.accepted_value
                                             for cell in row.cells if cell.status == "extracted"})
                    expected = {f["field"]: f["value"] for f in case["expected_response"][0]["fields"]}
                    report.update({"outcome": result.recognition.outcome, "expected_value_count": len(expected),
                                   "accepted_value_count": len(accepted),
                                   "exact_accepted_count": sum(value == expected.get(key) for key, value in accepted.items())})
        except (ModelError, PreparationError) as error:
            report["error"] = error.code
        finally:
            report["counted_prompts"] = adapter.counts
            report["calls"] = adapter.calls
            await adapter.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--alternate", action="store_true")
    parser.add_argument("--manual", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
