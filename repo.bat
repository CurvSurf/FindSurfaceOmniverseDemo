@echo off

:: Set OMNI_REPO_ROOT early so `repo` bootstrapping can target the repository
:: root when writing out Python dependencies.
:: Use SETLOCAL and ENDLOCAL to constrain these variables to this batch file.
:: Use ENABLEDELAYEDEXPANSION to evaluate the value of PM_PACKAGES_ROOT
:: at execution time.
SETLOCAL ENABLEDELAYEDEXPANSION
set OMNI_REPO_ROOT="%~dp0"

:: Force Python to read UTF-8 config files independently of the user's Windows
:: ANSI code page. Some NVIDIA repo tool packages contain UTF-8 TOML files, and
:: Python otherwise uses locale encodings such as cp949 on non-English Windows.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Set Packman cache directory early if repo-cache.json is configured
:: so that the Packman Python version is not fetched from the web.
IF NOT EXIST "%~dp0repo-cache.json" goto :RepoCacheEnd

:: Read PM_PACKAGES_ROOT from repo-cache.json and make sure it is an absolute path (assume relative to the script directory).
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "$PM_PACKAGES_ROOT = (Get-Content '%~dp0repo-cache.json' | ConvertFrom-Json).PM_PACKAGES_ROOT; if ([System.IO.Path]::IsPathRooted($PM_PACKAGES_ROOT)) { Write-Output ('absolute;' + $PM_PACKAGES_ROOT) } else { Write-Output ('relative;' + $PM_PACKAGES_ROOT) }"`) do (
    for /f "tokens=1,2 delims=;" %%A in ("%%i") do (
        if /i "%%A" == "relative" (
            set PM_PACKAGES_ROOT=%~dp0%%B
        ) else (
            set PM_PACKAGES_ROOT=%%B
        )
    )
)

:RepoCacheEnd

if /I "%~1"=="launch" if not defined FINDSURFACE_APP_SDK_PATH (
    if not exist "%~dp0source\extensions\com.findsurface.bootstrap\config\extension.toml" (
        echo Initialize submodules and build the app before launching.
        exit /b 1
    )
    call "%~dp0tools\packman\python.bat" "%~dp0tools\update_sdk.py" --sdk-path "%~dp0source\extensions\com.findsurface.bootstrap\data\native\windows-x86_64\FindSurface.dll" --asset-key windows-x86_64
    if !errorlevel! neq 0 ( goto Error )
)

if /I "%~1"=="launch" if "%~2"=="" (
    call "%~dp0tools\packman\python.bat" "%~dp0tools\repoman\repoman.py" launch com.curvsurf.findsurface_omniverse_demo.kit
    if !errorlevel! neq 0 ( goto Error )
    goto Success
)

call "%~dp0tools\packman\python.bat" "%~dp0tools\repoman\repoman.py" %*
if %errorlevel% neq 0 ( goto Error )

:Success
ENDLOCAL
exit /b 0

:Error
ENDLOCAL
exit /b %errorlevel%
