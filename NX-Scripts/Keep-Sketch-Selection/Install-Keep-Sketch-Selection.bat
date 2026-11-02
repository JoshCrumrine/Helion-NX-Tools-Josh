@echo off
REM Author:  jo388c
REM Created: 2026-11-01
REM Double-click to install Keep Sketch Selection in NX for your Windows user (README.md).
REM Runs Install-Keep-Sketch-Selection.ps1 past the PowerShell execution policy (a script that came
REM in a zip is often blocked otherwise) and keeps the window open so the result can be read.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Filter *.ps1 | Unblock-File" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Keep-Sketch-Selection.ps1" %*
echo.
pause
