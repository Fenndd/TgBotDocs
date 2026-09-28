"""Local resource startup with cleanup before dependencies and polling."""

from contextlib import AsyncExitStack, asynccontextmanager
import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import json

from tgbotdocs.recognition.adapter import ModelAdapter, ModelError
from tgbotdocs.recognition.config import current_environment, environment_mismatches, load_frozen
from tgbotdocs.recognition.runner import runtime_files
from tgbotdocs.recognition.runtime import LocalRuntime
from tgbotdocs.storage import ProfileStore

from .config import AppConfig, ConfigurationError, startup_temporary_root
from .lifecycle import TemporaryLifecycle
from .instance import instance_lock
from .maintenance import cleanup_sweep, stop_task
from .scheduler import GpuScheduler, ScheduledRecognitionCore
from .supervision import supervise_children


@dataclass(repr=False)
class Resources:
    config: AppConfig
    frozen: object
    lifecycle: TemporaryLifecycle
    storage: ProfileStore
    runtime: LocalRuntime
    adapter: ModelAdapter
    scheduler: GpuScheduler

    def core(self, job_id, *, admission_order=None):
        return ScheduledRecognitionCore(self.adapter, self.frozen.core_settings(), scheduler=self.scheduler,
                                        job_id=job_id, admission_order=admission_order)


def prepare_runtime_temp(root):
    """Only remove our explicitly marked directory's runtime key leftovers."""
    directory = root / "runtime-temp"
    if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
        raise ConfigurationError("unsafe_runtime_temporary_root")
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".tgbotdocs-runtime-temp.json"
    expected = {"application": "tgbotdocs-runtime-temp-v1", "root": str(directory)}
    if marker.exists():
        if marker.is_symlink() or json.loads(marker.read_text()) != expected:
            raise ConfigurationError("unowned_runtime_temporary_root")
    else:
        if any(directory.iterdir()):
            raise ConfigurationError("unowned_runtime_temporary_root")
        marker.write_text(json.dumps(expected), encoding="utf-8")
    for path in directory.iterdir():
        if path == marker:
            continue
        if path.is_symlink() or not path.is_file() or not path.name.startswith("tgbotdocs-runtime-key-"):
            raise ConfigurationError("unowned_runtime_temporary_file")
        path.unlink()
    return directory


def configured_runtime_files(cfg, frozen):
    """Allow relocation of the calibrated executable, never a different binary."""
    files = runtime_files(cfg.data_root)
    if cfg.runtime_executable is not None:
        if cfg.runtime_executable_sha256 != frozen.runtime_artifacts.executable_sha256:
            raise ConfigurationError("runtime_executable_differs_from_frozen_recalibrate")
        files = replace(files, executable=cfg.runtime_executable,
                        executable_sha256=cfg.runtime_executable_sha256)
    return files


@asynccontextmanager
async def resources(source: Path, *, alert=None):
    temporary = startup_temporary_root(source)
    with instance_lock(temporary.parent / ".tgbotdocs-instance.lock"):
        async with _resources(source, temporary, alert=alert) as value:
            yield value


@asynccontextmanager
async def _resources(source, temporary, *, alert=None):
    lifecycle = TemporaryLifecycle(temporary, alert=alert)
    if not await lifecycle.initialize():
        raise ConfigurationError("temporary_cleanup_incomplete")
    runtime_temp = prepare_runtime_temp(lifecycle.root.parent)
    cfg = AppConfig.load(source)
    frozen, _ = load_frozen(cfg.frozen_config)
    if environment_mismatches(frozen.environment(), current_environment()):
        raise ConfigurationError("frozen_recognition_identity_mismatch_recalibrate")
    if cfg.processing_s != frozen.core.processing_budget_s:
        raise ConfigurationError("processing_budget_differs_from_frozen_configuration")
    files = configured_runtime_files(cfg, frozen)
    # Runtime keys belong to this explicit data root, never an app's redirected
    # default TEMP directory. Recognition scratch always uses owned job areas.
    previous_temp = tempfile.tempdir
    tempfile.tempdir = str(runtime_temp)
    async with AsyncExitStack() as stack:
        try:
            sweep = asyncio.create_task(cleanup_sweep(lifecycle))
            stack.push_async_callback(stop_task, sweep)
            await stack.enter_async_context(supervise_children(lifecycle))
            storage = ProfileStore(cfg.database_url)
            stack.push_async_callback(storage.close)
            await storage.migrate()
            await storage.health()
            runtime = LocalRuntime(files, frozen.runtime_profile.profile(), port=cfg.runtime_port)
            await stack.enter_async_context(runtime)
            adapter = ModelAdapter(runtime.adapter_settings, restart=runtime.restart)
            stack.push_async_callback(adapter.close)
            scheduler = GpuScheduler(cfg.queue_timeout_s)
            stack.push_async_callback(scheduler.close)
            yield Resources(cfg, frozen, lifecycle, storage, runtime, adapter, scheduler)
        finally:
            tempfile.tempdir = previous_temp


async def check_configuration(source):
    """No Telegram calls: verify cleanup, migrations, frozen model startup/stop."""
    try:
        async with resources(source):
            return "local_startup_verified"
    except (ConfigurationError, ModelError):
        raise
    except Exception:
        raise ConfigurationError("local_startup_failed") from None
