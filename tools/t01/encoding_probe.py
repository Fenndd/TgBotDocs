"""Measure isolated vision-encoding durations via the pinned CLI helper path.

The official b11221 server does not expose this duration separately. These
numbers describe llama-mtmd-cli, not the server's batched encoder path.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from runtime_probe import CONFIGS, Resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not manifest.get("synthetic_only"):
        raise ValueError("Only synthetic fixtures are permitted")
    report = {"measurement_path": "llama-mtmd-cli helper, not server batching", "measurements": []}
    page = next(case for case in manifest["cases"] if case["id"] == "dev-08")["pages"][0]
    image = next(image for image in page["images"] if image["kind"] == "pdf_render" and image["dpi"] == 150)
    image_path = (args.manifest.parent / image["path"]).resolve()
    if not image_path.is_relative_to(args.manifest.parent.resolve()):
        raise ValueError("Fixture outside manifest directory")
    if hashlib.sha256(image_path.read_bytes()).hexdigest() != image["sha256"]:
        raise ValueError("Fixture hash mismatch")
    for config in CONFIGS:
        command = [str(args.root / "runtime-b11221/llama-mtmd-cli.exe"),
                   "-m", str(args.root / "models/Qwen3VL-4B-Instruct-Q4_K_M.gguf"),
                   "--mmproj", str(args.root / "models/mmproj-Qwen3VL-4B-Instruct-F16.gguf"),
                   "--image", str(image_path), "-p", "Read the reference.", "-n", "1",
                   "-c", "4096", "-ngl", "99", "-fa", "on", "-ctk", config["kv"], "-ctv", config["kv"],
                   "-b", "512", "-ub", "128", "--image-min-tokens", "128", "--image-max-tokens", str(config["image_tokens"]),
                   "--fit", "off", "--no-warmup"]
        if config["vision"] == "cpu":
            command.append("--no-mmproj-offload")
        begin = time.monotonic()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        monitor = Resources(process)
        monitor.start()
        timed_out = False
        try:
            raw, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            raw, _ = process.communicate()
            timed_out = True
        finally:
            monitor.stop()
        decoded = raw.decode("utf-8", "replace")
        durations = [float(number) for number in re.findall(r"(?:image slice encoded|mtmd batch encoding done) in\s+([\d.]+)\s+ms", decoded)]
        entry = {"configuration": config, "exit_code": process.returncode,
                 "timeout": timed_out, "total_command_s": time.monotonic() - begin,
                 "image_encoding_ms": durations, "input_sha256": image["sha256"], "resources": monitor.snapshot()}
        report["measurements"].append(entry)
        print(json.dumps({"id": config["id"], "encoding_ms": durations, "exit": process.returncode}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(m["exit_code"] == 0 and m["image_encoding_ms"] for m in report["measurements"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
