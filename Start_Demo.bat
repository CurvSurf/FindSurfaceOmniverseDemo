@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\manage_installation.ps1" -Action Start %*
set "FSOD_EXIT=%ERRORLEVEL%"
if not "%FSOD_EXIT%"=="0" pause
exit /b %FSOD_EXIT%
