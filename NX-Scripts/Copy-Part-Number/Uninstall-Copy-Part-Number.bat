@echo off
REM Author:  jo388c
REM Created: 2026-10-29
REM Double-click to remove Copy Part Number and Copy Part Name from NX (README.md). Deletes only what
REM Install-Copy-Part-Number.bat put in your NX startup folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Copy-Part-Number.ps1" -Uninstall %*
echo.
pause
