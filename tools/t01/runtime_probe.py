"""Exploratory T01a measurements, never an acceptance benchmark or product runtime.

Only generated synthetic fixtures are permitted. Responses and runtime logs stay
in memory; persisted JSON contains resource/timing/contract/legibility metrics.
Run one probe process at a time. The server is owned and terminated by this run.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time
import sys

import httpx
from jsonschema import validate
from PIL import Image, ImageDraw, ImageFont
import psutil


SCHEMA = {
    "type": "object",
    "properties": {
        "reference": {"type": "string"},
        "amount": {"type": "string"},
    },
    "required": ["reference", "amount"],
    "additionalProperties": False,
}
EXPECTED = {"reference": "SYN-047291", "amount": "125.80"}


def synthetic_page(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", max(22, width // 32))
    for i, line in enumerate(
        ["SYNTHETIC TEST INVOICE", "Reference: SYN-047291", "Amount: 125.80", "No real transaction"]
    ):
        draw.text((width // 12, height // 8 + i * height // 10), line, font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    return buffer.getvalue()


class Resources:
    """Sample total GPU memory and this server's process memory separately."""

    def __init__(self, process: subprocess.Popen):
        self.process = process
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.rows: list[dict] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.done.is_set():
            try:
                p = psutil.Process(self.process.pid)
                mem = p.memory_info()
                gpu = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                values = [float(v.strip()) for v in gpu.stdout.strip().split(",")]
                row = {"time": time.monotonic(), "server_rss_mib": mem.rss / 2**20,
                       "server_private_mib": getattr(mem, "private", mem.vms) / 2**20,
                       "system_available_mib": psutil.virtual_memory().available / 2**20,
                       "gpu_total_used_mib": values[0], "gpu_capacity_mib": values[1]}
                with self.lock:
                    self.rows.append(row)
            except (psutil.Error, OSError, ValueError, subprocess.TimeoutExpired):
                pass
            self.done.wait(0.5)

    def start(self):
        self.thread.start()

    def snapshot(self, since=0.0):
        with self.lock:
            rows = [row for row in self.rows if row["time"] >= since]
        if not rows:
            return {"samples": 0}
        return {"samples": len(rows),
                "server_peak_rss_mib": max(x["server_rss_mib"] for x in rows),
                "server_peak_private_mib": max(x["server_private_mib"] for x in rows),
                "system_min_available_mib": min(x["system_available_mib"] for x in rows),
                "gpu_peak_total_used_mib": max(x["gpu_total_used_mib"] for x in rows),
                "gpu_capacity_mib": rows[0]["gpu_capacity_mib"]}

    def stop(self):
        self.done.set()
        self.thread.join(timeout=6)


