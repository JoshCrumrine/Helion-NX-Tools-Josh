@echo off
REM Author:  jo388c
REM Created: 2026-11-01
REM Double-click to remove Keep Sketch Selection from NX (README.md). Deletes only what
REM Install-Keep-Sketch-Selection.bat put in your NX startup folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Keep-Sketch-Selection.ps1" -Uninstall %*
echo.
pause
