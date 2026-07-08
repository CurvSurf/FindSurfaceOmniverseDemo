param(
    [string]$KitExe = $env:KIT_EXE,
    [string]$FindSurfaceExtensionRoot = $env:FINDSURFACE_EXTENSION_ROOT
)

if (-not $KitExe) {
    throw "Set KIT_EXE or pass -KitExe with the path to kit.exe."
}

. (Join-Path $PSScriptRoot "_findsurface_windows.ps1")

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$AppFile = Join-Path $Root "source\apps\findsurface.debug-validation.kit"
$FindSurfaceExtensionRoot = Resolve-FindSurfaceExtensionRoot -ProjectRoot $Root -RequestedRoot $FindSurfaceExtensionRoot
$ExtFolder = Get-FindSurfaceExtensionFolder -ExtensionRoot $FindSurfaceExtensionRoot
if (-not (Test-Path -LiteralPath $ExtFolder -PathType Container)) {
    throw "FindSurface extension folder was not found: $ExtFolder"
}
Ensure-FindSurfaceNativeRuntime -ProjectRoot $Root -ExtensionRoot $FindSurfaceExtensionRoot
$Validator = Join-Path $Root "tools\validate_ui_smoke.py"

$env:FINDSURFACE_EXTENSION_ROOT = $FindSurfaceExtensionRoot
& $KitExe $AppFile `
    --ext-folder $ExtFolder `
    --exec $Validator `
    --/crashreporter/gatherUserStory=0 `
    --/crashreporter/skipOldDumpUpload=1 `
    --/app/uploadDumpsOnStartup=0 `
    @args