class Runtime:
    def __init__(self, root: Path, config: dict, port: int):
        self.root, self.config, self.port = root, config, port
        self.process = None
        self.metrics = None
        self.client = None
        self.log_events = []
        self.key_file = None
        self.key = secrets.token_urlsafe(32)
        self.ready_for_request = True

    def start(self) -> float:
        executables = list((self.root / "runtime-b11221").rglob("llama-server.exe"))
        if len(executables) != 1:
            raise RuntimeError("Expected one pinned llama-server executable")
        # Refuse to attach accidentally to somebody else's local service.
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", self.port))
        key = tempfile.NamedTemporaryFile(mode="w", prefix="t01-key-", delete=False)
        self.key_file = Path(key.name)
        with key:
            key.write(self.key)
        cfg = self.config
        args = [str(executables[0]), "--model", str(self.root / "models/Qwen3VL-4B-Instruct-Q4_K_M.gguf"),
                "--mmproj", str(self.root / "models/mmproj-Qwen3VL-4B-Instruct-F16.gguf"),
                "--host", "127.0.0.1", "--port", str(self.port), "--api-key-file", str(self.key_file),
                "--parallel", "1", "--ctx-size", str(cfg["context"]), "--n-gpu-layers", str(cfg.get("gpu_layers", 99)),
                "--batch-size", "512", "--ubatch-size", "128", "--flash-attn", "on",
                "--cache-type-k", cfg["kv"], "--cache-type-v", cfg["kv"],
                "--image-min-tokens", "128", "--image-max-tokens", str(cfg["image_tokens"]),
                "--cache-ram", "0", "--no-webui", "--slots", "--log-verbosity", "3",
                "--no-warmup", "--fit", "off"]
        if cfg["vision"] == "cpu":
            args.append("--no-mmproj-offload")
        begin = time.monotonic()
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.metrics = Resources(self.process)
        self.metrics.start()

        def consume():
            # Never persist raw server lines. Only allowlisted numeric timings
            # and diagnostics are retained; even synthetic response text is discarded.
            for raw in self.process.stdout:
                line = raw.decode("utf-8", "replace")
                if "image" in line.lower() and (" ms" in line or "tokens" in line):
                    numbers = re.findall(r"\d+(?:\.\d+)?", line)
                    self.log_events.append({"kind": "image_runtime_numbers", "numbers": numbers})
                if any(word in line.lower() for word in ("out of memory", "cuda error", "failed to allocate")):
                    self.log_events.append({"kind": "allocation_error"})

        self.log_thread = threading.Thread(target=consume, daemon=True)
        self.log_thread.start()
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.port}",
                                   headers={"Authorization": f"Bearer {self.key}"}, timeout=300, trust_env=False)
        while time.monotonic() - begin < 180:
            if self.process.poll() is not None:
                raise RuntimeError(f"server_exit_{self.process.returncode}")
            try:
                if self.client.get("/health", timeout=1).status_code == 200:
                    return time.monotonic() - begin
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise TimeoutError("server_health_timeout")

    def idle(self, timeout=10.0):
        begin = time.monotonic()
        while time.monotonic() - begin < timeout:
            try:
                response = self.client.get("/slots", timeout=min(1.0, timeout))
                if response.status_code == 200:
                    slots = response.json()
                    if isinstance(slots, list) and len(slots) == 1 and slots[0].get("is_processing") is False:
                        return {"confirmed": True, "release_s": time.monotonic() - begin}
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.05)
        return {"confirmed": False, "release_s": time.monotonic() - begin}

    def request(self, images, schema=SCHEMA, instruction=None, expected=None, max_tokens=1024,
                cancel_after_chunks=None, read_timeout=300.0, evaluate=None):
        if not self.ready_for_request:
            raise RuntimeError("Previous slot release unconfirmed; restart is required")
        self.ready_for_request = False
        begin = time.monotonic()
        body = {"messages": [{"role": "system", "content": "Read the supplied synthetic document images. Return only the requested JSON. Copy values exactly; do not translate."},
                             {"role": "user", "content": [
                                 *[{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}} for b in images],
                                 {"type": "text", "text": instruction or "Return reference and amount from the invoice. Amount is a decimal string."}]}],
                "temperature": 0, "seed": 42, "max_tokens": max_tokens, "stream": True,
                "cache_prompt": False, "logprobs": True, "top_logprobs": 5,
                "post_sampling_probs": False,
                "response_format": {"type": "json_schema", "json_schema": {"name": "probe", "strict": True, "schema": schema}}}
        chunks, probabilities, timings, finish = [], [], None, None
        first_token = None
        timed_out, cancelled, timeout_type = False, False, None
        try:
            with self.client.stream("POST", "/v1/chat/completions", json=body, timeout=read_timeout) as response:
                if response.status_code != 200:
                    response.read()
                    slot = self.idle()
                    self.ready_for_request = slot["confirmed"]
                    return {"http_status": response.status_code, "ok": False, "slot": slot,
                            "duration_s": time.monotonic() - begin, "resources": self.metrics.snapshot(begin)}
                for line in response.iter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    timings = event.get("timings", timings)
                    for choice in event.get("choices", []):
                        content = choice.get("delta", {}).get("content")
                        if content:
                            first_token = first_token or time.monotonic()
                            chunks.append(content)
                        logprobs = choice.get("logprobs") or {}
                        for token in logprobs.get("content", []):
                            probabilities.append(token.get("logprob"))
                        finish = choice.get("finish_reason") or finish
                    if cancel_after_chunks and len(chunks) >= cancel_after_chunks:
                        cancelled = True
                        break
        except httpx.TimeoutException as error:
            timed_out = True
            timeout_type = type(error).__name__
        text = "".join(chunks)
        valid, matches, parse_failure, evaluation = False, None, False, None
        if not (cancelled or timed_out):
            try:
                parsed = json.loads(text)
                validate(parsed, schema)
                valid = True
                if expected is not None:
                    matches = parsed == expected
                if evaluate is not None:
                    evaluation = evaluate(parsed)
            except (ValueError, __import__("jsonschema").ValidationError):
                parse_failure = True
        result = {"ok": valid, "schema_valid": valid, "exact_match": matches,
                  "parse_or_contract_error": parse_failure, "finish_reason": finish,
                  "cancelled": cancelled, "timed_out": timed_out,
                  "timeout_type": timeout_type, "received_content_chunks": len(chunks),
                  "duration_s": time.monotonic() - begin,
                  "first_token_s": first_token - begin if first_token else None,
                  "probability_count": len(probabilities),
                  "all_probabilities_numeric": bool(probabilities) and all(isinstance(p, (int, float)) for p in probabilities),
                  "nonzero_raw_logprob_count": sum(isinstance(p, (int, float)) and p < 0 for p in probabilities),
                  "timings": timings, "resources": self.metrics.snapshot(begin)}
        result["evaluation"] = evaluation
        prompt_tokens = timings.get("prompt_n", 0) + timings.get("cache_n", 0) if timings else None
        result["reserved_output_tokens"] = max_tokens
        result["output_reserve_fits_context"] = (prompt_tokens + max_tokens <= self.config["context"]) if prompt_tokens is not None else None
        result["image_encoding_s"] = None
        result["image_encoding_note"] = "Server prompt_ms combines vision encoding and prompt evaluation; separate duration unavailable in official server"
        result["slot"] = self.idle()
        self.ready_for_request = result["slot"]["confirmed"]
        return result

    def stop(self):
        begin = time.monotonic()
        if self.client:
            self.client.close()
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.metrics.stop()
            self.log_thread.join(timeout=2)
            self.process.stdout.close()
        if self.key_file:
            self.key_file.unlink(missing_ok=True)
        return time.monotonic() - begin


