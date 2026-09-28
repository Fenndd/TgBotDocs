"""Local command entry point. The check command makes no Telegram requests."""

import argparse
import asyncio
import os
from pathlib import Path

from .application.bootstrap import check_configuration
from .application.config import ConfigurationError
from .application.lifecycle import LifecycleError
from .recognition.adapter import ModelError
from .recognition.config import ConfigError
from .storage import StorageUnavailable


def main():
    parser = argparse.ArgumentParser(prog="tgbotdocs")
    parser.add_argument("action", choices=("check",))
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    source = args.config or Path(os.environ.get("TGBOTDOCS_CONFIG", ""))
    try:
        print(asyncio.run(check_configuration(source)))
    except KeyboardInterrupt:
        return 0
    except (ConfigurationError, LifecycleError, ModelError, ConfigError, StorageUnavailable) as error:
        print("local_application_failed: " + str(error))
        return 1
    except Exception:
        # No raw dependency exception, URL, SQL, update, prompt, or response.
        print("local_application_failed; check configuration and local dependencies")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
