<#
.SYNOPSIS
Back up, restore, or verify the permitted persistent PostgreSQL data (users, current
profiles, Alembic version) of an explicitly configured PostgreSQL installation.

.DESCRIPTION
Backup  : pg_dump (custom format) of exactly public.users, public.extraction_profiles and
          public.alembic_version into a new file outside the repository and outside AppData,
          readable only by the current Windows account. Refuses when the application schema
          holds any other table, and checks the archive listing after the dump.
Restore : pg_restore into a newly created database owned by the application role.
          Existing targets (including the live database) are always refused.
Verify  : restores the dump into a newly created scratch database with a random name,
          compares the table set and per-table row counts/checksums with the source
          database, then drops the scratch database.

Credentials are read from external config/credential files and passed to the PostgreSQL tools only
through the PGPASSWORD environment variable of this process; they are never printed.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Backup', 'Restore', 'Verify')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$DumpPath,
    [string]$TargetDatabase,
    [Parameter(Mandatory = $true)]
    [string]$DataRoot,
    [Parameter(Mandatory = $true)]
    [string]$PgBin,
    [string]$ConfigPath,
    [string]$PythonExe,
    [string]$CredentialFile,
    [string]$AdminCredentialFile
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

# The only tables DATA_MODEL permits in PostgreSQL. A new migration that adds a table
# must be reviewed against DATA_MODEL before this list changes.
$permittedTables = @('alembic_version', 'extraction_profiles', 'users')
$orderKeys = @{ alembic_version = 'version_num'; extraction_profiles = 'id'; users = 'telegram_id' }

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Assert-ExternalPath([string]$Path, [string]$What) {
    if (-not [IO.Path]::IsPathRooted($Path)) { throw "$What must be an absolute path." }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -eq $repoRoot -or $full.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "$What must be outside the repository."
    }
    if ($full -match '(?i)\\(AppData|LocalCache)(\\|$)') { throw "$What must not be under AppData." }
    return $full
}

function Get-DumpHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Invoke-Native([string]$Tool, [string[]]$Arguments, [string]$Failure, [string]$InputText) {
    $executable = Join-Path $bin $Tool
    if (-not (Test-Path -LiteralPath $executable)) { throw "PostgreSQL tool not found: $Tool. Check -PgBin." }
    # Native diagnostics can contain SQL/data. Return only the fixed failure text.
    try {
        if ($PSBoundParameters.ContainsKey('InputText')) { $output = $InputText | & $executable @Arguments 2>$null }
        else { $output = & $executable @Arguments 2>$null }
    } catch { throw $Failure }
    if ($LASTEXITCODE -ne 0) { throw $Failure }
    return $output
}

$savedEnvironment = @{}
function Set-SessionEnvironment([string]$Password) {
    foreach ($name in 'PGPASSWORD', 'PGCONNECT_TIMEOUT', 'PGTZ', 'PGDATESTYLE', 'PGOPTIONS', 'PGSSLMODE',
             'PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE', 'PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGUSER', 'PGDATABASE') {
        if (-not $savedEnvironment.ContainsKey($name)) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        }
    }
    $env:PGPASSWORD = $Password
    foreach ($name in 'PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE', 'PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGUSER', 'PGDATABASE') {
        Remove-Item -LiteralPath ("Env:" + $name) -ErrorAction SilentlyContinue
    }
    $env:PGSSLMODE = $credentials.sslmode
    $env:PGCONNECT_TIMEOUT = '10'
    # Identical text rendering of timestamps for source and restored checksums.
    $env:PGTZ = 'UTC'
    $env:PGDATESTYLE = 'ISO'
    $env:PGOPTIONS = '-c client_min_messages=warning'
}
function Restore-SessionEnvironment {
    foreach ($name in @($savedEnvironment.Keys)) {
        if ($null -eq $savedEnvironment[$name]) {
            Remove-Item -LiteralPath ("Env:" + $name) -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath ("Env:" + $name) -Value $savedEnvironment[$name]
        }
    }
}

function Invoke-Sql($Credentials, [string]$User, [string]$Password, [string]$Database, [string]$Sql) {
    Set-SessionEnvironment $Password
    $lines = Invoke-Native 'psql.exe' @('--no-password', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-h', $Credentials.host,
        '-p', "$($Credentials.port)", '-U', $User, '-d', $Database) 'PostgreSQL query failed.' $Sql
    return @($lines | Where-Object { $_ -ne '' })
}

