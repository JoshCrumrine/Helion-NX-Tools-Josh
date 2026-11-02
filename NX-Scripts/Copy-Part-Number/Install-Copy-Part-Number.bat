@echo off
REM Author:  jo388c
REM Created: 2026-10-29
REM Double-click to install Copy Part Number and Copy Part Name in NX for your Windows user (README.md).
REM Runs Install-Copy-Part-Number.ps1 past the PowerShell execution policy (a script that came in a
REM zip is often blocked otherwise) and keeps the window open so the result can be read.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Filter *.ps1 | Unblock-File" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Copy-Part-Number.ps1" %*
echo.
pause
