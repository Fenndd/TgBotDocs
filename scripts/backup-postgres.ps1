<#
.SYNOPSIS
Back up, restore, or verify the permitted persistent PostgreSQL data (users, current
profiles, Alembic version) of the development cluster created by setup-postgres.ps1.

.DESCRIPTION
Backup  : pg_dump (custom format) of exactly public.users, public.extraction_profiles and
          public.alembic_version into a new file outside the repository and outside AppData,
          readable only by the current Windows account. Refuses when the application schema
          holds any other table, and checks the archive listing after the dump.
Restore : pg_restore of such a dump into an explicit existing database in one transaction.
          The live application database is refused unless -Force is given.
Verify  : restores the dump into a newly created scratch database with a random name,
          compares the table set and per-table row counts/checksums with the source
          database, then drops the scratch database.

Credentials are read from the credential file and passed to the PostgreSQL tools only
through the PGPASSWORD environment variable of this process; they are never printed.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Backup', 'Restore', 'Verify')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$DumpPath,
    [string]$TargetDatabase,
    [switch]$Force,
    [string]$DataRoot = 'C:\Users\nikit\TgBotDocsData',
    [string]$CredentialFile
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

# The only tables DATA_MODEL permits in PostgreSQL. A new migration that adds a table
# must be reviewed against DATA_MODEL before this list changes.
$permittedTables = @('alembic_version', 'extraction_profiles', 'users')
$orderKeys = @{ alembic_version = 'version_num'; extraction_profiles = 'id'; users = 'telegram_id' }

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$root = [IO.Path]::GetFullPath($DataRoot)
$bin = Join-Path $root 'postgresql-18.6\pgsql\bin'
if (-not $CredentialFile) { $CredentialFile = Join-Path $root 'postgresql-dev-credentials.json' }

function Assert-ExternalPath([string]$Path, [string]$What) {
    if (-not [IO.Path]::IsPathRooted($Path)) { throw "$What must be an absolute path." }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -eq $repoRoot -or $full.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "$What must be outside the repository."
    }
    if ($full -match '(?i)\\(AppData|LocalCache)(\\|$)') { throw "$What must not be under AppData." }
    return $full
}

function Invoke-Native([string]$Tool, [string[]]$Arguments, [string]$Failure, [string]$InputText) {
    $executable = Join-Path $bin $Tool
    if (-not (Test-Path -LiteralPath $executable)) { throw "PostgreSQL tool not found: $Tool. Run setup-postgres.ps1 first." }
    if ($PSBoundParameters.ContainsKey('InputText')) { $output = $InputText | & $executable @Arguments }
    else { $output = & $executable @Arguments }
    if ($LASTEXITCODE -ne 0) { throw $Failure }
    return $output
}

$savedEnvironment = @{}
function Set-SessionEnvironment([string]$Password) {
    foreach ($name in 'PGPASSWORD', 'PGCONNECT_TIMEOUT', 'PGTZ', 'PGDATESTYLE', 'PGOPTIONS') {
        if (-not $savedEnvironment.ContainsKey($name)) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        }
    }
    $env:PGPASSWORD = $Password
    $env:PGCONNECT_TIMEOUT = '10'
    # Identical text rendering of timestamps for source and restored checksums.
    $env:PGTZ = 'UTC'
    $env:PGDATESTYLE = 'ISO'
    $env:PGOPTIONS = '-c client_min_messages=warning'
}
function Restore-SessionEnvironment {
    foreach ($name in @($savedEnvironment.Keys)) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}

