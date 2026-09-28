"""Read-only PostgreSQL service packaging checks using synthetic scratch trees."""
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows ACL planning")
ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
SCRIPT = ROOT / "deploy/windows/postgresql-service.ps1"


def environment():
    return {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}


def powershell(command, temporary_root=None):
    env = environment()
    if temporary_root is not None:
        # PS5.1 Add-Type can use the compiler's temporary directory.
        env.update(TEMP=str(temporary_root), TMP=str(temporary_root))
    return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, timeout=30, env=env)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def invoke(root, action="Register"):
    return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(SCRIPT), "-Action", action, "-DataRoot", str(root),
                           "-ServiceName", "TgBotDocsReadonlyPackagingCheck"],
                          capture_output=True, text=True, timeout=30, env=environment())


def trees(tmp_path):
    distribution = tmp_path / "postgresql-18.6"
    (distribution / "pgsql/bin").mkdir(parents=True)
    # No pg_ctl.exe exists: the test cannot execute PostgreSQL.
    (distribution / "pgsql/bin/synthetic.txt").write_text("public synthetic")
    cluster = tmp_path / "postgresql-dev-cluster"
    cluster.mkdir()
    (cluster / "PG_VERSION").write_text("18")
    (cluster / "synthetic.txt").write_text("public synthetic")
    (tmp_path / "postgresql-dev-credentials.json").write_text("synthetic; must not be read")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep")
    return distribution, cluster


