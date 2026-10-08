param([Parameter(Mandatory=$true)][string]$Sandbox)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\tools\manage_installation.ps1') -LibraryOnly
$ProjectRoot = Join-Path $Sandbox 'app'
$RecordPath = Join-Path $ProjectRoot '.installation\manifest.json'
New-Item -ItemType Directory -Path $ProjectRoot -Force | Out-Null
$passed = 0
function Check($Condition, $Message) {
    if (-not $Condition) { throw $Message }
    $script:passed++
}
function Must-Fail([scriptblock]$Action, [string]$Message) {
    $failed = $false
    try { & $Action | Out-Null } catch { $failed = $true }
    Check $failed $Message
}
$record = New-InstallationRecord (Join-Path $Sandbox 'dependencies')
$owned = Assert-PrivateRoot $record
Check (Test-Path $RecordPath) 'Record was not saved.'
Check ($owned -eq $record.private_root) 'Owned root validation failed.'
$external = Join-Path $Sandbox 'legacy-runtime'
New-Item -ItemType Directory -Path $external | Out-Null
$record.runtime = @{path=$external; ownership='external'}
Write-JsonAtomic $record $RecordPath
Remove-Installation $record
Check (Test-Path $owned) 'Preview deleted owned root.'
Check (Test-Path $external) 'Preview deleted external root.'
$originalId = $record.id
$record.id = [guid]::NewGuid().ToString()
Must-Fail { Assert-PrivateRoot $record } 'Forged ID accepted.'
$record.id = $originalId
$originalProject = $record.project_root
$record.project_root = Join-Path $Sandbox 'another-app'
Must-Fail { Assert-PrivateRoot $record } 'Foreign checkout accepted.'
$record.project_root = $originalProject
$originalRoot = $record.private_root
$record.private_root = $Sandbox
Must-Fail { Assert-PrivateRoot $record } 'Broad root accepted.'
$record.private_root = $originalRoot
$markerPath = Join-Path $owned '.fsod-owner.json'
Write-JsonAtomic @{id='wrong'; project_root=$ProjectRoot} $markerPath
Must-Fail { Assert-PrivateRoot $record } 'Wrong owner marker accepted.'
Write-JsonAtomic @{id=$record.id; project_root=$ProjectRoot} $markerPath
Must-Fail { Receive-VerifiedFile 'http://example.invalid/file' (Join-Path $owned 'bad') ('0'*64) } 'HTTP accepted.'
Must-Fail { Receive-VerifiedFile 'https://example.invalid/file' (Join-Path $owned 'bad') '' } 'Unpinned download accepted.'
$fixture = Join-Path $owned 'cached.bin'
[IO.File]::WriteAllText($fixture, 'fixture')
$digest = Get-Sha256 $fixture
Receive-VerifiedFile 'https://example.invalid/file' $fixture $digest
Check (Test-Path $fixture) 'Offline verified cache failed.'
Must-Fail { Receive-VerifiedFile 'https://example.invalid/file' $fixture ('0'*64) } 'Wrong digest accepted.'
Check (-not (Test-Kit $external)) 'Empty legacy folder accepted as runtime.'
$fakeRuntime = Join-Path $Sandbox 'complete-runtime'
New-Item -ItemType Directory -Path (Join-Path $fakeRuntime 'python') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fakeRuntime 'kernel\config') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $fakeRuntime 'kit.exe'), '')
[IO.File]::WriteAllText((Join-Path $fakeRuntime 'python\python.exe'), '')
Write-JsonAtomic @{crashreporter=@{data=@{buildVersion='110.1.2'}}} (Join-Path $fakeRuntime 'kernel\config\kit-core.json')
Check (Test-Kit $fakeRuntime) 'Runtime structure/version rejected.'
Check ((Find-Kit $fakeRuntime) -eq $fakeRuntime) 'Requested existing runtime was not preferred.'
Write-JsonAtomic @{crashreporter=@{data=@{buildVersion='110.1.20'}}} (Join-Path $fakeRuntime 'kernel\config\kit-core.json')
Check (-not (Test-Kit $fakeRuntime)) 'Wrong runtime version accepted.'
$junction = Join-Path $owned 'external-link'
New-Item -ItemType Junction -Path $junction -Target $external | Out-Null
Must-Fail { Assert-PrivateRoot $record -InspectContents } 'Nested external junction accepted.'
[IO.Directory]::Delete($junction)
# No runtime process is used by these synthetic folders. Exercise the guard
# separately, then stub it only for deletion of this test-owned temporary root.
$inside = Join-Path $owned 'inside'
New-Item -ItemType Directory -Path $inside | Out-Null
New-Item -ItemType Junction -Path (Join-Path $owned 'internal-link') -Target $inside | Out-Null
Check ((Assert-PrivateRoot $record -InspectContents) -eq $owned) 'Internal build junction rejected.'
$workspace = Join-Path $owned 'workspace'
New-Item -ItemType Directory -Path $workspace | Out-Null
$batch = Join-Path $workspace 'check-env.bat'
[IO.File]::WriteAllText($batch, "@echo off`r`nif defined PM_MODULE_DIR exit /b 9`r`nif not defined PM_PACKAGES_ROOT exit /b 8`r`nexit /b 0`r`n")
$previousModule = $env:PM_MODULE_DIR
$previousCache = $env:PM_PACKAGES_ROOT
try {
    $env:PM_MODULE_DIR = 'shared-module'
    $env:PM_PACKAGES_ROOT = 'shared-cache'
    Invoke-PrivateSetup $workspace $batch @()
    Check ($env:PM_MODULE_DIR -eq 'shared-module') 'Module environment was not restored.'
    Check ($env:PM_PACKAGES_ROOT -eq 'shared-cache') 'Packman environment was not restored.'
} finally {
    $env:PM_MODULE_DIR = $previousModule
    $env:PM_PACKAGES_ROOT = $previousCache
}
function Get-Process { [pscustomobject]@{ProcessName='kit'} }
Must-Fail { Assert-NoKitProcess } 'Running Kit accepted for removal.'
Remove-Item Function:\Get-Process
function Assert-NoKitProcess { }
Remove-Installation $record -Confirmed
Check (-not (Test-Path $owned)) 'Owned root was not removed.'
Check (-not (Test-Path $RecordPath)) 'Removed installation record remained.'
Check (Test-Path $external) 'Confirmed removal deleted legacy dependency.'
Write-Host "INSTALLATION_SAFETY_OK checks=$passed"