CONFIGS = [
    {"id": "cpu-q8-512", "vision": "cpu", "kv": "q8_0", "image_tokens": 512, "context": 4096},
    {"id": "gpu-q8-512", "vision": "gpu", "kv": "q8_0", "image_tokens": 512, "context": 4096},
    {"id": "gpu-f16-512", "vision": "gpu", "kv": "f16", "image_tokens": 512, "context": 4096},
    {"id": "cpu-f16-512", "vision": "cpu", "kv": "f16", "image_tokens": 512, "context": 4096},
    {"id": "gpu-q8-256", "vision": "gpu", "kv": "q8_0", "image_tokens": 256, "context": 4096},
    {"id": "gpu-q8-1024", "vision": "gpu", "kv": "q8_0", "image_tokens": 1024, "context": 4096},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", choices=[x["id"] for x in CONFIGS], default="cpu-q8-512")
    parser.add_argument("--mode", choices=["smoke", "matrix", "behavior", "envelope"], default="smoke")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    config = next(x for x in CONFIGS if x["id"] == args.config)
    runtime = Runtime(args.root, config, args.port)
    report = {"experiment": "T01a runtime feasibility, synthetic diagnostic only",
              "configuration": config, "mode": args.mode, "requests": [],
              "fixture_review": "pending human review; not acceptance-quality evidence"}
    try:
        report["load_s"] = runtime.start()
        print(json.dumps({"event": "loaded", "config": config["id"], "seconds": report["load_s"]}), flush=True)
        shapes = [(905, 1280)]
        if args.mode == "matrix":
            shapes = [(1240, 1754), (1654, 2339), (905, 1280), (1810, 2560)]
        for width, height in shapes:
            result = runtime.request([synthetic_page(width, height)], expected=EXPECTED)
            result.update({"kind": "single_image", "width": width, "height": height})
            report["requests"].append(result)
            print(json.dumps(result), flush=True)
        if args.mode == "behavior":
            long_schema = {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"], "additionalProperties": False}
            result = runtime.request([synthetic_page(905, 1280)], schema=long_schema,
                                     instruction="Describe every visual detail in a very long description, at least 500 words.", cancel_after_chunks=8)
            result["kind"] = "cancel_generation"
            report["requests"].append(result)
            print(json.dumps(result), flush=True)
            result = runtime.request([synthetic_page(1810, 2560)], read_timeout=0.2)
            result["kind"] = "timeout_before_first_content_phase_unconfirmed"
            report["requests"].append(result)
            print(json.dumps(result), flush=True)
            report["first_runtime_resources"] = runtime.metrics.snapshot()
            report["first_runtime_numeric_events"] = runtime.log_events
            report["stop_s"] = runtime.stop()
            runtime = Runtime(args.root, config, args.port)
            report["restart_health_s"] = runtime.start()
            report["recovery_stop_and_health_s"] = report["stop_s"] + report["restart_health_s"]
            report["restart_idle"] = runtime.idle()
            result = runtime.request([synthetic_page(905, 1280)], expected=EXPECTED)
            result["kind"] = "post_restart"
            report["requests"].append(result)
        if args.mode == "envelope":
            for count in (2, 3, 4, 6, 8):
                result = runtime.request([synthetic_page(1240, 1754)] * count, expected=EXPECTED)
                result.update({"kind": "page_envelope", "pages": count, "reserved_output_tokens": 1024})
                report["requests"].append(result)
                print(json.dumps(result), flush=True)
                if not result["ok"] or not result.get("output_reserve_fits_context"):
                    break
    except Exception as error:
        # Do not persist arbitrary exception text (which can contain an HTTP body).
        report["failure_type"] = type(error).__name__
        print(json.dumps({"event": "failed", "type": type(error).__name__}), flush=True)
    finally:
        if runtime.metrics:
            report["resources"] = runtime.metrics.snapshot()
        report["runtime_numeric_events"] = runtime.log_events
        report["final_stop_s"] = runtime.stop()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 1 if "failure_type" in report else 0


if __name__ == "__main__":
    sys.exit(main())
