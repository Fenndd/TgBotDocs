<#
.SYNOPSIS
Plans or applies private permissions to dedicated Windows delivery directories.
.DESCRIPTION
Dry run by default. -Apply requires elevation. SYSTEM and Administrators retain
full control; the dedicated bot account receives ReadAndExecute on AppRoot and
PythonRoot, Read on ConfigDirectory, and Modify on DataRoot. Existing inherited
and explicit access rules are replaced on every entry after a complete read-only
preflight. Use only dedicated delivery directories; never the PostgreSQL parent,
an operator's profile, or a shared checkout. Reparse points and overlapping roots
are refused. Updating the protected application afterwards requires elevation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AppRoot,
    [Parameter(Mandatory = $true)][string]$PythonRoot,
    [Parameter(Mandatory = $true)][string]$ConfigDirectory,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$BotAccount,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if ($Apply -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '-Apply requires an elevated PowerShell session; no permissions were changed.'
}
try {
    $botSid = (New-Object Security.Principal.NTAccount($BotAccount)).Translate([Security.Principal.SecurityIdentifier])
} catch { throw 'BotAccount does not resolve to a Windows account.' }
$botUser = @(Get-CimInstance Win32_UserAccount -Filter ("SID='" + $botSid.Value + "' AND LocalAccount=TRUE"))
if ($botUser.Count -ne 1 -or $botUser[0].Disabled) {
    throw 'BotAccount must identify one enabled local user, not a group or a domain principal.'
}
if ($Apply -and $botSid.Value -eq $identity.User.Value) {
    throw 'Use a separate dedicated bot account; the installing account must remain an administrator.'
}
$systemSid = [Security.Principal.SecurityIdentifier]'S-1-5-18'
$adminsSid = [Security.Principal.SecurityIdentifier]'S-1-5-32-544'
$roles = @(
    @{ Path = $AppRoot; Rights = 'ReadAndExecute'; Role = 'application' },
    @{ Path = $PythonRoot; Rights = 'ReadAndExecute'; Role = 'Python runtime' },
    @{ Path = $ConfigDirectory; Rights = 'Read'; Role = 'configuration' },
    @{ Path = $DataRoot; Rights = 'Modify'; Role = 'application data' }
)
$entries = New-Object 'System.Collections.Generic.List[object]'
foreach ($role in $roles) {
    if ($role.Path -notmatch '^[A-Za-z]:[\\/]') { throw 'Each root must be an absolute local drive path.' }
    $full = [IO.Path]::GetFullPath($role.Path).TrimEnd('\')
    if ($full -match '(?i)(^|[\\/])(AppData|LocalCache)([\\/]|$)') { throw 'Virtualized paths are forbidden.' }
    if (-not (Test-Path -LiteralPath $full -PathType Container)) { throw 'Every dedicated directory must already exist.' }
    foreach ($protected in @([IO.Path]::GetPathRoot($full), $env:SystemRoot, $env:ProgramFiles, $env:USERPROFILE)) {
        if ($protected) {
            $protectedFull = $protected.TrimEnd('\')
            if ($full -ieq $protectedFull -or $protectedFull.StartsWith($full + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw 'A drive, system, profile root, or their ancestor is forbidden.'
            }
        }
    }
    $role.Path = $full
    $ancestor = Get-Item -LiteralPath $full -Force
    while ($null -ne $ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are forbidden in root paths.' }
        $ancestor = $ancestor.Parent
    }
}
for ($i = 0; $i -lt $roles.Count; $i++) {
    for ($j = $i + 1; $j -lt $roles.Count; $j++) {
        $left = $roles[$i].Path; $right = $roles[$j].Path
        if ($left -ieq $right -or $left.StartsWith($right + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $right.StartsWith($left + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Dedicated delivery roots must be disjoint.'
        }
    }
}
# Do not follow links during discovery. Preflight every entry before any write.
foreach ($role in $roles) {
    $pending = New-Object 'System.Collections.Generic.Queue[string]'
    $pending.Enqueue($role.Path)
    while ($pending.Count -gt 0) {
        $path = $pending.Dequeue()
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are forbidden in delivery trees.' }
        $entries.Add(@{ Path = $item.FullName; Directory = $item.PSIsContainer; Rights = $role.Rights })
        if ($item.PSIsContainer) {
            foreach ($child in Get-ChildItem -LiteralPath $path -Force) { $pending.Enqueue($child.FullName) }
        }
    }
    Write-Output ($role.Role + ': ' + $role.Path + '; bot=' + $role.Rights + '; SYSTEM/Administrators=FullControl')
}
Write-Output ('Preflight entries: ' + $entries.Count)
# Build and validate the complete protected DACL plan even in a dry run.
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
    foreach ($grant in @(@{ Sid = $systemSid; Rights = 'FullControl' },
                         @{ Sid = $adminsSid; Rights = 'FullControl' },
                         @{ Sid = $botSid; Rights = $entry.Rights })) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $grant.Sid, [Security.AccessControl.FileSystemRights]$grant.Rights,
            $inheritance, [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
    }
    $entry.Acl = $acl
}
if (-not $Apply) { Write-Output 'Dry run complete; no permissions were changed.'; exit 0 }
foreach ($entry in $entries) { Set-Acl -LiteralPath $entry.Path -AclObject $entry.Acl }
Write-Output 'Private delivery permissions applied. Check access as the bot account before registering a task.'