def snapshot(root):
    result = powershell("$items=@(Get-Item -LiteralPath " + quote(root) + "); "
                        "$items += @(Get-ChildItem -LiteralPath " + quote(root) + " -Force -Recurse); "
                        "@($items | ForEach-Object { [pscustomobject]@{ "
                        "Path=$_.FullName; Sddl=(Get-Acl -LiteralPath $_.FullName).Sddl } }) | "
                        "ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def dacl(sddl):
    result = powershell("$acl=New-Object Security.AccessControl.DirectorySecurity; "
                        "$acl.SetSecurityDescriptorSddlForm(" + quote(sddl) + "); "
                        "[pscustomobject]@{Protected=$acl.AreAccessRulesProtected; "
                        "Rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | "
                        "ForEach-Object {[pscustomobject]@{Sid=$_.IdentityReference.Value; "
                        "Rights=$_.FileSystemRights.ToString(); Inherited=$_.IsInherited}})} | "
                        "ConvertTo-Json -Depth 4 -Compress")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("action", ["Register", "Unregister"])
def test_private_plan_has_exact_principals_and_never_changes_scratch_acl(tmp_path, action):
    trees(tmp_path)
    before = snapshot(tmp_path)
    result = invoke(tmp_path, action)
    assert result.returncode == 0, result.stderr
    assert "Dry run complete; nothing was changed." in result.stdout
    assert "Private ACL plan entries: 7;" in result.stdout
    installer_line = next(line for line in result.stdout.splitlines() if line.startswith("Private ACL plan entries:"))
    installer = installer_line.split("installing user=")[1]
    expected = {"S-1-5-18", "S-1-5-32-544", installer}
    if action == "Register":
        expected.add("S-1-5-20")
    for role, rights in [("distribution", "ReadAndExecute"), ("cluster", "Modify")]:
        line = next(line for line in result.stdout.splitlines() if line.startswith("Private DACL " + role + ":"))
        plan = dacl(line.split(": ", 1)[1])
        assert plan["Protected"]
        assert {rule["Sid"] for rule in plan["Rules"]} == expected
        assert all(not rule["Inherited"] for rule in plan["Rules"])
        for rule in plan["Rules"]:
            assert (rights if rule["Sid"] == "S-1-5-20" else "FullControl") in rule["Rights"]
    assert snapshot(tmp_path) == before
    assert (tmp_path / "postgresql-dev-credentials.json").read_text() == "synthetic; must not be read"
    assert (tmp_path / "unrelated/keep.txt").read_text() == "keep"


@pytest.mark.parametrize("kind", ["relative", "profile", "drive", "virtualized"])
def test_unsafe_root_refused_before_plan(tmp_path, kind):
    root = {"relative": "relative", "profile": os.environ["USERPROFILE"],
            "drive": Path(tmp_path.anchor), "virtualized": tmp_path / "AppData/Local/fixture"}[kind]
    result = invoke(root)
    assert result.returncode != 0
    assert "Private ACL plan entries:" not in result.stdout


def test_refreshed_private_plan_includes_new_cluster_file_without_service_access(tmp_path):
    distribution, cluster = trees(tmp_path)
    # Load only the planning function's complete AST definition. No main-script Apply,
    # service command, native executable or Set-Acl is invoked.
    result = powershell(
        "$tokens=$null; $parseErrors=$null; $ast=[System.Management.Automation.Language.Parser]::ParseFile("
        + quote(SCRIPT) + ",[ref]$tokens,[ref]$parseErrors); "
        "$node=$ast.Find({param($item) $item -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $item.Name -eq 'New-PrivateAclPlan'},$true); . ([ScriptBlock]::Create($node.Extent.Text)); "
        "$systemSid=[Security.Principal.SecurityIdentifier]'S-1-5-18'; "
        "$adminsSid=[Security.Principal.SecurityIdentifier]'S-1-5-32-544'; "
        "$serviceSid=[Security.Principal.SecurityIdentifier]'S-1-5-20'; "
        "$installerSid=[Security.Principal.WindowsIdentity]::GetCurrent().User; "
        "$roles=@(@{Path=" + quote(distribution) + ";Rights='ReadAndExecute'}, "
        "@{Path=" + quote(cluster) + ";Rights='Modify'}); "
        "$first=New-PrivateAclPlan -Roles $roles -IncludeService $false; "
        "[IO.File]::WriteAllText(" + quote(cluster / "created-after-first-plan.txt") + ",'synthetic'); "
        "$second=New-PrivateAclPlan -Roles $roles -IncludeService $false; "
        "$serviceRules=@($second | ForEach-Object { $_.Acl.GetAccessRules($true,$true,"
        "[Security.Principal.SecurityIdentifier]) | Where-Object {$_.IdentityReference.Value -eq 'S-1-5-20'}}); "
        "[pscustomobject]@{First=$first.Count; Second=$second.Count; ServiceRules=$serviceRules.Count} | "
        "ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"First": 7, "Second": 8, "ServiceRules": 0}


@pytest.mark.parametrize("location", ["cluster_root", "distribution_child", "ancestor"])
def test_reparse_point_refused_before_native_execution_or_permissions(tmp_path, location):
    distribution, cluster = trees(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "PG_VERSION").write_text("18")
    before = snapshot(external)
    if location == "cluster_root":
        # Empty only the fixture folder created by this test; no shared data.
        (cluster / "PG_VERSION").unlink()
        (cluster / "synthetic.txt").unlink()
        cluster.rmdir()
        link, target = cluster, external
        root = tmp_path
    elif location == "distribution_child":
        link, target = distribution / "linked", external
        root = tmp_path
    else:
        link, target = tmp_path / "linked-root", tmp_path
        root = link
    # A directory junction needs no elevated symlink privilege. Only scratch is changed.
    created = powershell("New-Item -ItemType Junction -Path " + quote(link) + " -Target " + quote(target) + " | Out-Null")
    assert created.returncode == 0, created.stderr
    result = invoke(root)
    assert result.returncode != 0 and "Reparse points are forbidden" in result.stderr
    assert "Private ACL plan entries:" not in result.stdout
    assert snapshot(external) == before

def identity_functions():
    names = ["ConvertFrom-WindowsServiceCommandLine", "Get-CanonicalServicePath", "Assert-OwnedServiceIdentity"]
    return ("$tokens=$null; $parseErrors=$null; $ast=[System.Management.Automation.Language.Parser]::ParseFile("
            + quote(SCRIPT) + ",[ref]$tokens,[ref]$parseErrors); "
            "foreach($name in @(" + ",".join(quote(name) for name in names) + ")) { "
            "$node=$ast.Find({param($item) $item -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $item.Name -eq $name},$true); "
            ". ([ScriptBlock]::Create($node.Extent.Text)) }; ")


@pytest.mark.parametrize("case,accepted", [
    ("matching", True), ("canonical", True), ("opaque_o_text", True),
    ("foreign_executable", False), ("foreign_cluster", False), ("foreign_account", False),
    ("foreign_name", False), ("missing_identity", False), ("missing_path", False),
    ("wrong_command", False), ("missing_D", False), ("missing_D_value", False),
    ("duplicate_D", False), ("duplicate_N", False), ("embedded_D_only", False),
    ("foreign_D_with_embedded_matching_D", False), ("backend_D_override", False),
    ("unknown_option", False), ("unbalanced_quotes", False),
])
def test_service_identity_requires_exact_owned_argv_and_network_service(tmp_path, case, accepted):
    name = "TgBotDocsReadonlyPackagingCheck"
    exe = str(tmp_path / "data with spaces/postgresql-18.6/pgsql/bin/pg_ctl.exe")
    cluster = str(tmp_path / "data with spaces/postgresql-dev-cluster")
    argv = [exe, "runservice", "-N", name, "-D", cluster, "-w",
            "-o", "-h 127.0.0.1 -p 55432"]
    account = "NT AUTHORITY\\NetworkService"
    identity_name = name
    if case == "canonical":
        argv[0] = str(Path(exe).parent / "." / "pg_ctl.exe").upper()
        argv[5] = cluster + "\\."
    elif case == "opaque_o_text":
        argv[-1] = "-c log_line_prefix=literal-D-value"
    elif case == "foreign_executable":
        argv[0] = str(tmp_path / "other/pg_ctl.exe")
    elif case == "foreign_cluster":
        argv[5] = str(tmp_path / "other cluster")
    elif case == "foreign_account":
        account = "NT AUTHORITY\\SYSTEM"
    elif case == "foreign_name":
        identity_name = "ForeignService"
    elif case == "wrong_command":
        argv[1] = "start"
    elif case == "missing_D":
        del argv[4:6]
    elif case == "missing_D_value":
        argv = argv[:4] + ["-D"]
    elif case == "duplicate_D":
        argv += ["-D", cluster]
    elif case == "duplicate_N":
        argv += ["-N", name]
    elif case == "embedded_D_only":
        del argv[4:6]
        argv[-1] = "-D " + subprocess.list2cmdline([cluster])
    elif case == "foreign_D_with_embedded_matching_D":
        argv[5] = str(tmp_path / "other cluster")
        argv[-1] = "-D " + subprocess.list2cmdline([cluster])
    elif case == "backend_D_override":
        argv[-1] = "-D " + subprocess.list2cmdline([str(tmp_path / "other cluster")])
    elif case == "unknown_option":
        argv += ["--pgdata", cluster]
    command_line = subprocess.list2cmdline(argv)
    if case == "missing_path":
        command_line = ""
    elif case == "unbalanced_quotes":
        command_line += ' "unfinished'
    identity = ("[pscustomobject]@{Name=" + quote(identity_name) + ";StartName=" + quote(account)
                + ";PathName=" + quote(command_line) + "}")
    if case == "missing_identity":
        identity = "$null"
    # Only read-only helper functions run; no actual SCM query or main-script Apply.
    result = powershell(identity_functions() + "try { Assert-OwnedServiceIdentity -Identity (" + identity
                        + ") -Executable " + quote(exe) + " -ClusterPath " + quote(cluster)
                        + " -Name " + quote(name) + "; 'accepted' } catch { 'rejected' }", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("accepted" if accepted else "rejected"), result.stdout + result.stderr


def test_unregister_dry_run_rejects_service_from_other_root_before_any_plan_or_mutation(tmp_path):
    _, cluster = trees(tmp_path)
    before = snapshot(tmp_path)
    name = "TgBotDocsReadonlyPackagingCheck"
    foreign_root = tmp_path / "foreign data root"
    command_line = subprocess.list2cmdline([
        str(foreign_root / "postgresql-18.6/pgsql/bin/pg_ctl.exe"),
        "runservice", "-N", name, "-D", str(foreign_root / "postgresql-dev-cluster")])
    # All SCM/mutation commands are synthetic functions in this child process.
    # The real script runs without Apply and must fail before publishing its plan.
    command = (
        "function Get-Service { [CmdletBinding()] param([string]$Name) "
        "[pscustomobject]@{Name=$Name;Status='Running';StartType='Automatic'} }; "
        "function Get-CimInstance { [CmdletBinding()] param([string]$ClassName,[string]$Filter) "
        "[pscustomobject]@{Name=" + quote(name) + ";StartName='NT AUTHORITY\\NetworkService';PathName="
        + quote(command_line) + "} }; "
        "function Stop-Service { throw 'MUTATION_REQUESTED' }; "
        "function Set-Acl { throw 'MUTATION_REQUESTED' }; "
        "& " + quote(SCRIPT) + " -Action Unregister -DataRoot " + quote(tmp_path)
        + " -ServiceName " + quote(name))
    result = powershell(command, tmp_path)
    assert result.returncode != 0
    assert "does not match this installation" in result.stderr
    assert "Private ACL plan entries:" not in result.stdout
    assert "MUTATION_REQUESTED" not in result.stderr
    assert snapshot(tmp_path) == before
    assert (cluster / "synthetic.txt").read_text() == "public synthetic"


