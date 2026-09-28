<#
.SYNOPSIS
Plans, and with -Apply performs, registration of the TgBotDocs PostgreSQL cluster as
an automatic Windows service, or its removal.

.DESCRIPTION
DRY RUN BY DEFAULT: reports the service and cluster state and prints the exact
commands. -Apply requires an elevated session.

The cluster is the one created by scripts/setup-postgres.ps1 -Action Initialize under
-DataRoot: binaries in <DataRoot>\postgresql-18.6\pgsql\bin, data directory
<DataRoot>\postgresql-dev-cluster. The service uses the same safe launch options as
setup-postgres.ps1 Start: IPv4 loopback only on -Port, no statement or parameter
logging, terse error verbosity.

Register (-Apply):
1. refuses when the service already exists or when the cluster is running (stop the
   hidden development process first with scripts/setup-postgres.ps1 -Action Stop);
2. replaces inherited/explicit permissions on only the cluster and distribution:
   SYSTEM, Administrators and the installing user keep full control; NETWORK
   SERVICE receives cluster Modify and distribution ReadAndExecute;
3. runs pg_ctl register with start type automatic (-S auto) as NETWORK SERVICE.
It does not start the service; run Start-Service afterwards.

Unregister (-Apply): stops the service if it runs (fast shutdown), runs pg_ctl
unregister, and removes NETWORK SERVICE from the same private directory trees.
Cluster data is never deleted. DataRoot/ancestor permissions and credential files
outside those two trees are not changed. Target-machine parent traversal and
effective service access must be checked separately.

Compatible with Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
.\deploy\windows\postgresql-service.ps1 -Action Register -DataRoot D:\TgBotDocsData
.\deploy\windows\postgresql-service.ps1 -Action Register -DataRoot D:\TgBotDocsData -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Register', 'Unregister')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$DataRoot,
    [ValidateRange(1, 65535)]
    [int]$Port = 55432,
    [ValidatePattern('^[A-Za-z0-9_-]{1,64}$')]
    [string]$ServiceName = 'TgBotDocsPostgreSQL',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Command failed (exit ' + $LASTEXITCODE + '): ' + [IO.Path]::GetFileName($Executable)) }
}

function ConvertFrom-WindowsServiceCommandLine([string]$CommandLine) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { throw 'Service command line is missing.' }
    if (-not ('TgBotDocs.Packaging.WindowsArgv' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
namespace TgBotDocs.Packaging {
    public static class WindowsArgv {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CommandLineToArgvW(string commandLine, out int count);
        [DllImport("kernel32.dll")]
        private static extern IntPtr LocalFree(IntPtr pointer);
        public static string[] Parse(string commandLine) {
            if (commandLine.IndexOf('\0') >= 0) throw new FormatException("Invalid service command line.");
            bool quoted = false;
            for (int i = 0; i < commandLine.Length; i++) {
                if (commandLine[i] != '"') continue;
                int slashes = 0;
                for (int j = i - 1; j >= 0 && commandLine[j] == '\\'; j--) slashes++;
                if (slashes % 2 == 0) quoted = !quoted;
            }
            if (quoted) throw new FormatException("Unbalanced service command line quotes.");
            int count;
            IntPtr memory = CommandLineToArgvW(commandLine, out count);
            if (memory == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            try {
                string[] result = new string[count];
                for (int i = 0; i < count; i++)
                    result[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory, i * IntPtr.Size));
                return result;
            } finally { LocalFree(memory); }
        }
    }
}
'@
    }
    return [TgBotDocs.Packaging.WindowsArgv]::Parse($CommandLine)
}

