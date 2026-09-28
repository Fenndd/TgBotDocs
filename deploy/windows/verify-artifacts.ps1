<#
.SYNOPSIS
Read-only check of the pinned runtime artifacts and the frozen recognition configuration.

.DESCRIPTION
Checks presence and SHA-256 of:
- <DataRoot>\runtime-b11221\llama-server.exe
- <DataRoot>\models\Qwen3VL-4B-Instruct-Q4_K_M.gguf
- <DataRoot>\models\mmproj-Qwen3VL-4B-Instruct-F16.gguf
against the pinned values read from src\tgbotdocs\recognition\runtime.py (class
RuntimeFiles), and the frozen configuration file against -FrozenConfigSha256. It
also checks that the frozen configuration names llama.cpp build b11221 and the same
three runtime hashes.

Nothing is written or started. Exit code 0 when everything matches, 1 on any missing
file or mismatch, 2 on invalid arguments or unreadable pins.

Compatible with Windows PowerShell 5.1 and PowerShell 7.

.PARAMETER DataRoot
Absolute DATA_ROOT of the installation.

.PARAMETER FrozenConfigPath
Absolute path of the frozen configuration (FROZEN_CONFIG). Default:
<DataRoot>\frozen\frozen-t01b.json.

.PARAMETER FrozenConfigSha256
Expected SHA-256 of the frozen configuration file. Default: the T01b value recorded
in docs/testing/T01B_CALIBRATION_REPORT.md.

.EXAMPLE
.\deploy\windows\verify-artifacts.ps1 -DataRoot D:\TgBotDocsData\prod
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DataRoot,
    [string]$FrozenConfigPath,
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$FrozenConfigSha256 = 'dd1d01a0e8ff878a60b7b4bf61b6bcb20939cd5bd5695bed4eaa79a55ea633f6'
)
$ErrorActionPreference = 'Stop'

function Test-FullyQualified([string]$Path) {
    return ($Path -match '^[A-Za-z]:[\\/]') -or ($Path -match '^[\\/]{2}[^\\/]+[\\/]')
}

function Stop-Usage([string]$Message) {
    [Console]::Error.WriteLine('verify_artifacts_usage_error: ' + $Message)
    exit 2
}

if (-not (Test-FullyQualified $DataRoot)) { Stop-Usage 'DataRoot must be an absolute path.' }
$root = [IO.Path]::GetFullPath($DataRoot)
if (-not $FrozenConfigPath) { $FrozenConfigPath = Join-Path $root 'frozen\frozen-t01b.json' }
if (-not (Test-FullyQualified $FrozenConfigPath)) { Stop-Usage 'FrozenConfigPath must be an absolute path.' }
$frozenPath = [IO.Path]::GetFullPath($FrozenConfigPath)

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runtimeSource = Join-Path $repoRoot 'src\tgbotdocs\recognition\runtime.py'
if (-not (Test-Path -LiteralPath $runtimeSource -PathType Leaf)) { Stop-Usage 'runtime.py was not found in the checkout.' }
$source = [IO.File]::ReadAllText($runtimeSource)
$pins = @{}
foreach ($name in 'executable_sha256', 'model_sha256', 'projector_sha256') {
    $match = [regex]::Match($source, '(?m)^\s*' + $name + '\s*:\s*str\s*=\s*"([0-9a-f]{64})"')
    if (-not $match.Success) { Stop-Usage ('pinned ' + $name + ' was not found in runtime.py.') }
    $pins[$name] = $match.Groups[1].Value
}

$checks = @(
    @{ Label = 'llama-server.exe (b11221)'; Path = (Join-Path $root 'runtime-b11221\llama-server.exe'); Expected = $pins['executable_sha256'] },
    @{ Label = 'model Q4_K_M'; Path = (Join-Path $root 'models\Qwen3VL-4B-Instruct-Q4_K_M.gguf'); Expected = $pins['model_sha256'] },
    @{ Label = 'vision projector F16'; Path = (Join-Path $root 'models\mmproj-Qwen3VL-4B-Instruct-F16.gguf'); Expected = $pins['projector_sha256'] },
    @{ Label = 'frozen configuration'; Path = $frozenPath; Expected = $FrozenConfigSha256.ToLowerInvariant() }
)

$failures = 0
foreach ($check in $checks) {
    if (-not (Test-Path -LiteralPath $check.Path -PathType Leaf)) {
        Write-Output ('MISSING   ' + $check.Label + ': ' + $check.Path)
        $failures++
        continue
    }
    $actual = (Get-FileHash -LiteralPath $check.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -eq $check.Expected) {
        Write-Output ('OK        ' + $check.Label + ': ' + $actual)
    } else {
        Write-Output ('MISMATCH  ' + $check.Label + ': expected ' + $check.Expected + ', actual ' + $actual)
        $failures++
    }
}

# The frozen configuration must name the same pinned runtime (a consistency check of
# the file's own content, not a replacement for the application's identity check).
if (Test-Path -LiteralPath $frozenPath -PathType Leaf) {
    try {
        $frozen = [IO.File]::ReadAllText($frozenPath) | ConvertFrom-Json
        $artifacts = $frozen.runtime_artifacts
        $consistent = ($artifacts.llama_cpp_build -eq 'b11221') -and
            ($artifacts.executable_sha256 -eq $pins['executable_sha256']) -and
            ($artifacts.model_sha256 -eq $pins['model_sha256']) -and
            ($artifacts.projector_sha256 -eq $pins['projector_sha256'])
        if ($consistent) {
            Write-Output 'OK        frozen configuration names build b11221 and the pinned runtime hashes'
        } else {
            Write-Output 'MISMATCH  frozen configuration runtime_artifacts differ from runtime.py pins'
            $failures++
        }
    } catch {
        Write-Output 'MISMATCH  frozen configuration is not readable JSON'
        $failures++
    }
}

if ($failures -gt 0) {
    Write-Output ('Result: FAILED (' + $failures + ' problem(s))')
    exit 1
}
Write-Output 'Result: all pinned artifacts verified'
exit 0
