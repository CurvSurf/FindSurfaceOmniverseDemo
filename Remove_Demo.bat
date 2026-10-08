@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\manage_installation.ps1" -Action Remove %*
set "FSOD_EXIT=%ERRORLEVEL%"
pause
exit /b %FSOD_EXIT%
