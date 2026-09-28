<#
.SYNOPSIS
Plans, and with -Apply registers, the scheduled task that runs the TgBotDocs bot.

.DESCRIPTION
DRY RUN BY DEFAULT: validates the inputs and prints the exact Register-ScheduledTask
definition without changing anything. Only -Apply registers the task, and -Apply
refuses to run outside an elevated (Run as administrator) session.

Task definition (ADR-0005, T08):
- action: Python runs the bot directly with --restart-on-failure; there is no
  intermediate shell whose termination could leave the bot polling;
- trigger: at system startup;
- principal: the given account, logon type S4U (runs whether or not the account is
  signed in, stores no password, has no network credentials), limited run level;
- application: retry a failed startup/run after one minute within the same Python
  process, after resource cleanup. Clean shutdown ends the retry loop;
- settings: scheduler restart on failure (999 times), no execution time limit,
  ignore a new instance while one runs, start when available (a missed start runs
  as soon as possible), normal process priority (the Task Scheduler default of 7 is
  below normal), and do not stop or refuse to start on battery power.

-RunCheck requires -Apply: it runs "python -m tgbotdocs check --config"
in the current session as the current user before anything else. That check cleans
the temporary root, applies database migrations, and starts and stops the pinned
llama-server on the GPU; it sends nothing to Telegram. It runs as the installing
user, not as the task account. Dry run never runs the application.

Compatible with Windows PowerShell 5.1 and PowerShell 7.

.PARAMETER ConfigPath
Absolute path of the external .env file, outside the checkout and outside AppData.

.PARAMETER UserId
Account the task runs as, for example "MACHINE\botuser" or "DOMAIN\botuser". It
needs read access to the checkout and the configuration file, modify access to
DATA_ROOT, and the "Log on as a batch job" right.

.PARAMETER TaskName
Scheduled task name. Default: "TgBotDocs Bot".

.PARAMETER TaskPath
Task Scheduler folder. Default: "\TgBotDocs\".

.PARAMETER Replace
With -Apply, replace an existing task of the same name instead of refusing.

.PARAMETER RunCheck
Run "python -m tgbotdocs check --config <ConfigPath>" first and stop on failure.

.PARAMETER Apply
Register the task. Requires an elevated session.

.EXAMPLE
.\deploy\windows\install-bot-task.ps1 -ConfigPath D:\TgBotDocs\config\tgbotdocs.env -UserId "$env:COMPUTERNAME\botuser"

.EXAMPLE
.\deploy\windows\install-bot-task.ps1 -ConfigPath D:\TgBotDocs\config\tgbotdocs.env -UserId "$env:COMPUTERNAME\botuser" -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$UserId,
    [string]$TaskName = 'TgBotDocs Bot',
    [string]$TaskPath = '\TgBotDocs\',
    [switch]$Replace,
    [switch]$RunCheck,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'

function Test-FullyQualified([string]$Path) {
    return ($Path -match '^[A-Za-z]:[\\/]') -or ($Path -match '^[\\/]{2}[^\\/]+[\\/]')
}

