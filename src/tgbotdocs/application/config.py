"""External configuration with content-free validation errors."""

from dataclasses import dataclass, field
import os
import math
from pathlib import Path

from dotenv import dotenv_values


class ConfigurationError(ValueError):
    pass


def startup_temporary_root(source: Path):
    """Read only paths needed for cleanup before validating DB/token settings."""
    checkout = Path(__file__).resolve().parents[3]
    if not source.is_absolute() or source.resolve().is_relative_to(checkout):
        raise ConfigurationError("configuration_must_be_external_absolute_file")
    try:
        values = dotenv_values(source, interpolate=False)
        data = Path(values["DATA_ROOT"])
        temporary = Path(values.get("TEMPORARY_ROOT") or str(data / "temporary"))
        for path in (data, temporary):
            if not path.is_absolute() or path.resolve().is_relative_to(checkout):
                raise ConfigurationError("data_path_must_be_external_absolute")
            if any(part.lower() in ("appdata", "localcache") for part in path.parts):
                raise ConfigurationError("data_path_must_not_use_virtualized_appdata")
        if not temporary.resolve().is_relative_to(data.resolve()) or temporary.resolve() == data.resolve():
            raise ConfigurationError("temporary_root_must_be_inside_data_root")
        return temporary
    except ConfigurationError:
        raise
    except (OSError, KeyError, ValueError, TypeError):
        raise ConfigurationError("configuration_invalid_or_missing") from None


@dataclass(frozen=True, repr=False)
class AppConfig:
    data_root: Path
    frozen_config: Path
    temporary_root: Path
    database_url: str = field(repr=False)
    bot_token: str = field(repr=False)
    password: str = field(repr=False)
    runtime_port: int = 18081
    operator_ids: tuple[int, ...] = ()
    inactivity_s: float = 900.0
    processing_s: float = 1800.0
    queue_timeout_s: float = 900.0
    album_quiet_s: float = 2.0
    admitted_jobs: int = 8
    download_limit: int = 2
    delivery_s: float = 60.0
    delivery_attempts: int = 3

    @classmethod
    def load(cls, path: Path | None = None):
        source = path or Path(os.environ.get("TGBOTDOCS_CONFIG", ""))
        checkout = Path(__file__).resolve().parents[3]
        if not source.is_absolute() or source.resolve().is_relative_to(checkout):
            raise ConfigurationError("configuration_must_be_external_absolute_file")
        try:
            values = dotenv_values(source, interpolate=False)
            data = Path(values["DATA_ROOT"])
            temporary = Path(values.get("TEMPORARY_ROOT") or str(data / "temporary"))
            frozen = Path(values["FROZEN_CONFIG"])
            for location in (data, temporary, frozen):
                if not location.is_absolute() or location.resolve().is_relative_to(checkout):
                    raise ConfigurationError("data_path_must_be_external_absolute")
                if any(part.lower() in ("appdata", "localcache") for part in location.parts):
                    raise ConfigurationError("data_path_must_not_use_virtualized_appdata")
            if not temporary.resolve().is_relative_to(data.resolve()) or temporary.resolve() == data.resolve():
                raise ConfigurationError("temporary_root_must_be_inside_data_root")
            token, password, database = values["BOT_TOKEN"], values["SHARED_PASSWORD"], values["DATABASE_URL"]
            if not token or ":" not in token or not token.split(":", 1)[0].isdigit():
                raise ConfigurationError("bot_token_required")
            if not password or len(password) < 16:
                raise ConfigurationError("shared_password_minimum_16_characters")
            if not database or not database.startswith("postgresql+psycopg://"):
                raise ConfigurationError("postgresql_psycopg_url_required")
            operators = tuple(int(x.strip()) for x in (values.get("OPERATOR_TELEGRAM_IDS") or "").split(",") if x.strip())
            port = int(values.get("RUNTIME_PORT") or 18081)
            if not 1 <= port <= 65535:
                raise ConfigurationError("invalid_runtime_port")
            parameters = {}
            for name, default in (("inactivity_s", 900.0), ("processing_s", 1800.0), ("queue_timeout_s", 900.0),
                                  ("album_quiet_s", 2.0), ("delivery_s", 60.0)):
                value = float(values.get(name.upper()) or default)
                if not math.isfinite(value) or value <= 0:
                    raise ConfigurationError("invalid_timer_setting")
                parameters[name] = value
            for name, default in (("admitted_jobs", 8), ("download_limit", 2), ("delivery_attempts", 3)):
                value = int(values.get(name.upper()) or default)
                if value < 1:
                    raise ConfigurationError("invalid_capacity_setting")
                parameters[name] = value
            return cls(data, frozen, temporary, database, token, password, port, operators, **parameters)
        except ConfigurationError:
            raise
        except (OSError, KeyError, ValueError, TypeError):
            raise ConfigurationError("configuration_invalid_or_missing") from None