function Get-TableSet($Credentials, [string]$Database) {
    # Every ordinary/partitioned table outside the system schemas, as schema.name.
    $sql = "select n.nspname || '.' || c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace " +
        "where c.relkind in ('r', 'p') and n.nspname not in ('pg_catalog', 'information_schema') " +
        "and n.nspname not like 'pg_toast%' order by 1;"
    return @(Invoke-Sql $Credentials $Credentials.username $Credentials.password $Database $sql)
}

function Get-TableSummary($Credentials, [string]$User, [string]$Password, [string]$Database) {
    $parts = foreach ($table in $permittedTables) {
        "select '$table', count(*), md5(coalesce(string_agg(t::text, chr(10) order by t.$($orderKeys[$table])), '')) " +
            "from public.$table t"
    }
    return @(Invoke-Sql $Credentials $User $Password $Database (($parts -join ' union all ') + ' order by 1;'))
}

function Read-Credentials([string]$Path) {
    $full = Assert-ExternalPath $Path 'The credential path'
    try { $value = Get-Content -Raw -LiteralPath $full | ConvertFrom-Json }
    catch { throw 'The credential file could not be read.' }
    return $value
}

function Read-ConfigConnection([string]$Path) {
    $full = Assert-ExternalPath $Path 'The configuration path'
    if (-not $PythonExe) { $script:PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw 'Config parsing requires the installed application Python; supply -PythonExe.'
    }
    # dotenv matches the application's quoting rules and disables interpolation.
    # make_url decodes credentials without feeding a URL/password to any argv.
    $code = @'
import json, sys
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
try:
    url = make_url(dotenv_values(sys.argv[1], interpolate=False)["DATABASE_URL"])
    if url.drivername not in ("postgresql", "postgresql+psycopg") or set(url.query) - {"sslmode"}:
        raise ValueError()
    print(json.dumps(dict(host=url.host, port=url.port or 5432, database=url.database,
                         username=url.username, password=url.password,
                         sslmode=url.query.get("sslmode", "prefer"))))
except Exception:
    sys.exit(1)
'@
    # stdin also avoids Windows PowerShell 5.1's legacy -c quote mangling.
    try { $result = $code | & $PythonExe - $full 2>$null }
    catch { throw 'DATABASE_URL could not be parsed; check external configuration.' }
    if ($LASTEXITCODE -ne 0) { throw 'DATABASE_URL could not be parsed; check external configuration.' }
    try { return ($result | ConvertFrom-Json) }
    catch { throw 'DATABASE_URL could not be parsed; check external configuration.' }
}

function Assert-Connection($Value) {
    foreach ($key in 'host', 'port', 'database', 'username', 'password') {
        if (-not ($Value.PSObject.Properties.Name -contains $key) -or $null -eq $Value.$key -or "$($Value.$key)" -eq '') {
            throw 'The connection file lacks required connection values.'
        }
    }
    if ("$($Value.database)" -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$' -or
        "$($Value.port)" -notmatch '^\d+$' -or [int]$Value.port -lt 1 -or [int]$Value.port -gt 65535) {
        throw 'The connection database/port is invalid.'
    }
    if (-not ($Value.PSObject.Properties.Name -contains 'sslmode')) {
        $Value | Add-Member -NotePropertyName sslmode -NotePropertyValue 'prefer'
    }
    if ($Value.sslmode -notin @('disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full')) {
        throw 'The connection sslmode is invalid.'
    }
}

