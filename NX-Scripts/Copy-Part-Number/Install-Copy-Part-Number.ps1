<#
.SYNOPSIS
  Installs (or, with -Uninstall, removes) Copy Part Number and Copy Part Name for NX 2506, for your
  Windows user only.

.DESCRIPTION
  Puts "Copy Part Number" and "Copy Part Name" on the right-click menu of components in the NX
  Assembly Navigator, and in the Edit menu. See README.md in this folder.

  Installing writes two files to your personal NX startup folder,
  %LOCALAPPDATA%\Siemens\NX2506\startup, which the Helion NX launcher already registers with NX
  (it keeps NX_title.men there):

    helion_copy_part_number.men  defines the two commands, which run copy_part_number.py and
                                 copy_part_name.py from THIS folder
    helion_copy_part_number.py   adds the commands to right-click menus

  Nothing else changes: no environment variables, nothing on the network share, no other file in
  that folder. Restart NX afterwards. Run it again after moving this folder or changing the files in
  nx_startup. -Uninstall deletes exactly those two files, plus the compiled copy of the second one
  that NX's Python keeps in startup\__pycache__.

.PARAMETER Uninstall
  Remove the files instead of installing them.

.PARAMETER ProfileDir
  Your NX user folder. Default: %LOCALAPPDATA%\Siemens\NX2506, where the Helion NX launcher keeps
  NX's user settings.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Install-Copy-Part-Number.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Install-Copy-Part-Number.ps1 -Uninstall
#>
# Author:  jo388c
# Created: 2026-10-29
param(
    [switch]$Uninstall,
    [string]$ProfileDir = (Join-Path $env:LOCALAPPDATA 'Siemens\NX2506')
)

$ErrorActionPreference = 'Stop'
$Name        = 'helion_copy_part_number'
$ToolDir     = $PSScriptRoot
$Actions     = [ordered]@{      # placeholder in the menu file template -> script its command runs
    '@COPY_PART_NUMBER_SCRIPT@' = (Join-Path $ToolDir 'copy_part_number.py')
    '@COPY_PART_NAME_SCRIPT@'   = (Join-Path $ToolDir 'copy_part_name.py')
}
$SourceDir   = Join-Path $ToolDir 'nx_startup'
$StartupDir  = Join-Path $ProfileDir 'startup'
$MenuFile    = Join-Path $StartupDir "$Name.men"
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
    $files = @($MenuFile, $StartupFile)
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
    # NX's Python made __pycache__ for the startup script; remove it only if nothing else is in it.
    if ((Test-Path -LiteralPath $CacheDir) -and -not (Get-ChildItem -LiteralPath $CacheDir -Force)) {
        Remove-Item -LiteralPath $CacheDir -Force
        Write-Host "Removed      $CacheDir"
    }
    Write-Host ''
    Write-Host 'Copy Part Number and Copy Part Name are uninstalled. Restart NX to drop them from the menus.'
} else {
    # The menu file names the scripts by their full paths, which an NX menu file cannot hold if they
    # have spaces or non-ASCII characters.
    if (@($Actions.Values) -match '[^\x21-\x7E]') {
        Stop-WithError ("This folder's path has a space or a non-ASCII character, which an NX menu " +
            "file cannot hold:`n  $ToolDir`n" +
            'Move the repo to a plain path such as C:\Code\Helion-NX-Tools and run this again.')
    }
    $template = Join-Path $SourceDir "$Name.men"
    foreach ($file in @($Actions.Values) + $template + (Join-Path $SourceDir "$Name.py")) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            Stop-WithError "Missing file: $file"
        }
    }
    $menu = [System.IO.File]::ReadAllText($template)
    foreach ($placeholder in $Actions.Keys) {
        if (-not $menu.Contains($placeholder)) {
            Stop-WithError "$placeholder not found in $template"
        }
        $menu = $menu.Replace($placeholder, $Actions[$placeholder])
    }

    if (-not (Test-Path -LiteralPath $StartupDir)) {
        New-Item -ItemType Directory -Path $StartupDir | Out-Null
    }
    [System.IO.File]::WriteAllText($MenuFile, $menu, [System.Text.Encoding]::ASCII)
    Copy-Item -LiteralPath (Join-Path $SourceDir "$Name.py") -Destination $StartupFile -Force

    Write-Host "Wrote   $MenuFile"
    foreach ($script in $Actions.Values) {
        Write-Host "        (runs $script)"
    }
    Write-Host "Copied  $StartupFile"
    Write-Host ''
    Write-Host 'Copy Part Number and Copy Part Name are installed. Restart NX, then right-click a'
    Write-Host 'component in the Assembly Navigator and choose either one (both are also in Menu > Edit).'
}

if (Get-Process -Name ugraf -ErrorAction SilentlyContinue) {
    Write-Host ''
    Write-Host 'NX is running: this takes effect the next time NX starts.' -ForegroundColor Yellow
}
