<#
.SYNOPSIS
Runs the TgBotDocs bot in the foreground; this is what the scheduled task executes.

.DESCRIPTION
Resolves the checkout from this script's location (deploy\windows -> repository root),
requires an absolute configuration file outside the checkout, runs
"<checkout>\.venv\Scripts\python.exe -m tgbotdocs run --config <file>" from the
checkout, and exits with the Python process exit code (0 stopped, 1 application
failure). Wrapper validation failures exit with 2.

The application writes its technical log to <DATA_ROOT>\logs\tgbotdocs.log. Its
console lines (start/stop markers and content-free failure codes) are also appended
to <DATA_ROOT>\logs\run-bot.log with a UTC timestamp, because a scheduled task has
no visible console. Standard error is not captured here.

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

# Best-effort console log next to the application's own log. DATA_ROOT is only read
# here; the application validates every path itself before using it.
$consoleLog = $null
try {
    foreach ($line in [IO.File]::ReadAllLines($config)) {
        if ($line -match '^\s*DATA_ROOT\s*=\s*(.+?)\s*$') {
            $dataRoot = $Matches[1].Trim('"', "'")
            if ((Test-FullyQualified $dataRoot) -and -not (Test-VirtualizedSegment $dataRoot) -and
                -not (Test-Inside ([IO.Path]::GetFullPath($dataRoot)) $repoRoot)) {
                $logDirectory = Join-Path ([IO.Path]::GetFullPath($dataRoot)) 'logs'
                [void][IO.Directory]::CreateDirectory($logDirectory)
                $consoleLog = Join-Path $logDirectory 'run-bot.log'
                # Keep the wrapper log small: one previous generation of about 5 MB.
                if ((Test-Path -LiteralPath $consoleLog) -and (Get-Item -LiteralPath $consoleLog).Length -gt 5MB) {
                    Move-Item -LiteralPath $consoleLog -Destination ($consoleLog + '.1') -Force
                }
            }
            break
        }
    }
} catch {
    $consoleLog = $null
}

function Write-ConsoleLine([string]$Text) {
    Write-Output $Text
    if ($null -ne $consoleLog) {
        try {
            $stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
            [IO.File]::AppendAllText($consoleLog, $stamp + ' ' + $Text + [Environment]::NewLine)
        } catch { }
    }
}

Set-Location -LiteralPath $repoRoot
Write-ConsoleLine 'run_bot_starting'
# Native stderr must not become a terminating error under Windows PowerShell 5.1.
$ErrorActionPreference = 'Continue'
& $python -m tgbotdocs run --config $config | ForEach-Object { Write-ConsoleLine ([string]$_) }
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }
Write-ConsoleLine ('run_bot_exited ' + $code)
exit $code
