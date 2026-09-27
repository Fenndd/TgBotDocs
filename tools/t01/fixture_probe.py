"""T01a exploratory runtime and legibility diagnostics on synthetic development cases.

Refuses non-synthetic manifests. Never claims calibration or benchmark acceptance.
Input documents remain development fixtures; response content stays in RAM only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from runtime_probe import CONFIGS, Runtime


def load_image(root, metadata):
    path = (root / metadata["path"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Fixture path outside manifest directory")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
        raise ValueError("Fixture hash mismatch")
    return content


def pick(page, kind, dpi=None):
    return next(image for image in page["images"] if image["kind"] == kind and (dpi is None or image.get("dpi") == dpi))


def fields_request(runtime, root, pages):
    expected = {f"{page_id}:{field['field']}": field["value"]
                for page_id, image in pages for field in image["annotations"]}
    schema = {"type": "object", "properties": {key: {"type": "string"} for key in expected},
              "required": list(expected), "additionalProperties": False}
    instruction = ("The images are pages " + ", ".join(page_id for page_id, _ in pages) +
                   ". Copy the requested fields exactly from each corresponding image. "
                   "Use these exact JSON keys: " + json.dumps(list(expected)) +
                   ". rows[N].column means the Nth data row (zero based) of the table; omit headers. "
                   "Do not translate or normalize values. No extra fields.")

    def evaluate(parsed):
        return {"requested_values": len(expected),
                "exact_values": sum(parsed.get(key) == value for key, value in expected.items())}

    return runtime.request([load_image(root, image) for _, image in pages], schema=schema,
                           instruction=instruction, expected=expected, evaluate=evaluate)


def iou(left, right):
    a = max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(0, min(left[3], right[3]) - max(left[1], right[1]))
    union = max(0, left[2]-left[0])*max(0, left[3]-left[1]) + max(0, right[2]-right[0])*max(0, right[3]-right[1]) - a
    return a / union if union else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", choices=[c["id"] for c in CONFIGS], default="gpu-q8-512")
    parser.add_argument("--mode", choices=["matrix", "development", "localization", "envelope"], required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("synthetic_only") is not True:
        raise ValueError("Only explicitly synthetic development fixtures are permitted")
    root = args.manifest.parent
    cases = manifest["cases"]
    config = next(c for c in CONFIGS if c["id"] == args.config)
    runtime = Runtime(args.root, config, 18081)
    report = {"mode": args.mode, "configuration": config, "requests": [],
              "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              "eligible_for_quality_measurement": False,
              "notice": "Exploratory synthetic diagnostic; human review pending; no benchmark or calibration claims"}
    try:
        report["load_s"] = runtime.start()
        jobs = []
        if args.mode in ("matrix", "envelope"):
            pdf_page = next(c for c in cases if c["id"] == "dev-08")["pages"][0]
            image_page = cases[0]["pages"][0]
            for kind, page, dpi in [("pdf_render", pdf_page, 150), ("pdf_render", pdf_page, 200),
                                    ("simulated_telegram_photo_1280", image_page, None),
                                    ("simulated_telegram_photo_2560", image_page, None)]:
                image = pick(page, kind, dpi)
                jobs.append((f"{kind}-{dpi}", [(page["page_id"], image)]))
        elif args.mode == "development":
            for case in cases:
                kind = "pdf_render" if case["delivery_path"] == "pdf" else case["delivery_path"]
                pages = [(p["page_id"], pick(p, kind, 150 if kind == "pdf_render" else None)) for p in case["pages"]]
                jobs.append((case["id"], pages))
        for job_id, pages in jobs:
            counts = (1, 2, 3, 4, 6, 8) if args.mode == "envelope" else (1,)
            for count in counts:
                repeated = [(f"page-{n + 1}", pages[0][1]) for n in range(count)] if args.mode == "envelope" else pages
                result = fields_request(runtime, root, repeated)
                result.update({"id": job_id, "pages": len(repeated),
                               "input_sha256": [img["sha256"] for _, img in repeated]})
                report["requests"].append(result)
                print(json.dumps({"id": job_id, "pages": len(repeated), "schema": result.get("schema_valid"),
                                  "values": result.get("evaluation"), "reserve": result.get("output_reserve_fits_context"),
                                  "seconds": result["duration_s"]}), flush=True)
                if not result.get("ok") or not result.get("output_reserve_fits_context"):
                    break
        if args.mode == "localization":
            for case in cases[:6]:
                image = pick(case["pages"][0], "simulated_telegram_photo_1280")
                field = image["annotations"][0]
                ground = [v / (image["width"] if i % 2 == 0 else image["height"]) * 1000 for i, v in enumerate(field["bbox_px"])]
                schema = {"type": "object", "properties": {"box": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}}, "required": ["box"], "additionalProperties": False}
                def evaluate(parsed, reference=ground):
                    box = parsed["box"]
                    return {"iou": iou(box, reference), "valid_bounds": 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000}
                result = runtime.request([load_image(root, image)], schema=schema,
                                         instruction=f"Locate only the printed VALUE of field {field['field']}, excluding its label. Return box [x1,y1,x2,y2] in coordinates 0 to 1000 relative to full image.", evaluate=evaluate)
                result["id"] = case["id"]
                report["requests"].append(result)
                print(json.dumps({"id": case["id"], "localization": result.get("evaluation")}), flush=True)
    except Exception as error:
        report["failure_type"] = type(error).__name__
    finally:
        if runtime.metrics:
            report["resources"] = runtime.metrics.snapshot()
        report["stop_s"] = runtime.stop()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 1 if report.get("failure_type") else 0


if __name__ == "__main__":
    sys.exit(main())
