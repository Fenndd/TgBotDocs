"""Own one pinned local llama-server process; never reuse an unrelated listener."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile

import httpx

from .adapter import AdapterSettings, ModelError


@dataclass(frozen=True)
class RuntimeFiles:
    executable: Path
    model: Path
    projector: Path
    executable_sha256: str = "32f5394d0bd75ce90bcc15edb7a638e05b659d0f532313c65dc3401d1f521575"
    model_sha256: str = "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"
    projector_sha256: str = "256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331"

    def verify(self):
        for path, digest in (
            (self.executable, self.executable_sha256),
            (self.model, self.model_sha256),
            (self.projector, self.projector_sha256),
        ):
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ModelError("runtime_artifact_hash_mismatch")
        if not self.executable.is_file():
            raise ModelError("runtime_executable_missing")


@dataclass(frozen=True)
class RuntimeProfile:
    context_tokens: int = 4096
    image_min_tokens: int = 128
    image_max_tokens: int = 1024
    output_tokens: int = 1024
    pdf_dpi: int = 150
    alternative_pdf_dpi: int = 200
    vision_gpu: bool = True
    cache_type: str = "q8_0"

    def __post_init__(self):
        if (
            self.context_tokens < 512
            or not 1 <= self.output_tokens < self.context_tokens
            or not 1 <= self.image_min_tokens <= self.image_max_tokens
            or self.pdf_dpi <= 0
            or self.alternative_pdf_dpi <= 0
            or self.cache_type not in ("f16", "q8_0")
        ):
            raise ValueError("Invalid runtime profile")


class WindowsJob:
    """Kernel-owned kill-on-close job; its handle is never inherited by children."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ModelError("runtime_job_creation_failed")
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ModelError("runtime_job_configuration_failed")

    def assign(self, pid):
        process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ModelError("runtime_process_binding_failed")
        try:
            if not self.api.AssignProcessToJobObject(self.handle, process):
                raise ModelError("runtime_job_assignment_failed")
        finally:
            self.api.CloseHandle(process)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class LocalRuntime:
    def __init__(self, files: RuntimeFiles, profile: RuntimeProfile, *, port=18081, start_timeout_s=60.0):
        if (
            type(port) is not int
            or not 1 <= port <= 65535
            or not math.isfinite(start_timeout_s)
            or start_timeout_s <= 0
        ):
            raise ValueError("Invalid runtime port or startup deadline")
        self.files, self.profile, self.port = files, profile, port
        self.start_timeout_s = start_timeout_s
        self._process = None
        self._key_file = None
        self._job = None
        self._key = secrets.token_urlsafe(32)
        self._verified = False
        self._lifecycle = asyncio.Lock()

    @property
    def adapter_settings(self):
        return AdapterSettings(endpoint=f"http://127.0.0.1:{self.port}", api_key=self._key)

    async def start(self):
        async with self._lifecycle:
            await self._start()

    async def _start(self):
        if self._process is not None:
            raise ModelError("runtime_already_started")
        if not self._verified:
            await asyncio.to_thread(self.files.verify)
            self._verified = True
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", self.port))
            except OSError:
                raise ModelError("runtime_port_in_use") from None
        key_file = tempfile.NamedTemporaryFile("w", prefix="tgbotdocs-runtime-key-", delete=False)
        self._key_file = Path(key_file.name)
        with key_file:
            key_file.write(self._key)
        p = self.profile
        command = [
            str(self.files.executable),
            "--model",
            str(self.files.model),
            "--mmproj",
            str(self.files.projector),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--api-key-file",
            str(self._key_file),
            "--parallel",
            "1",
            "--ctx-size",
            str(p.context_tokens),
            "--n-gpu-layers",
            "99",
            "--batch-size",
            "512",
            "--ubatch-size",
            "128",
            "--flash-attn",
            "on",
            "--cache-type-k",
            p.cache_type,
            "--cache-type-v",
            p.cache_type,
            "--image-min-tokens",
            str(p.image_min_tokens),
            "--image-max-tokens",
            str(p.image_max_tokens),
            "--cache-ram",
            "0",
            "--no-webui",
            "--slots",
            "--log-verbosity",
            "1",
            "--fit",
            "off",
            "--no-warmup",
        ]
        if not p.vision_gpu:
            command.append("--no-mmproj-offload")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("LLAMA_", "HF_", "HUGGING_FACE_"))
        }
        try:
            if os.name == "nt":
                self._job = WindowsJob()
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            )
            try:
                self._process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                self._process = await _complete(spawn)
                raise
            if self._job:
                self._job.assign(self._process.pid)
            async with httpx.AsyncClient(trust_env=False) as client:
                async with asyncio.timeout(self.start_timeout_s):
                    while True:
                        if self._process.returncode is not None:
                            raise ModelError("runtime_start_failed")
                        try:
                            response = await client.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                            health = response.json()
                            if (
                                response.status_code == 200
                                and isinstance(health, dict)
                                and health.get("status") == "ok"
                            ):
                                return
                        except httpx.HTTPError, ValueError:
                            pass
                        await asyncio.sleep(0.1)
        except BaseException:
            await _complete(asyncio.create_task(self._stop()))
            raise

    async def stop(self):
        async def locked_stop():
            async with self._lifecycle:
                await self._stop()

        task = asyncio.create_task(locked_stop())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        task.result()
        if interrupted:
            raise asyncio.CancelledError

    async def _stop(self):
        try:
            if self._job:
                self._job.close()
                self._job = None
            if self._process:
                if self._process.returncode is None:
                    try:
                        self._process.terminate()
                    except ProcessLookupError:
                        pass
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()
                self._process = None
        finally:
            if self._key_file:
                self._key_file.unlink(missing_ok=True)
                self._key_file = None

    async def restart(self):
        async with self._lifecycle:
            await _complete(asyncio.create_task(self._stop()), propagate_cancel=True)
            await self._start()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.stop()


async def _complete(task, *, propagate_cancel=False):
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    result = task.result()
    if interrupted and propagate_cancel:
        raise asyncio.CancelledError
    return result