function Create-OwnedDatabase([string]$Database) {
    Set-SessionEnvironment $admin.password
    Invoke-Native 'createdb.exe' @('--no-password', '-h', $credentials.host, '-p', "$($credentials.port)",
        '-U', $admin.username, '-O', $credentials.username, '-T', 'template0', '-E', 'UTF8', $Database) `
        'Could not create the new database; it must not exist and the admin role needs CREATEDB.' | Out-Null
}

function Remove-OwnedDatabase([string]$Database) {
    Set-SessionEnvironment $admin.password
    Invoke-Native 'dropdb.exe' @('--no-password', '--if-exists', '--force', '-h', $credentials.host,
        '-p', "$($credentials.port)", '-U', $admin.username, $Database) 'Scratch database cleanup failed.' | Out-Null
}

function Assert-DumpListing([string]$Path) {
    $lines = @(Invoke-Native 'pg_restore.exe' @('--list', $Path) 'The dump could not be read as a custom-format archive.')
    $tables = @{}; $data = @{}
    foreach ($line in $lines) {
        if ($line -match '^\s*;' -or $line.Trim() -eq '') { continue }
        # Tables, their data, keys, index, and the identity sequence/default that Alembic
        # created for users.telegram_id. Anything else is rejected.
        if ($line -notmatch ('^\d+;\s+\d+\s+\d+\s+(?<type>TABLE DATA|FK CONSTRAINT|SEQUENCE OWNED BY|SEQUENCE SET|' +
                'TABLE|CONSTRAINT|INDEX|SEQUENCE|DEFAULT)\s+(?<schema>\S+)\s+(?<name>\S+)')) {
            throw 'The dump contains an entry type outside the permitted table set; it was not accepted.'
        }
        $type = $Matches.type; $schema = $Matches.schema; $name = $Matches.name
        if ($schema -ne 'public') { throw 'The dump contains an object outside the public schema.' }
        if ($type -like 'SEQUENCE*' -and $name -ne 'users_telegram_id_seq') {
            throw 'The dump contains a sequence that does not belong to a permitted table.'
        }
        if ($type -in @('TABLE', 'TABLE DATA', 'CONSTRAINT', 'FK CONSTRAINT', 'DEFAULT') -and $name -notin $permittedTables) {
            throw 'The dump contains an object belonging to an unapproved table.'
        }
        if ($type -eq 'INDEX' -and $name -ne 'ix_extraction_profiles_owner_id') {
            throw 'The dump contains an unapproved index.'
        }
        if ($type -eq 'TABLE') { $tables[$name] = $true }
        if ($type -eq 'TABLE DATA') { $data[$name] = $true }
    }
    $expected = ($permittedTables | Sort-Object) -join ','
    if ((($tables.Keys | Sort-Object) -join ',') -ne $expected -or (($data.Keys | Sort-Object) -join ',') -ne $expected) {
        throw 'The dump table set differs from users, extraction_profiles and alembic_version.'
    }
}

function Invoke-Restore($Credentials, [string]$Path, [string]$Database) {
    # This helper is called only after this invocation created an empty target.
    Set-SessionEnvironment $Credentials.password
    Invoke-Native 'pg_restore.exe' @('--no-password', '--single-transaction', '--exit-on-error',
        '--no-owner', '--no-privileges', '-h', $Credentials.host, '-p', "$($Credentials.port)",
        '-U', $Credentials.username, '-d', $Database, $Path) 'pg_restore failed; nothing was committed to the target database.' | Out-Null
}

$root = Assert-ExternalPath $DataRoot 'DataRoot'
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'DataRoot must exist.' }
$bin = [IO.Path]::GetFullPath($PgBin)
if (-not [IO.Path]::IsPathRooted($PgBin)) { throw 'PgBin must be an absolute path.' }
$dump = Assert-ExternalPath $DumpPath 'The dump path'
if (([bool]$ConfigPath) -eq ([bool]$CredentialFile)) { throw 'Supply exactly one of -ConfigPath or -CredentialFile.' }
$credentials = if ($ConfigPath) { Read-ConfigConnection $ConfigPath } else { Read-Credentials $CredentialFile }
Assert-Connection $credentials
$admin = $credentials
if ($AdminCredentialFile) {
    $admin = Read-Credentials $AdminCredentialFile
    Assert-Connection $admin
    if ($admin.host -ne $credentials.host -or $admin.port -ne $credentials.port -or $admin.sslmode -ne $credentials.sslmode) {
        throw 'Admin credentials must refer to the same PostgreSQL host/port/sslmode.'
    }
} elseif ($credentials.PSObject.Properties.Name -contains 'admin_username' -and
          $credentials.PSObject.Properties.Name -contains 'admin_password') {
    $admin = [pscustomobject]@{ username = $credentials.admin_username; password = $credentials.admin_password }
}
$expectedSet = ($permittedTables | ForEach-Object { "public.$_" } | Sort-Object) -join ','

try {
    if ($Action -eq 'Backup') {
        if (Test-Path -LiteralPath $dump) { throw 'The dump file already exists; choose a new path. Existing files are never replaced.' }
        $directory = Split-Path -Parent $dump
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) { throw 'The dump directory does not exist.' }
        $sourceTables = @(Get-TableSet $credentials $credentials.database)
        if ((($sourceTables | Sort-Object) -join ',') -ne $expectedSet) {
            throw 'The database table set differs from the permitted set; review DATA_MODEL before backing up.'
        }
        # Create the file first and restrict it to the current account, so the dump is never
        # written into a file with inherited, broader permissions.
        # CreateNew closes the existence-check race without truncating somebody else's file.
        $newFile = [IO.File]::Open($dump, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $newFile.Dispose()
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $dump '/inheritance:r' '/grant:r' ($identity + ':F') *> $null
        if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $dump -Force; throw 'Could not restrict the dump file.' }
        try {
            Set-SessionEnvironment $credentials.password
            $arguments = @('--no-password', '--format=custom', '--no-owner', '--no-privileges', '-h', $credentials.host,
                '-p', "$($credentials.port)", '-U', $credentials.username, '-d', $credentials.database, '-f', $dump)
            foreach ($table in $permittedTables) { $arguments += @('--table', "public.$table") }
            Invoke-Native 'pg_dump.exe' $arguments 'pg_dump failed.' | Out-Null
            Assert-DumpListing $dump
        } catch {
            Remove-Item -LiteralPath $dump -Force -ErrorAction SilentlyContinue
            throw
        }
        $hash = Get-DumpHash $dump
        Write-Output "Backup written: $dump ($((Get-Item -LiteralPath $dump).Length) bytes, SHA-256 $hash)."
        Write-Output 'Contents: users, extraction_profiles, alembic_version. Access: current Windows account only.'
    } else {
        if (-not (Test-Path -LiteralPath $dump -PathType Leaf)) { throw 'The dump file does not exist.' }
        Assert-DumpListing $dump
        if ($Action -eq 'Restore') {
            if (-not $TargetDatabase) { throw 'Restore requires -TargetDatabase.' }
            if ($TargetDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') { throw 'The target database name is not a plain identifier.' }
            if ($TargetDatabase -eq $credentials.database) {
                throw 'The target is the live application database; in-place restore is never permitted.'
            }
            Create-OwnedDatabase $TargetDatabase
            try { Invoke-Restore $credentials $dump $TargetDatabase }
            catch {
                $restoreFailure = $_
                try { Remove-OwnedDatabase $TargetDatabase }
                catch { Write-Warning "Restore target cleanup failed: $TargetDatabase. Remove this newly created database manually." }
                throw $restoreFailure
            }
            Write-Output "Restored users, extraction_profiles and alembic_version into '$TargetDatabase' in one transaction."
        } else {
            # The application role has no CREATEDB privilege; the local admin role creates the
            # scratch database owned by the application role, which then restores into it
            # exactly as Restore would.
            $scratch = 'tgbotdocs_verify_' + [guid]::NewGuid().ToString('N').Substring(0, 16)
            Create-OwnedDatabase $scratch
            Write-Output "Created scratch database $scratch."
            $verificationPassed = $false
            try {
                Invoke-Restore $credentials $dump $scratch
                $restoredSet = (Get-TableSet $credentials $scratch | Sort-Object) -join ','
                if ($restoredSet -ne $expectedSet) { throw 'Restored table set differs from the permitted set.' }
                Write-Output "Table set matches: $restoredSet."
                $source = Get-TableSummary $credentials $credentials.username $credentials.password $credentials.database
                $restored = Get-TableSummary $credentials $credentials.username $credentials.password $scratch
                $mismatch = $false
                for ($i = 0; $i -lt $permittedTables.Count; $i++) {
                    $s = $source[$i].Split('|'); $r = $restored[$i].Split('|')
                    $state = 'match'
                    if ($s[0] -ne $r[0] -or $s[1] -ne $r[1] -or $s[2] -ne $r[2]) { $state = 'DIFFERENT'; $mismatch = $true }
                    Write-Output "$($s[0]): source rows=$($s[1]), restored rows=$($r[1]), checksum $state."
                }
                if ($mismatch) { throw 'Restored data differs from the current source database (it may have changed after the backup).' }
                $verificationPassed = $true
                Write-Output 'Verification passed.'
            } finally {
                try {
                    Remove-OwnedDatabase $scratch
                    Write-Output "Dropped scratch database $scratch."
                } catch {
                    Write-Warning "Scratch cleanup failed: $scratch. Remove this owned database manually."
                    # Preserve the original restore/comparison exception, if any.
                    if ($verificationPassed) { throw 'Verification matched, but scratch database cleanup failed.' }
                }
            }
        }
    }
} finally {
    Restore-SessionEnvironment
}
