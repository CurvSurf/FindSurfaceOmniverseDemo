function Resolve-FindSurfaceExtensionRoot {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$RequestedRoot
    )

    if ($RequestedRoot) {
        return (Resolve-Path $RequestedRoot).Path
    }

    $submoduleRoot = Join-Path $ProjectRoot "source\extensions\com.findsurface.bootstrap"
    if (Test-Path -LiteralPath (Join-Path $submoduleRoot "config\extension.toml") -PathType Leaf) {
        return (Resolve-Path $submoduleRoot).Path
    }

    $siblingRoot = Join-Path $ProjectRoot "FindSurfaceExtension"
    if (Test-Path -LiteralPath (Join-Path $siblingRoot "config\extension.toml") -PathType Leaf) {
        return (Resolve-Path $siblingRoot).Path
    }

    return (Resolve-Path $ProjectRoot).Path
}

function Get-FindSurfaceExtensionFolder {
    param([Parameter(Mandatory = $true)][string]$ExtensionRoot)

    if (Test-Path -LiteralPath (Join-Path $ExtensionRoot "config\extension.toml") -PathType Leaf) {
        return (Split-Path -Parent $ExtensionRoot)
    }

    return (Join-Path $ExtensionRoot "source\extensions")
}

function Get-FindSurfaceSdkPath {
    param([Parameter(Mandatory = $true)][string]$ExtensionRoot)

    return (Join-Path $ExtensionRoot "data\native\windows-x86_64\FindSurface.dll")
}

function Invoke-FindSurfaceSdkAcquisition {
    param([Parameter(Mandatory = $true)][string]$ExtensionRoot)

    $fetchTool = Join-Path $ExtensionRoot "tools\fetch_findsurface_sdk.py"
    if (-not (Test-Path -LiteralPath $fetchTool -PathType Leaf)) {
        throw "FindSurface SDK acquisition helper was not found: $fetchTool"
    }

    $python = $env:PYTHON
    if (-not $python) {
        $python = "python"
    }

    & $python $fetchTool --extension-root $ExtensionRoot --asset-key windows-x86_64
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download the FindSurface Windows SDK binary."
    }
}

function Ensure-FindSurfaceNativeRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$ExtensionRoot
    )

    $extFolder = Get-FindSurfaceExtensionFolder -ExtensionRoot $ExtensionRoot
    if (-not (Test-Path -LiteralPath $extFolder -PathType Container)) {
        throw "FindSurface extension folder was not found: $extFolder"
    }

    $sdkPath = Get-FindSurfaceSdkPath -ExtensionRoot $ExtensionRoot
    if (-not (Test-Path -LiteralPath $sdkPath -PathType Leaf)) {
        Write-Host "FindSurface SDK binary was not found; downloading it now: $sdkPath"
        Invoke-FindSurfaceSdkAcquisition -ExtensionRoot $ExtensionRoot
    }

    if (-not (Test-Path -LiteralPath $sdkPath -PathType Leaf)) {
        throw "FindSurface SDK binary is still missing after download: $sdkPath"
    }
}
