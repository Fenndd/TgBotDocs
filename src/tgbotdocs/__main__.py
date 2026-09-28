"""Local command entry point.

``check`` verifies cleanup, configuration, migrations and the frozen model runtime
without any Telegram request. ``run`` starts the bot: the same startup, then long
polling until stopped.
"""

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
    parser.add_argument("action", choices=("check", "run"))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--restart-on-failure", action="store_true",
                        help="retry a failed run after 60 seconds; for a local service manager")
    args = parser.parse_args()
    if args.restart_on_failure and args.action != "run":
        parser.error("--restart-on-failure is only valid with run")
    source = args.config or Path(os.environ.get("TGBOTDOCS_CONFIG", ""))
    try:
        if args.action == "run":
            from .application.service import configure_logging, serve, supervised_serve

            configure_logging(source)
            print("tgbotdocs_starting", flush=True)
            asyncio.run(supervised_serve(source) if args.restart_on_failure else serve(source))
            print("tgbotdocs_stopped", flush=True)
        else:
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