function Test-Inside([string]$Child, [string]$Parent) {
    $parentFull = $Parent.TrimEnd('\')
    return ($Child -ieq $parentFull) -or $Child.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Test-VirtualizedSegment([string]$Path) {
    foreach ($part in $Path.Split([char[]]@('\', '/'), [StringSplitOptions]::RemoveEmptyEntries)) {
        if ($part -ieq 'AppData' -or $part -ieq 'LocalCache') { return $true }
    }
    return $false
}

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

# ---- Validation (read-only) ----
if ($RunCheck -and -not $Apply) { throw '-RunCheck requires -Apply; a dry run cannot change local data.' }
if ($Apply -and -not (Test-Elevated)) { throw '-Apply requires an elevated PowerShell session (Run as administrator); nothing was changed.' }
if (-not (Test-FullyQualified $ConfigPath)) { throw 'ConfigPath must be an absolute path.' }
$config = [IO.Path]::GetFullPath($ConfigPath)
if (Test-Inside $config $repoRoot) { throw 'ConfigPath must be outside the checkout.' }
if (Test-VirtualizedSegment $config) { throw 'ConfigPath must not be under AppData or LocalCache.' }
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { throw 'ConfigPath does not name an existing file.' }
if ($config.Contains('"')) { throw 'ConfigPath must not contain double quotes.' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The virtual environment is missing: run "uv sync --locked --no-dev" in the checkout first.'
}
if (-not $TaskPath.StartsWith('\') -or -not $TaskPath.EndsWith('\')) { throw 'TaskPath must start and end with a backslash.' }
try {
    $sid = (New-Object Security.Principal.NTAccount($UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
} catch {
    throw 'UserId does not resolve to a Windows account on this machine.'
}

$argument = '-m tgbotdocs run --config "' + $config + '" --restart-on-failure'
$description = 'Runs the TgBotDocs Telegram bot (python -m tgbotdocs run) at startup; restarts on failure.'

# In-memory CIM objects only; nothing is registered until Register-ScheduledTask.
$action = New-ScheduledTaskAction -Execute $python -Argument $argument -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -Priority 5 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($Apply -and $existing -and -not $Replace) { throw 'The task is already registered; pass -Replace to overwrite it, or uninstall it first.' }

Write-Output ('Mode:            ' + $(if ($Apply) { 'APPLY' } else { 'DRY RUN (no changes; add -Apply to register)' }))
Write-Output ('Checkout:        ' + $repoRoot)
Write-Output ('Python:          ' + $python)
Write-Output ('Configuration:   ' + $config)
Write-Output ('Account:         ' + $UserId + ' (SID ' + $sid + ')')
Write-Output ('Task:            ' + $TaskPath + $TaskName + $(if ($existing) { ' (already registered)' } else { ' (not registered)' }))
Write-Output ''
Write-Output 'Planned definition:'
Write-Output ('$action = New-ScheduledTaskAction -Execute ''' + $python + ''' `')
Write-Output ('    -Argument ''' + $argument.Replace("'", "''") + ''' `')
Write-Output ('    -WorkingDirectory ''' + $repoRoot + '''')
Write-Output '$trigger = New-ScheduledTaskTrigger -AtStartup'
Write-Output ('$principal = New-ScheduledTaskPrincipal -UserId ''' + $UserId + ''' -LogonType S4U -RunLevel Limited')
Write-Output '$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `'
Write-Output '    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew -StartWhenAvailable `'
Write-Output '    -Priority 5 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries'
Write-Output ('Register-ScheduledTask -TaskName ''' + $TaskName + ''' -TaskPath ''' + $TaskPath + ''' `')
Write-Output ('    -Action $action -Trigger $trigger -Principal $principal -Settings $settings `')
Write-Output ('    -Description ''' + $description + '''' + $(if ($Replace) { ' -Force' } else { '' }))
Write-Output ''
Write-Output ('Resolved settings: RestartCount=' + $settings.RestartCount + ' RestartInterval=' + $settings.RestartInterval +
    ' ExecutionTimeLimit=' + $settings.ExecutionTimeLimit + ' MultipleInstances=' + $settings.MultipleInstances +
    ' StartWhenAvailable=' + $settings.StartWhenAvailable + ' Priority=' + $settings.Priority +
    ' LogonType=' + $principal.LogonType + ' RunLevel=' + $principal.RunLevel)

if ($RunCheck) {
    Write-Output ''
    Write-Output 'Running: python -m tgbotdocs check --config <ConfigPath> (as the current user)'
    Push-Location -LiteralPath $repoRoot
    try {
        $ErrorActionPreference = 'Continue'
        & $python -m tgbotdocs check --config $config
        $checkCode = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    } finally { Pop-Location }
    if ($checkCode -ne 0) { throw ('tgbotdocs check failed with exit code ' + $checkCode + '; nothing was registered.') }
}

if (-not $Apply) {
    Write-Output ''
    Write-Output 'Dry run complete; nothing was registered.'
    exit 0
}

$registered = Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description $description -Force:$Replace
Write-Output ''
Write-Output ('Registered ' + $registered.TaskPath + $registered.TaskName + ' (state ' + $registered.State + ').')
Write-Output ('It starts at the next boot. Start now with: Start-ScheduledTask -TaskPath ''' + $TaskPath + ''' -TaskName ''' + $TaskName + '''')