function Invoke-Sql($Credentials, [string]$User, [string]$Password, [string]$Database, [string]$Sql) {
    Set-SessionEnvironment $Password
    $lines = Invoke-Native 'psql.exe' @('-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-h', $Credentials.host,
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
        if ($type -like 'SEQUENCE*' -and $name -notmatch '^(users|extraction_profiles|alembic_version)_\w+_seq$') {
            throw 'The dump contains a sequence that does not belong to a permitted table.'
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
    # One transaction: any error rolls the whole restore back. --clean --if-exists replaces
    # only the three permitted tables; other objects in the target are not touched.
    Set-SessionEnvironment $Credentials.password
    Invoke-Native 'pg_restore.exe' @('--single-transaction', '--exit-on-error', '--clean', '--if-exists',
        '--no-owner', '--no-privileges', '-h', $Credentials.host, '-p', "$($Credentials.port)",
        '-U', $Credentials.username, '-d', $Database, $Path) 'pg_restore failed; nothing was committed to the target database.' | Out-Null
}

$dump = Assert-ExternalPath $DumpPath 'The dump path'
$credentialPath = [IO.Path]::GetFullPath($CredentialFile)
if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'The credential file does not exist.' }
$credentials = Get-Content -Raw -LiteralPath $credentialPath | ConvertFrom-Json
foreach ($key in 'host', 'port', 'database', 'username', 'password') {
    if (-not ($credentials.PSObject.Properties.Name -contains $key)) { throw "The credential file lacks the '$key' key." }
}
$expectedSet = ($permittedTables | ForEach-Object { "public.$_" } | Sort-Object) -join ','

try {
    if ($Action -eq 'Backup') {
        if (Test-Path -LiteralPath $dump) { throw 'The dump file already exists; choose a new path. Existing files are never replaced.' }
        $directory = Split-Path -Parent $dump
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) { throw 'The dump directory does not exist.' }
        $publicTables = @(Get-TableSet $credentials $credentials.database | Where-Object { $_ -like 'public.*' })
        if ((($publicTables | Sort-Object) -join ',') -ne $expectedSet) {
            throw 'The application schema holds tables other than the permitted set; review DATA_MODEL before backing up.'
        }
        # Create the file first and restrict it to the current account, so the dump is never
        # written into a file with inherited, broader permissions.
        [IO.File]::WriteAllBytes($dump, [byte[]]@())
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $dump '/inheritance:r' '/grant:r' ($identity + ':F') *> $null
        if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $dump -Force; throw 'Could not restrict the dump file.' }
        try {
            Set-SessionEnvironment $credentials.password
            $arguments = @('--format=custom', '--no-owner', '--no-privileges', '-h', $credentials.host,
                '-p', "$($credentials.port)", '-U', $credentials.username, '-d', $credentials.database, '-f', $dump)
            foreach ($table in $permittedTables) { $arguments += @('--table', "public.$table") }
            Invoke-Native 'pg_dump.exe' $arguments 'pg_dump failed.' | Out-Null
            Assert-DumpListing $dump
        } catch {
            Remove-Item -LiteralPath $dump -Force -ErrorAction SilentlyContinue
            throw
        }
        $hash = (Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Output "Backup written: $dump ($((Get-Item -LiteralPath $dump).Length) bytes, SHA-256 $hash)."
        Write-Output 'Contents: users, extraction_profiles, alembic_version. Access: current Windows account only.'
    } else {
        if (-not (Test-Path -LiteralPath $dump -PathType Leaf)) { throw 'The dump file does not exist.' }
        Assert-DumpListing $dump
        if ($Action -eq 'Restore') {
            if (-not $TargetDatabase) { throw 'Restore requires -TargetDatabase.' }
            if ($TargetDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') { throw 'The target database name is not a plain identifier.' }
            if ($TargetDatabase -eq $credentials.database -and -not $Force) {
                throw 'The target is the live application database; stop the bot and pass -Force to replace its profiles.'
            }
            Invoke-Restore $credentials $dump $TargetDatabase
            Write-Output "Restored users, extraction_profiles and alembic_version into '$TargetDatabase' in one transaction."
        } else {
            foreach ($key in 'admin_username', 'admin_password') {
                if (-not ($credentials.PSObject.Properties.Name -contains $key)) {
                    throw 'Verify needs the admin role from the credential file to create a scratch database.'
                }
            }
            # The application role has no CREATEDB privilege; the local admin role creates the
            # scratch database owned by the application role, which then restores into it
            # exactly as Restore would.
            $scratch = 'tgbotdocs_verify_' + [guid]::NewGuid().ToString('N').Substring(0, 16)
            Set-SessionEnvironment $credentials.admin_password
            Invoke-Native 'createdb.exe' @('-h', $credentials.host, '-p', "$($credentials.port)", '-U',
                $credentials.admin_username, '-O', $credentials.username, '-T', 'template0', '-E', 'UTF8', $scratch) `
                'Could not create the scratch database.' | Out-Null
            Write-Output "Created scratch database $scratch."
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
                Write-Output 'Verification passed.'
            } finally {
                Set-SessionEnvironment $credentials.admin_password
                Invoke-Native 'dropdb.exe' @('--if-exists', '--force', '-h', $credentials.host, '-p', "$($credentials.port)",
                    '-U', $credentials.admin_username, $scratch) 'Could not drop the scratch database; drop it manually.' | Out-Null
                Write-Output "Dropped scratch database $scratch."
            }
        }
    }
} finally {
    Restore-SessionEnvironment
}
