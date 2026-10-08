$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$RecordPath = Join-Path $ProjectRoot '.installation\manifest.json'

function Write-JsonAtomic($Value, [string]$Path) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = $Path + '.tmp'
    $json = $Value | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Read-Json([string]$Path) {
    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Assert-NoReparsePath([string]$Path) {
    $candidate = [IO.Path]::GetFullPath($Path)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing a symlink/junction path: $candidate"
            }
        }
        $candidate = Split-Path -Parent $candidate
    }
}

function Assert-PrivateRoot($Record, [switch]$InspectContents) {
    if ($Record.schema -ne 1 -or $Record.app -ne 'FindSurfaceOmniverseDemo') { throw 'Unknown installation record.' }
    $id = [guid]::Parse($Record.id).ToString()
    $root = [IO.Path]::GetFullPath($Record.private_root).TrimEnd('\')
    if ((Split-Path -Leaf $root) -ne "fsod-$id") { throw 'Private root name does not match installation ID.' }
    if ([IO.Path]::GetFullPath($Record.project_root).TrimEnd('\') -ne $ProjectRoot) {
        throw 'This record belongs to another/moved checkout. Keep the old record; see INSTALL.md.'
    }
    Assert-NoReparsePath $root
    $marker = Read-Json (Join-Path $root '.fsod-owner.json')
    if ($marker.id -ne $Record.id -or $marker.project_root -ne $Record.project_root) { throw 'Ownership marker mismatch.' }
    if ($InspectContents) {
        $links = Get-ChildItem -LiteralPath $root -Recurse -Force -ErrorAction Stop |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
        foreach ($link in $links) {
            $targets = @($link.Target)
            if ($targets.Count -ne 1 -or -not $targets[0]) { throw 'Unknown reparse target; manual inspection required.' }
            $target = $targets[0]
            if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path (Split-Path -Parent $link.FullName) $target }
            $target = [IO.Path]::GetFullPath($target).TrimEnd('\')
            if (-not $target.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Private installation links outside its owned root: $($link.FullName)"
            }
        }
    }
    return $root
}

function New-InstallationRecord([string]$Base) {
    $id = [guid]::NewGuid().ToString()
    $root = Join-Path ([IO.Path]::GetFullPath($Base)) "fsod-$id"
    Assert-NoReparsePath $root
    if (Test-Path -LiteralPath $root) { throw 'Refusing to adopt an existing private directory.' }
    New-Item -ItemType Directory -Path $root | Out-Null
    $record = [pscustomobject]@{
        schema = 1; app = 'FindSurfaceOmniverseDemo'; id = $id
        project_root = $ProjectRoot; private_root = $root
        runtime = $null; sdk = $null
    }
    Write-JsonAtomic @{ id = $id; project_root = $ProjectRoot } (Join-Path $root '.fsod-owner.json')
    Write-JsonAtomic $record $RecordPath
    return $record
}

function Receive-VerifiedFile([string]$Url, [string]$Path, [string]$Hash) {
    if ($Url -notmatch '^https://' -or $Hash -notmatch '^[a-fA-F0-9]{64}$') { throw 'Download URL/hash is not pinned.' }
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
        $partial = $Path + '.partial'
        $curl = Get-Command curl.exe -ErrorAction Stop
        & $curl.Source --fail --location --proto '=https' --proto-redir '=https' --retry 3 --continue-at - --output $partial $Url
        if ($LASTEXITCODE -ne 0) { throw 'Download failed; partial file retained for retry.' }
        if ((Get-Sha256 $partial) -ne $Hash) {
            throw "Hash mismatch; inspect/remove $partial before retrying."
        }
        Move-Item -LiteralPath $partial -Destination $Path
    }
    if ((Get-Sha256 $Path) -ne $Hash) { throw "Hash mismatch: $Path" }
}

function Assert-NoKitProcess {
    # Conservative: do not delete while any Kit app might use the dependency.
    if (Get-Process -Name kit -ErrorAction SilentlyContinue) { throw 'Close all Kit/Isaac Sim apps before removing dependencies.' }
}

function Remove-Installation($Record, [switch]$Confirmed) {
    $root = Assert-PrivateRoot $Record -InspectContents
    Write-Host "App-private runtime/downloads only: $root"
    foreach ($entry in @($Record.runtime, $Record.sdk)) {
        if ($entry -and $entry.ownership -eq 'external') { Write-Host "PRESERVED external dependency: $($entry.path)" }
    }
    Write-Host 'App source, user data/settings and shared NVIDIA/Packman caches are NOT removed.'
    if (-not $Confirmed) { return }
    Assert-NoKitProcess
    # Revalidate exact owned target immediately before recursive removal.
    $root = Assert-PrivateRoot $Record -InspectContents
    # Unlink verified internal junctions without traversing them.
    $links = @(Get-ChildItem -LiteralPath $root -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
        Sort-Object { $_.FullName.Length } -Descending)
    foreach ($link in $links) {
        if ($link.PSIsContainer) { [IO.Directory]::Delete($link.FullName) }
        else { [IO.File]::Delete($link.FullName) }
    }
    Remove-Item -LiteralPath $root -Recurse -Force
    Remove-Item -LiteralPath $RecordPath
}
