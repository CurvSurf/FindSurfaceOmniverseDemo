param(
    [string]$KitExe = $env:KIT_EXE
)

if (-not $KitExe) {
    throw "Set KIT_EXE or pass -KitExe with the path to kit.exe."
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$AppFile = Join-Path $Root "source\apps\uiapp.debug-validation.kit"

& $KitExe $AppFile @args
