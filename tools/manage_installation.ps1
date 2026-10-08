param(
    [ValidateSet('Start','Remove')][string]$Action = 'Start',
    [string]$InstallBase,
    [string]$KitRoot,
    [switch]$PrepareOnly,
    [switch]$LibraryOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dependency_ownership.ps1')
$KitVersion = '110.1.2'

function Get-SourceExtensionFolder {
    if (Test-Path (Join-Path $ProjectRoot 'source\extensions')) { return (Join-Path $ProjectRoot 'source\extensions') }
    return (Join-Path $ProjectRoot 'exts')
}

function Test-Kit([string]$Root) {
    if (-not $Root) { return $false }
    foreach ($part in @('kit.exe','python\python.exe','kernel\config\kit-core.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $part) -PathType Leaf)) { return $false }
    }
    try { return (Read-Json (Join-Path $Root 'kernel\config\kit-core.json')).crashreporter.data.buildVersion -eq $KitVersion }
    catch { return $false }
}

function Find-Kit([string]$Requested) {
    foreach ($root in @($Requested, $env:KIT_ROOT, (Join-Path $ProjectRoot 'kit'),
        (Join-Path $ProjectRoot '_build\windows-x86_64\release\kit'))) {
        if (Test-Kit $root) { return [IO.Path]::GetFullPath($root) }
    }
    return $null
}

function Copy-BuildInputs([string]$Destination) {
    if (-not (Test-Path (Join-Path $ProjectRoot 'source\apps'))) { throw 'Private source build requires a recursive source clone.' }
    New-Item -ItemType Directory -Path $Destination | Out-Null
    foreach ($name in @('repo.bat','repo.sh','repo.toml','repo_tools.toml','premake5.lua','VERSION.md',
        'PRODUCT_TERMS_OMNIVERSE','THIRD_PARTY_NOTICES.md','Start_Demo.bat','Remove_Demo.bat','INSTALL.md')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot $name) -Destination $Destination
    }
    foreach ($name in @('tools','source')) {
        & robocopy.exe (Join-Path $ProjectRoot $name) (Join-Path $Destination $name) /E /XJ /R:0 /W:0 /NFL /NDL /NJH /NJS `
            /XD .git __pycache__ /XF .git '*.pyc' FindSurface.dll app_defaults.json repo-cache.json
        if ($LASTEXITCODE -ge 8) { throw "Private build input copy failed: $name" }
    }
}

function Invoke-PrivateSetup([string]$Workspace, [string]$Command, [string[]]$Arguments) {
    $names = @('PM_MODULE_DIR','PM_PYTHON','PM_PYTHON_BASE_DIR','PM_INSTALL_PATH','PM_PACKAGES_ROOT')
    $saved = @{}
    foreach ($name in $names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:PM_PACKAGES_ROOT = Join-Path (Split-Path -Parent $Workspace) 'packman'
    Push-Location $Workspace
    try {
        & $Command @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Private dependency command failed with code $LASTEXITCODE" }
    } finally {
        Pop-Location
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    }
}

function Initialize-PrivateBuild($Record) {
    $root = Assert-PrivateRoot $Record
    $workspace = Join-Path $root 'build-workspace'
    $runtime = Join-Path $workspace '_build\windows-x86_64\release\kit'
    if (Test-Kit $runtime) { return $runtime }
    if (Test-Path $workspace) { throw 'Incomplete private build retained; inspect/remove the private installation before retrying.' }
    Write-Host "Private Kit/Packman build destination: $root"
    Write-Host 'Review NVIDIA Omniverse license terms: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/'
    if ((Read-Host 'Type YES to accept the applicable terms and download/build dependencies') -cne 'YES') { throw 'Cancelled.' }
    Copy-BuildInputs $workspace
    $cache = @{
        PM_PACKAGES_ROOT = (Join-Path $root 'packman')
        PIP_CACHE_DIR = (Join-Path $root 'pip')
        UV_CACHE_DIR = (Join-Path $root 'uv')
    }
    foreach ($path in $cache.Values) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
    # Both repo.bat and repoman read this private workspace's configuration.
    Write-JsonAtomic $cache (Join-Path $workspace 'repo-cache.json')
    Invoke-PrivateSetup $workspace (Join-Path $workspace 'repo.bat') @('build')
    if (-not (Test-Kit $runtime)) { throw 'Private Kit build failed; files retained for diagnosis.' }
    return $runtime
}

function Initialize-PrivateThin($Record) {
    $root = Assert-PrivateRoot $Record
    $workspace = Join-Path $root 'thin-workspace'
    $runtime = Join-Path $workspace 'kit'
    if (Test-Kit $runtime) { return $runtime }
    if (Test-Path $workspace) { throw 'Incomplete private thin install retained; inspect it before retrying.' }
    if (-not (Test-Path (Join-Path $ProjectRoot 'dev\repo.bat'))) { throw 'Thin package is missing NVIDIA dependency tooling.' }
    Write-Host "Private thin install destination: $root"
    Write-Host 'Review NVIDIA Omniverse license terms: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/'
    if ((Read-Host 'Type YES to accept the applicable terms and download dependencies') -cne 'YES') { throw 'Cancelled.' }
    New-Item -ItemType Directory -Path $workspace | Out-Null
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'pull_kit_sdk.bat') -Destination $workspace
    foreach ($name in @('dev','apps','exts')) {
        & robocopy.exe (Join-Path $ProjectRoot $name) (Join-Path $workspace $name) /E /XJ /R:0 /W:0 /NFL /NDL /NJH /NJS `
            /XD .git __pycache__ /XF .git '*.pyc' FindSurface.dll app_defaults.json repo-cache.json
        if ($LASTEXITCODE -ge 8) { throw "Thin input copy failed: $name" }
    }
    $cache = @{
        PM_PACKAGES_ROOT=(Join-Path $root 'packman')
        PIP_CACHE_DIR=(Join-Path $root 'pip')
        UV_CACHE_DIR=(Join-Path $root 'uv')
    }
    foreach ($path in $cache.Values) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
    Write-JsonAtomic $cache (Join-Path $workspace 'dev\repo-cache.json')
    Invoke-PrivateSetup $workspace (Join-Path $workspace 'pull_kit_sdk.bat') @()
    if (-not (Test-Kit $runtime)) { throw 'Private thin install failed; retained for diagnosis.' }
    return $runtime
}

function Get-LaunchArguments([string]$Runtime) {
    $folder = Get-SourceExtensionFolder
    $app = Join-Path $ProjectRoot 'source\apps\com.curvsurf.findsurface_omniverse_demo.kit'
    if (-not (Test-Path $app)) { $app = Join-Path $ProjectRoot 'apps\com.curvsurf.findsurface_omniverse_demo.kit' }
    if (-not (Test-Path $app)) { throw 'Demo experience file is missing.' }
    $args = @($app, '--ext-folder', $folder)
    # Runtime sibling cache belongs to its existing installation; it is never
    # adopted/deleted when the runtime is external.
    foreach ($cache in @((Join-Path (Split-Path -Parent $Runtime) 'extscache'), (Join-Path $ProjectRoot 'extscache'))) {
        if (Test-Path $cache) { $args += @('--ext-folder', $cache) }
    }
    return $args
}

function Start-Installation {
    $extensionFolder = Get-SourceExtensionFolder
    $bootstrap = Join-Path $extensionFolder 'com.findsurface.bootstrap'
    if (-not (Test-Path (Join-Path $bootstrap 'config\extension.toml'))) {
        if (-not (Test-Path (Join-Path $ProjectRoot '.git'))) { throw 'Use the thin release ZIP or a recursive clone, not the automatic Source ZIP.' }
        & git.exe -c "safe.directory=$($ProjectRoot.Replace('\','/'))" -C $ProjectRoot submodule update --init --recursive
        if ($LASTEXITCODE -ne 0) { throw 'Pinned submodule initialization failed.' }
    }
    if (Test-Path $RecordPath) {
        $record = Read-Json $RecordPath
        $null = Assert-PrivateRoot $record
    } else {
        $base = $InstallBase
        if (-not $base) {
            $default = Join-Path $env:LOCALAPPDATA 'CurvSurf\FindSurfaceOmniverseDemo'
            $base = Read-Host "Private dependency base folder (Enter for $default)"
            if (-not $base) { $base = $default }
        }
        $record = New-InstallationRecord $base
    }
    $root = Assert-PrivateRoot $record
    if ($KitRoot) {
        if (-not (Test-Kit $KitRoot)) { throw 'Explicit KitRoot is not a complete Kit 110.1.2 installation.' }
        $runtime = [IO.Path]::GetFullPath($KitRoot)
    } elseif ($record.runtime -and (Test-Kit $record.runtime.path)) { $runtime = $record.runtime.path }
    else { $runtime = Find-Kit $null }
    if (-not $runtime) {
        if (-not (Test-Path (Join-Path $ProjectRoot 'source\apps'))) {
            $runtime = Initialize-PrivateThin $record
        } else { $runtime = Initialize-PrivateBuild $record }
    }
    $privateRuntime = Join-Path $root 'build-workspace\_build\windows-x86_64\release\kit'
    $ownership = if ($runtime -eq $privateRuntime -or $runtime -eq (Join-Path $root 'thin-workspace\kit')) {'private'} else {'external'}
    $record.runtime = @{path=$runtime; ownership=$ownership; version=$KitVersion}
    Write-JsonAtomic $record $RecordPath
    $sdk = Join-Path $bootstrap 'data\native\windows-x86_64\FindSurface.dll'
    if ($record.sdk -and (Test-Path $record.sdk.path -PathType Leaf)) {
        $sdk = $record.sdk.path
        if ($record.sdk.ownership -eq 'private' -and ((Get-Sha256 $sdk) -ne $record.sdk.sha256 -or
            $sdk -ne (Join-Path $root 'sdk\FindSurface.dll'))) { throw 'Private SDK path/hash mismatch.' }
    } elseif (-not (Test-Path $sdk -PathType Leaf)) {
        $sdk = Join-Path $root 'sdk\FindSurface.dll'
        $release = Read-Json (Join-Path $bootstrap 'config\sdk_release.json')
        if ($release.release_tag -ne 'v1.0.0') { throw 'Update the installer SDK digest for the new release before downloading.' }
        $url = $release.release_base_url + '/' + $release.release_tag + '/' + $release.assets.'windows-x86_64'
        Receive-VerifiedFile $url $sdk '559ad2f68323790f10ba71c2416df1f3b115fed2b683482f25b0244a554cf230'
    }
    $python = Join-Path $runtime 'python\python.exe'
    & $python -B -c 'import ctypes, sys; ctypes.CDLL(sys.argv[1])' $sdk
    if ($LASTEXITCODE -ne 0) { throw 'SDK load check failed.' }
    $ownership = if ($sdk -eq (Join-Path $root 'sdk\FindSurface.dll')) {'private'} else {'external'}
    $record.sdk = @{path=$sdk; ownership=$ownership; sha256=(Get-Sha256 $sdk)}
    Write-JsonAtomic $record $RecordPath
    Write-Host "Kit ($($record.runtime.ownership)): $runtime"
    Write-Host "SDK ($ownership): $sdk"
    if ($PrepareOnly) { return }
    $previousSdk = $env:FINDSURFACE_APP_SDK_PATH
    try {
        $env:FINDSURFACE_APP_SDK_PATH = $sdk
        $arguments = Get-LaunchArguments $runtime
        & (Join-Path $runtime 'kit.exe') @arguments
        if ($LASTEXITCODE -ne 0) { throw "Demo exited with code $LASTEXITCODE" }
    } finally { $env:FINDSURFACE_APP_SDK_PATH = $previousSdk }
}

if ($LibraryOnly) { return }
$installationLock = $null
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }
    Assert-NoReparsePath $RecordPath
    New-Item -ItemType Directory -Path (Split-Path -Parent $RecordPath) -Force | Out-Null
    $installationLock = [IO.File]::Open((Join-Path (Split-Path -Parent $RecordPath) 'operation.lock'),
        [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    if ($Action -eq 'Start') { Start-Installation } else {
        if (-not (Test-Path $RecordPath)) { throw 'No ownership record; no legacy dependencies will be removed.' }
        $record = Read-Json $RecordPath
        Remove-Installation $record
        if ((Read-Host 'Type REMOVE to permanently delete the listed app-private folder') -ceq 'REMOVE') {
            Remove-Installation $record -Confirmed
        } else { Write-Host 'Cancelled; nothing removed.' }
    }
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($installationLock) { $installationLock.Dispose() } }
