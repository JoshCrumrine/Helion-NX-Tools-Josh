<#
.SYNOPSIS
  Installs (or, with -Uninstall, removes) Keep Sketch Selection for NX 2506, for your Windows user
  only.

.DESCRIPTION
  In an NX sketch, the curves you selected stay selected after you apply a relation to them (Make
  Parallel, Make Equal, Convert To/From Reference, ...), so the next relation needs no new pick. See
  README.md in this folder.

  Installing copies one file, helion_keep_sketch_selection.py, to your personal NX startup folder,
  %LOCALAPPDATA%\Siemens\NX2506\startup, which the Helion NX launcher already registers with NX
  (it keeps NX_title.men there). NX runs it at startup.

  Nothing else changes: no environment variables, nothing on the network share, no other file in
  that folder. Restart NX afterwards. Run it again after changing the file in nx_startup.
  -Uninstall deletes exactly that file, plus the compiled copy of it that NX's Python keeps in
  startup\__pycache__.

.PARAMETER Uninstall
  Remove the file instead of installing it.

.PARAMETER ProfileDir
  Your NX user folder. Default: %LOCALAPPDATA%\Siemens\NX2506, where the Helion NX launcher keeps
  NX's user settings.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Install-Keep-Sketch-Selection.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Install-Keep-Sketch-Selection.ps1 -Uninstall
#>
# Author:  jo388c
# Created: 2026-11-01
param(
    [switch]$Uninstall,
    [string]$ProfileDir = (Join-Path $env:LOCALAPPDATA 'Siemens\NX2506')
)

$ErrorActionPreference = 'Stop'
$Name        = 'helion_keep_sketch_selection'
$SourceFile  = Join-Path $PSScriptRoot "nx_startup\$Name.py"
$StartupDir  = Join-Path $ProfileDir 'startup'
$StartupFile = Join-Path $StartupDir "$Name.py"
$CacheDir    = Join-Path $StartupDir '__pycache__'    # where NX's Python compiles $StartupFile to

function Stop-WithError([string]$Message) {
    Write-Host ''
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $ProfileDir -PathType Container)) {
    Stop-WithError ("NX user folder not found: $ProfileDir`n" +
        'Start NX once from the Helion NX launcher (it creates this folder), or pass -ProfileDir.')
}

if ($Uninstall) {
    $files = @($StartupFile)
    if (Test-Path -LiteralPath $CacheDir) {
        $files += @(Get-ChildItem -LiteralPath $CacheDir -Filter "$Name.*.pyc" | ForEach-Object { $_.FullName })
    }
    foreach ($file in $files) {
        if (Test-Path -LiteralPath $file) {
            Remove-Item -LiteralPath $file -Force
            Write-Host "Removed      $file"
        } else {
            Write-Host "Not present  $file"
        }
    }
    # Other startup scripts (Copy Part Number) share __pycache__; remove it only if it is empty.
    if ((Test-Path -LiteralPath $CacheDir) -and -not (Get-ChildItem -LiteralPath $CacheDir -Force)) {
        Remove-Item -LiteralPath $CacheDir -Force
        Write-Host "Removed      $CacheDir"
    }
    Write-Host ''
    Write-Host 'Keep Sketch Selection is uninstalled. Restart NX to stop it.'
} else {
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
        Stop-WithError "Missing file: $SourceFile"
    }
    if (-not (Test-Path -LiteralPath $StartupDir)) {
        New-Item -ItemType Directory -Path $StartupDir | Out-Null
    }
    Copy-Item -LiteralPath $SourceFile -Destination $StartupFile -Force

    Write-Host "Copied  $StartupFile"
    Write-Host ''
    Write-Host 'Keep Sketch Selection is installed. Restart NX, then in a sketch select two lines and'
    Write-Host 'click Make Parallel: the lines stay selected for the next relation.'
}

if (Get-Process -Name ugraf -ErrorAction SilentlyContinue) {
    Write-Host ''
    Write-Host 'NX is running: this takes effect the next time NX starts.' -ForegroundColor Yellow
}
