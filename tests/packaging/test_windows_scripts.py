"""Read-only packaging checks; never register a task, grant ACLs, or call Telegram."""
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows packaging checks")
ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def native_environment():
    # A PowerShell 7 parent can prepend modules incompatible with Windows PS 5.1.
    return {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}


def invoke(script, *args):
    return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(ROOT / "deploy/windows" / script), *map(str, args)],
                          capture_output=True, text=True, timeout=30, env=native_environment())


def account():
    return os.environ["COMPUTERNAME"] + "\\" + os.environ["USERNAME"]


def roots(tmp_path):
    result = []
    for flag, name in (("-AppRoot", "app"), ("-PythonRoot", "python"),
                       ("-ConfigDirectory", "config"), ("-DataRoot", "data")):
        path = tmp_path / name
        path.mkdir()
        (path / "synthetic.txt").write_text("keep", encoding="utf-8")
        result.extend((flag, path))
    return result


def test_acl_dry_run_builds_private_plan_without_changing_access(tmp_path):
    args = roots(tmp_path)
    before = subprocess.check_output([str(POWERSHELL), "-NoProfile", "-Command",
                                      "(Get-Acl -LiteralPath '" + str(tmp_path / "app") + "').Sddl"],
                                     text=True, env=native_environment())
    result = invoke("secure-directories.ps1", *args, "-BotAccount", account())
    assert result.returncode == 0, result.stderr
    assert "Preflight entries: 8" in result.stdout and "Dry run complete" in result.stdout
    assert "bot=ReadAndExecute" in result.stdout and "bot=Modify" in result.stdout
    after = subprocess.check_output([str(POWERSHELL), "-NoProfile", "-Command",
                                     "(Get-Acl -LiteralPath '" + str(tmp_path / "app") + "').Sddl"],
                                    text=True, env=native_environment())
    assert before == after and (tmp_path / "data/synthetic.txt").read_text() == "keep"


@pytest.mark.parametrize("unsafe", ["overlap", "relative", "profile"])
def test_acl_plan_refuses_unsafe_roots(tmp_path, unsafe):
    args = roots(tmp_path)
    if unsafe == "overlap":
        args[3] = args[1]
    elif unsafe == "relative":
        args[1] = "relative-path"
    else:
        args[1] = Path(os.environ["USERPROFILE"])
    result = invoke("secure-directories.ps1", *args, "-BotAccount", account())
    assert result.returncode != 0
    assert (tmp_path / "data/synthetic.txt").read_text() == "keep"


def test_task_dry_run_has_direct_supervised_python_action(tmp_path):
    config = tmp_path / "synthetic.env"
    config.write_text("synthetic; not read during task dry run", encoding="utf-8")
    result = invoke("install-bot-task.ps1", "-ConfigPath", config, "-UserId", account())
    assert result.returncode == 0, result.stderr
    assert "--restart-on-failure" in result.stdout and ".venv\\Scripts\\python.exe" in result.stdout
    assert "run-bot.ps1" not in result.stdout and "Dry run complete; nothing was registered" in result.stdout


def test_dry_run_refuses_mutating_startup_check(tmp_path):
    config = tmp_path / "synthetic.env"
    config.write_text("not a configuration", encoding="utf-8")
    result = invoke("install-bot-task.ps1", "-ConfigPath", config, "-UserId", account(), "-RunCheck")
    assert result.returncode != 0 and "requires -Apply" in result.stderr
    assert not (tmp_path / "logs").exists() and not (tmp_path / "temporary").exists()
