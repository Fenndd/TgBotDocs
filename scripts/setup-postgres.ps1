param(
    [ValidateSet('Initialize', 'Start', 'Stop', 'Status')]
    [string]$Action = 'Status',
    [string]$DataRoot = 'C:\Users\nikit\TgBotDocsData',
    [int]$Port = 55432
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($DataRoot)
if ($taskRoot -match '(?i)\\AppData\\Local(?:\\|$)') { throw 'LOCALAPPDATA is not a database root.' }
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($taskRoot.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $taskRoot -eq $repoRoot) {
    throw 'The database root must be outside the repository.'
}
$distribution = Join-Path $taskRoot 'postgresql-18.6'
$bin = Join-Path $distribution 'pgsql\bin'
$cluster = Join-Path $taskRoot 'postgresql-dev-cluster'
$credentialFile = Join-Path $taskRoot 'postgresql-dev-credentials.json'
$archive = Join-Path $distribution 'postgresql-18.6-windows-x64-binaries.zip'
$expectedHash = '1DF55002AFE95B945D934C078B13E82C1603FA546731E511D068AA983B4EAD28'

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL command failed; inspect the local technical log.' }
}

function Start-Cluster {
    if (-not (Test-Path -LiteralPath (Join-Path $cluster 'PG_VERSION'))) { throw 'Initialize the cluster first.' }
    & (Join-Path $bin 'pg_ctl.exe') status -D $cluster *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output 'Development cluster is already running.'; return }
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw 'The selected port is already in use.'
    }
    # No service/admin changes. Keep the process hidden and log technical events outside Git.
    $process = Start-Process -FilePath (Join-Path $bin 'postgres.exe') -WindowStyle Hidden -PassThru `
        -ArgumentList @('-D', ('"' + $cluster + '"'), '-h', '127.0.0.1', '-p', $Port,
            '-c', 'log_statement=none', '-c', 'log_min_error_statement=panic',
            '-c', 'log_error_verbosity=terse',
            '-c', 'log_parameter_max_length=0', '-c', 'log_parameter_max_length_on_error=0') `
        -RedirectStandardOutput (Join-Path $taskRoot 'postgresql-dev.stdout.log') `
        -RedirectStandardError (Join-Path $taskRoot 'postgresql-dev.stderr.log')
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        & (Join-Path $bin 'pg_isready.exe') -h 127.0.0.1 -p $Port -q
        if ($LASTEXITCODE -eq 0) { Write-Output "Development PostgreSQL is ready on 127.0.0.1:$Port."; return }
        if ($process.HasExited) { throw 'PostgreSQL exited; inspect the local technical log.' }
        Start-Sleep -Milliseconds 250
    }
    throw 'PostgreSQL readiness timed out.'
}

if ($Action -eq 'Initialize') {
    if ((Test-Path -LiteralPath $cluster) -or (Test-Path -LiteralPath $credentialFile)) {
        throw 'A cluster or credentials already exists; use Start. Existing data is never replaced.'
    }
    New-Item -ItemType Directory -Path $distribution -Force | Out-Null
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -Uri 'https://sbp.enterprisedb.com/getfile.jsp?fileid=1260566' -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
        throw 'Archive SHA-256 differs from the reviewed development artifact.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $bin 'postgres.exe'))) {
        Invoke-Checked 'tar.exe' @('-xf', $archive, '-C', $distribution, 'pgsql/bin', 'pgsql/lib', 'pgsql/share',
            'pgsql/server_license.txt', 'pgsql/commandlinetools_3rd_party_licenses.txt')
    }
    # EDB's ZIP executables are unsigned. This hash pins the artifact downloaded
    # over HTTPS from the link on EDB's official page, not a vendor-signed checksum.
    Invoke-Checked (Join-Path $bin 'postgres.exe') @('--version')
    $adminPassword = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $appPassword = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $passwordFile = Join-Path $taskRoot ('initdb-password-' + [guid]::NewGuid().ToString('N') + '.txt')
    [IO.File]::WriteAllText($passwordFile, $adminPassword + "`n")
    try {
        Invoke-Checked (Join-Path $bin 'initdb.exe') @('-D', $cluster, '-U', 'tgbotdocs_dev_admin',
            '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C', ('--pwfile=' + $passwordFile))
    } finally { Remove-Item -LiteralPath $passwordFile -Force }
    $credentials = @{ host='127.0.0.1'; port=$Port; database='tgbotdocs_dev'; username='tgbotdocs_dev';
        password=$appPassword; admin_username='tgbotdocs_dev_admin'; admin_password=$adminPassword }
    [IO.File]::WriteAllText($credentialFile, ($credentials | ConvertTo-Json))
    # Restrict the generated credential file to the current Windows account and SYSTEM.
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $credentialFile '/inheritance:r' '/grant:r' ($identity + ':F') 'SYSTEM:F' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restrict the generated credential file.' }
    Start-Cluster
    $previousPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $adminPassword
        # Generated hexadecimal password is never printed or passed in a command argument.
        "CREATE ROLE tgbotdocs_dev LOGIN PASSWORD '$appPassword';" | & (Join-Path $bin 'psql.exe') `
            -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port -U tgbotdocs_dev_admin -d postgres
        if ($LASTEXITCODE -ne 0) { throw 'Development role creation failed.' }
        Invoke-Checked (Join-Path $bin 'createdb.exe') @('-h', '127.0.0.1', '-p', "$Port", '-U',
            'tgbotdocs_dev_admin', '-O', 'tgbotdocs_dev', 'tgbotdocs_dev')
    } finally { $env:PGPASSWORD = $previousPassword }
    Write-Output "Credentials generated outside Git: $credentialFile"
} elseif ($Action -eq 'Start') {
    Start-Cluster
} elseif ($Action -eq 'Stop') {
    Invoke-Checked (Join-Path $bin 'pg_ctl.exe') @('stop', '-D', $cluster, '-m', 'fast', '-w')
} else {
    Invoke-Checked (Join-Path $bin 'pg_ctl.exe') @('status', '-D', $cluster)
}