function Get-CanonicalServicePath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:[\\/]') { throw 'Service paths must be absolute local paths.' }
    try { return [IO.Path]::GetFullPath($Path).TrimEnd('\') }
    catch { throw 'Service path cannot be canonicalized.' }
}

function Assert-OwnedServiceIdentity([object]$Identity, [string]$Executable, [string]$ClusterPath, [string]$Name) {
    if ($null -eq $Identity -or $Identity.Name -ine $Name -or [string]::IsNullOrWhiteSpace($Identity.StartName)) {
        throw 'Service identity is missing or foreign.'
    }
    try {
        $accountSid = (New-Object Security.Principal.NTAccount($Identity.StartName)).Translate([Security.Principal.SecurityIdentifier]).Value
    } catch { throw 'Service account cannot be verified.' }
    if ($accountSid -ne 'S-1-5-20') { throw 'Service does not run as NETWORK SERVICE.' }
    $argv = @(ConvertFrom-WindowsServiceCommandLine $Identity.PathName)
    if ($argv.Count -lt 2 -or $argv[1] -cne 'runservice' -or
        (Get-CanonicalServicePath $argv[0]) -ine (Get-CanonicalServicePath $Executable)) {
        throw 'Service executable or runservice command does not match this installation.'
    }
    $values = @{}
    $seen = @{}
    for ($i = 2; $i -lt $argv.Count; $i++) {
        $flag = $argv[$i]
        # Only the spelling emitted by pg_ctl register is accepted. Do not let
        # an embedded flag in an -o value masquerade as an outer option.
        if ($flag -cnotin @('-N', '-D', '-o', '-e', '-t', '-w', '-s') -or $seen.ContainsKey($flag)) {
            throw 'Service command arguments are unknown or ambiguous.'
        }
        $seen[$flag] = $true
        if ($flag -cin @('-w', '-s')) { continue }
        $i++
        if ($i -ge $argv.Count -or [string]::IsNullOrEmpty($argv[$i])) { throw 'Service command argument is missing.' }
        $values[$flag] = $argv[$i]
        if ($flag -ceq '-t' -and $argv[$i] -notmatch '^[0-9]+$') { throw 'Service timeout argument is invalid.' }
    }
    if (-not $values.ContainsKey('-D') -or -not $values.ContainsKey('-N') -or $values['-N'] -ine $Name -or
        (Get-CanonicalServicePath $values['-D']) -ine (Get-CanonicalServicePath $ClusterPath)) {
        throw 'Service cluster or name does not match this installation.'
    }
    if ($values.ContainsKey('-o')) {
        $backend = @(ConvertFrom-WindowsServiceCommandLine ('postgres.exe ' + $values['-o']))
        foreach ($argument in $backend | Select-Object -Skip 1) {
            if ($argument -cmatch '^(-D|--pgdata(?:=|$))') {
                throw 'Service backend options override its selected cluster.'
            }
        }
    }
}

function Get-VerifiedServiceIdentity([string]$Name, [string]$Executable, [string]$ClusterPath) {
    $identities = @(Get-CimInstance Win32_Service -Filter ("Name='" + $Name + "'") -ErrorAction Stop)
    if ($identities.Count -ne 1) { throw 'Existing service identity cannot be verified.' }
    Assert-OwnedServiceIdentity -Identity $identities[0] -Executable $Executable -ClusterPath $ClusterPath -Name $Name
    return $identities[0]
}

if ($Apply -and -not (Test-Elevated)) { throw '-Apply requires an elevated PowerShell session; nothing was changed.' }
if ($DataRoot -notmatch '^[A-Za-z]:[\\/]') { throw 'DataRoot must be an absolute local drive path.' }
$root = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
if ($root -match '(?i)(^|[\\/])(AppData|LocalCache)([\\/]|$)') { throw 'Virtualized paths are not database roots.' }
foreach ($protected in @([IO.Path]::GetPathRoot($root), $env:SystemRoot, $env:ProgramFiles,
                         [Environment]::GetEnvironmentVariable('ProgramFiles(x86)'), $env:USERPROFILE)) {
    if ($protected) {
        $protectedFull = $protected.TrimEnd('\')
        if ($root -ieq $protectedFull -or $protectedFull.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'A drive, system, profile root, or their ancestor is forbidden.'
        }
    }
}
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
if ($root -ieq $repoRoot -or $root.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The database root must be outside the repository.'
}
$distribution = Join-Path $root 'postgresql-18.6'
$bin = Join-Path $distribution 'pgsql\bin'
$pgCtl = Join-Path $bin 'pg_ctl.exe'
$cluster = Join-Path $root 'postgresql-dev-cluster'
$serviceAccount = 'NT AUTHORITY\NetworkService'
$serviceSid = [Security.Principal.SecurityIdentifier]'S-1-5-20'
$systemSid = [Security.Principal.SecurityIdentifier]'S-1-5-18'
$adminsSid = [Security.Principal.SecurityIdentifier]'S-1-5-32-544'
$installerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
# Inspect only the two fixed trees, without following reparse points. Complete
# discovery and DACL construction precede native execution and all ACL writes.
$roles = @(
    @{ Path = $distribution; Rights = 'ReadAndExecute'; Role = 'distribution' },
    @{ Path = $cluster; Rights = 'Modify'; Role = 'cluster' }
)
function New-PrivateAclPlan([object[]]$Roles, [bool]$IncludeService) {
    $entries = New-Object 'System.Collections.Generic.List[object]'
    foreach ($role in $roles) {
        if (-not (Test-Path -LiteralPath $role.Path -PathType Container)) {
            throw 'Both known PostgreSQL directory trees must exist before planning permissions.'
        }
        $ancestor = Get-Item -LiteralPath $role.Path -Force
        while ($null -ne $ancestor) {
            if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are forbidden in PostgreSQL root paths.' }
            $ancestor = $ancestor.Parent
        }
        $pending = New-Object 'System.Collections.Generic.Queue[string]'
        $pending.Enqueue($role.Path)
        while ($pending.Count -gt 0) {
            $path = $pending.Dequeue()
            $item = Get-Item -LiteralPath $path -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are forbidden in PostgreSQL trees.' }
            $entries.Add(@{ Path = $item.FullName; Directory = $item.PSIsContainer; Rights = $role.Rights })
            if ($item.PSIsContainer) {
                foreach ($child in Get-ChildItem -LiteralPath $path -Force) { $pending.Enqueue($child.FullName) }
            }
        }
    }
    foreach ($entry in $entries) {
        if ($entry.Directory) {
            $acl = New-Object Security.AccessControl.DirectorySecurity
            $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        } else {
            $acl = New-Object Security.AccessControl.FileSecurity
            $inheritance = [Security.AccessControl.InheritanceFlags]::None
        }
        $acl.SetAccessRuleProtection($true, $false)
        $acl.SetOwner($adminsSid)
        $grants = @(@{ Sid = $systemSid; Rights = 'FullControl' },
                    @{ Sid = $adminsSid; Rights = 'FullControl' },
                    @{ Sid = $installerSid; Rights = 'FullControl' })
        if ($IncludeService) { $grants += @{ Sid = $serviceSid; Rights = $entry.Rights } }
        foreach ($grant in $grants) {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule(
                $grant.Sid, [Security.AccessControl.FileSystemRights]$grant.Rights,
                $inheritance, [Security.AccessControl.PropagationFlags]::None,
                [Security.AccessControl.AccessControlType]::Allow)
            $acl.AddAccessRule($rule)
        }
        $entry.Acl = $acl
    }
    return ,$entries
}
$entries = New-PrivateAclPlan -Roles $roles -IncludeService ($Action -eq 'Register')
# Identical to scripts/setup-postgres.ps1 Start.
$options = "-h 127.0.0.1 -p $Port -c log_statement=none -c log_min_error_statement=panic " +
    '-c log_error_verbosity=terse -c log_parameter_max_length=0 -c log_parameter_max_length_on_error=0'

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Action -eq 'Unregister' -and $service) {
    $null = Get-VerifiedServiceIdentity -Name $ServiceName -Executable $pgCtl -ClusterPath $cluster
}
$clusterExists = Test-Path -LiteralPath (Join-Path $cluster 'PG_VERSION')
$binariesExist = Test-Path -LiteralPath $pgCtl -PathType Leaf
$clusterRunning = $false
if ($clusterExists -and $binariesExist) {
    # Read-only: pg_ctl status only inspects postmaster.pid and the process.
    $ErrorActionPreference = 'Continue'
    & $pgCtl status -D $cluster *> $null
    $clusterRunning = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
}

Write-Output ('Mode:          ' + $(if ($Apply) { 'APPLY' } else { 'DRY RUN (no changes; add -Apply to execute)' }))
Write-Output ('Action:        ' + $Action)
Write-Output ('Binaries:      ' + $bin + $(if ($binariesExist) { '' } else { ' (MISSING: run scripts/setup-postgres.ps1 -Action Initialize)' }))
Write-Output ('Cluster:       ' + $cluster + $(if ($clusterExists) { '' } else { ' (MISSING)' }))
Write-Output ('Cluster state: ' + $(if ($clusterRunning) { 'running' } else { 'not running' }))
Write-Output ('Service:       ' + $ServiceName + $(if ($service) { ' (exists; status ' + $service.Status + ', start type ' + $service.StartType + ')' } else { ' (not registered)' }))
Write-Output ''
Write-Output 'Planned commands:'
if ($Action -eq 'Register') {
    Write-Output ('"' + $pgCtl + '" register -N ' + $ServiceName + ' -U "' + $serviceAccount + '" -D "' + $cluster + '" -S auto -w -o "' + $options + '"')
    Write-Output ('Then: Start-Service -Name ' + $ServiceName)
} else {
    if ($service -and $service.Status -ne 'Stopped') { Write-Output ('Stop-Service -Name ' + $ServiceName) }
    Write-Output ('"' + $pgCtl + '" unregister -N ' + $ServiceName)
}
Write-Output ('Private ACL plan entries: ' + $entries.Count + '; installing user=' + $installerSid.Value)
foreach ($role in $roles) {
    $entry = $entries | Where-Object { $_.Path -ieq $role.Path } | Select-Object -First 1
    $dacl = $entry.Acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
    Write-Output ('Private DACL ' + $role.Role + ': ' + $dacl)
}
Write-Output 'Every existing entry receives a protected DACL; DataRoot, ancestors and external credentials are untouched.'

if (-not $Apply) {
    Write-Output ''
    Write-Output 'Dry run complete; nothing was changed.'
    exit 0
}
if (-not $binariesExist) { throw 'PostgreSQL binaries are missing under DataRoot.' }

if ($Action -eq 'Register') {
    if (-not $clusterExists) { throw 'The cluster is missing: run scripts/setup-postgres.ps1 -Action Initialize first.' }
    if ($service) { throw 'The service already exists; nothing was changed.' }
    if ($clusterRunning) {
        throw 'The cluster is running outside the service manager; stop it first with scripts/setup-postgres.ps1 -Action Stop.'
    }
    foreach ($entry in $entries) { Set-Acl -LiteralPath $entry.Path -AclObject $entry.Acl }
    Invoke-Checked $pgCtl @('register', '-N', $ServiceName, '-U', $serviceAccount, '-D', $cluster, '-S', 'auto', '-w', '-o', $options)
    Write-Output ('Registered service ' + $ServiceName + ' (automatic start). Start it with: Start-Service -Name ' + $ServiceName)
} else {
    if (-not $service) { throw 'The service is not registered; nothing was changed.' }
    # Re-read the read-only SCM identity immediately before any stop operation.
    $null = Get-VerifiedServiceIdentity -Name $ServiceName -Executable $pgCtl -ClusterPath $cluster
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName
        (Get-Service -Name $ServiceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
    }
    # The running cluster could have created files since initial preflight.
    # Refresh only the two owned trees after confirmed stop, before unregister
    # and ACL removal. New unsafe entries stop the operation here.
    $entries = New-PrivateAclPlan -Roles $roles -IncludeService $false
    $null = Get-VerifiedServiceIdentity -Name $ServiceName -Executable $pgCtl -ClusterPath $cluster
    Invoke-Checked $pgCtl @('unregister', '-N', $ServiceName)
    foreach ($entry in $entries) { Set-Acl -LiteralPath $entry.Path -AclObject $entry.Acl }
    Write-Output ('Unregistered service ' + $ServiceName + '; cluster data was not changed.')
}
