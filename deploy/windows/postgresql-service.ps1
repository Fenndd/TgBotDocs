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
2. grants NT AUTHORITY\NETWORK SERVICE (SID S-1-5-20) modify access to the data
   directory and read/execute access to the distribution;
3. runs pg_ctl register with start type automatic (-S auto) as NETWORK SERVICE.
It does not start the service; run Start-Service afterwards.

Unregister (-Apply): stops the service if it runs (fast shutdown), runs pg_ctl
unregister, and removes the NETWORK SERVICE grants. Cluster data is never deleted.

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

function Test-FullyQualified([string]$Path) {
    return ($Path -match '^[A-Za-z]:[\\/]') -or ($Path -match '^[\\/]{2}[^\\/]+[\\/]')
}

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Command failed (exit ' + $LASTEXITCODE + '): ' + [IO.Path]::GetFileName($Executable)) }
}

if (-not (Test-FullyQualified $DataRoot)) { throw 'DataRoot must be an absolute path.' }
$root = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
if ($root -match '(?i)\\AppData\\Local(?:\\|$)') { throw 'LOCALAPPDATA is not a database root.' }
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
if ($root -ieq $repoRoot -or $root.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The database root must be outside the repository.'
}
$distribution = Join-Path $root 'postgresql-18.6'
$bin = Join-Path $distribution 'pgsql\bin'
$pgCtl = Join-Path $bin 'pg_ctl.exe'
$cluster = Join-Path $root 'postgresql-dev-cluster'
$serviceAccount = 'NT AUTHORITY\NetworkService'
$serviceSid = '*S-1-5-20'
# Identical to scripts/setup-postgres.ps1 Start.
$options = "-h 127.0.0.1 -p $Port -c log_statement=none -c log_min_error_statement=panic " +
    '-c log_error_verbosity=terse -c log_parameter_max_length=0 -c log_parameter_max_length_on_error=0'

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
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
    Write-Output ('icacls "' + $cluster + '" /grant "' + $serviceSid + ':(OI)(CI)M"')
    Write-Output ('icacls "' + $distribution + '" /grant "' + $serviceSid + ':(OI)(CI)RX"')
    Write-Output ('"' + $pgCtl + '" register -N ' + $ServiceName + ' -U "' + $serviceAccount + '" -D "' + $cluster + '" -S auto -w -o "' + $options + '"')
    Write-Output ('Then: Start-Service -Name ' + $ServiceName)
} else {
    if ($service -and $service.Status -ne 'Stopped') { Write-Output ('Stop-Service -Name ' + $ServiceName) }
    Write-Output ('"' + $pgCtl + '" unregister -N ' + $ServiceName)
    Write-Output ('icacls "' + $cluster + '" /remove:g "' + $serviceSid + '"')
    Write-Output ('icacls "' + $distribution + '" /remove:g "' + $serviceSid + '"')
}

if (-not $Apply) {
    Write-Output ''
    Write-Output 'Dry run complete; nothing was changed.'
    exit 0
}
if (-not (Test-Elevated)) { throw '-Apply requires an elevated PowerShell session (Run as administrator); nothing was changed.' }
if (-not $binariesExist) { throw 'PostgreSQL binaries are missing under DataRoot.' }

if ($Action -eq 'Register') {
    if (-not $clusterExists) { throw 'The cluster is missing: run scripts/setup-postgres.ps1 -Action Initialize first.' }
    if ($service) { throw 'The service already exists; nothing was changed.' }
    if ($clusterRunning) {
        throw 'The cluster is running outside the service manager; stop it first with scripts/setup-postgres.ps1 -Action Stop.'
    }
    Invoke-Checked 'icacls.exe' @($cluster, '/grant', ($serviceSid + ':(OI)(CI)M'))
    Invoke-Checked 'icacls.exe' @($distribution, '/grant', ($serviceSid + ':(OI)(CI)RX'))
    Invoke-Checked $pgCtl @('register', '-N', $ServiceName, '-U', $serviceAccount, '-D', $cluster, '-S', 'auto', '-w', '-o', $options)
    Write-Output ('Registered service ' + $ServiceName + ' (automatic start). Start it with: Start-Service -Name ' + $ServiceName)
} else {
    if (-not $service) { throw 'The service is not registered; nothing was changed.' }
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName
        (Get-Service -Name $ServiceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
    }
    Invoke-Checked $pgCtl @('unregister', '-N', $ServiceName)
    Invoke-Checked 'icacls.exe' @($cluster, '/remove:g', $serviceSid)
    Invoke-Checked 'icacls.exe' @($distribution, '/remove:g', $serviceSid)
    Write-Output ('Unregistered service ' + $ServiceName + '; cluster data was not changed.')
}
