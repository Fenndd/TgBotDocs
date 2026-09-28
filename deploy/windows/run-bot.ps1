<#
.SYNOPSIS
Runs the TgBotDocs bot in the foreground for the joint operator test.

.DESCRIPTION
Resolves the checkout from this script's location (deploy\windows -> repository root),
requires an absolute configuration file outside the checkout, runs
"<checkout>\.venv\Scripts\python.exe -m tgbotdocs run --config <file>" from the
checkout, and exits with the Python process exit code (0 stopped, 1 application
failure). Wrapper validation failures exit with 2.

The application writes only its technical log to <DATA_ROOT>\logs\tgbotdocs.log.
The scheduled task launches Python directly with --restart-on-failure; this manual
wrapper does not retry or capture configuration/console contents into another log.

Compatible with Windows PowerShell 5.1 and PowerShell 7.

.PARAMETER ConfigPath
Absolute path of the external .env file, outside the checkout and outside AppData.

.EXAMPLE
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\windows\run-bot.ps1 -ConfigPath D:\TgBotDocs\config\tgbotdocs.env
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)
$ErrorActionPreference = 'Stop'

function Stop-Wrapper([string]$Code) {
    [Console]::Error.WriteLine('run_bot_failed: ' + $Code)
    exit 2
}

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

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not (Test-FullyQualified $ConfigPath)) { Stop-Wrapper 'config_path_must_be_absolute' }
$config = [IO.Path]::GetFullPath($ConfigPath)
if (Test-Inside $config $repoRoot) { Stop-Wrapper 'config_path_must_be_outside_checkout' }
if (Test-VirtualizedSegment $config) { Stop-Wrapper 'config_path_must_not_use_appdata' }
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { Stop-Wrapper 'config_file_missing' }

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-Wrapper 'virtual_environment_missing_run_uv_sync' }

Set-Location -LiteralPath $repoRoot
Write-Output 'run_bot_starting'
# Native stderr must not become a terminating error under Windows PowerShell 5.1.
$ErrorActionPreference = 'Continue'
& $python -m tgbotdocs run --config $config
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }
Write-Output ('run_bot_exited ' + $code)
exit $code
