<#
.SYNOPSIS
Plans, and with -Apply performs, removal of the TgBotDocs bot scheduled task.

.DESCRIPTION
DRY RUN BY DEFAULT: reports whether the task exists and its state, and prints the
commands that -Apply would run. -Apply requires an elevated session; it stops the
task if it is running and unregisters it. Data, logs, configuration, the checkout,
and PostgreSQL are not touched.

Stopping a task terminates its process without the bot's graceful shutdown; the
bot's llama-server child is in a kill-on-close job, and the next start cleans the
temporary root. After -Apply, check that no bot Python process is left (see
docs/operations/INSTALL_WINDOWS.md).

Compatible with Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
.\deploy\windows\uninstall-bot-task.ps1
.\deploy\windows\uninstall-bot-task.ps1 -Apply
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'TgBotDocs Bot',
    [string]$TaskPath = '\TgBotDocs\',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
Write-Output ('Mode: ' + $(if ($Apply) { 'APPLY' } else { 'DRY RUN (no changes; add -Apply to unregister)' }))
if (-not $existing) {
    Write-Output ('Task ' + $TaskPath + $TaskName + ' is not registered (or not visible to this account); nothing to do.')
    exit 0
}
Write-Output ('Task ' + $TaskPath + $TaskName + ' is registered; state ' + $existing.State + '.')
Write-Output 'Planned commands:'
if ($existing.State -eq 'Running') {
    Write-Output ('Stop-ScheduledTask -TaskPath ''' + $TaskPath + ''' -TaskName ''' + $TaskName + '''')
}
Write-Output ('Unregister-ScheduledTask -TaskPath ''' + $TaskPath + ''' -TaskName ''' + $TaskName + ''' -Confirm:$false')

if (-not $Apply) {
    Write-Output 'Dry run complete; nothing was changed.'
    exit 0
}
if (-not (Test-Elevated)) { throw '-Apply requires an elevated PowerShell session (Run as administrator); nothing was changed.' }
if ($existing.State -eq 'Running') {
    Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $state = (Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath).State
        if ($state -ne 'Running') { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($state -eq 'Running') { throw 'Task did not stop; it was not unregistered. Inspect Task Scheduler.' }
}
Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false
Write-Output ('Unregistered ' + $TaskPath + $TaskName + '.')
