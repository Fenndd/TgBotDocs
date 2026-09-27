"""Download official T01 artifacts, verify SHA-256, then extract the runtime.

Uses curl to support restartable large downloads on the development PC.
No model hub token or other existing credential is read or needed.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

MODEL_REVISION = "1cd86afb9a95c410a6038ab3b40d8b578c892266"
ARTIFACTS = [
    (f"https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/{MODEL_REVISION}/Qwen3VL-4B-Instruct-Q4_K_M.gguf",
     "models/Qwen3VL-4B-Instruct-Q4_K_M.gguf", "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"),
    (f"https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/{MODEL_REVISION}/mmproj-Qwen3VL-4B-Instruct-F16.gguf",
     "models/mmproj-Qwen3VL-4B-Instruct-F16.gguf", "256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331"),
    ("https://github.com/ggml-org/llama.cpp/releases/download/b11221/llama-b11221-bin-win-cuda-12.4-x64.zip",
     "downloads/llama-b11221-bin-win-cuda-12.4-x64.zip", "95e15aa4f9cdcf27ea8705b6857567215dc20117ce75ff3701c51f23f6a267d1"),
    ("https://github.com/ggml-org/llama.cpp/releases/download/b11221/cudart-llama-bin-win-cuda-12.4-x64.zip",
     "downloads/cudart-llama-bin-win-cuda-12.4-x64.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
]


def prepare(root: Path):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    def download(item):
        url, relative, expected = item
        target = root / relative
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            partial = target.with_suffix(target.suffix + ".part")
            subprocess.run(["curl.exe", "--fail", "--location", "--silent", "--show-error",
                            "--retry", "3", "--continue-at", "-", "--output", str(partial), url], check=True)
            with partial.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError(f"Hash mismatch; retained for diagnosis: {partial.name}")
            partial.rename(target)
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Existing artifact hash mismatch: {target.name}")
        print(f"Verified {target.name}", flush=True)
        return {"url": url, "name": target.name, "sha256": actual, "bytes": target.stat().st_size}

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(download, ARTIFACTS))
    runtime = root / "runtime-b11221"
    runtime.mkdir(exist_ok=True)
    for _, relative, _ in ARTIFACTS:
        if relative.endswith(".zip"):
            with zipfile.ZipFile(root / relative) as archive:
                for member in archive.namelist():
                    if not (runtime / member).resolve().is_relative_to(runtime):
                        raise ValueError("Archive path escapes runtime directory")
                archive.extractall(runtime)
    (root / "artifacts.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    prepare(parser.parse_args().root)
