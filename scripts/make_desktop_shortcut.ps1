<#
.SYNOPSIS
  Drop a one-click Desktop shortcut that launches Chrome (or Brave) with CDP enabled
  and auto-opens the ThaiAI-Pass portal.

.DESCRIPTION
  Windows 10/11 only. The shortcut puts the user's browser on the right remote-debugging
  port (9222), uses a dedicated --user-data-dir (Chrome 136+ blocks remote debugging on
  the default profile), and pre-fills the ThaiAI-Pass URL so double-click = ready.

  - Auto-detects Chrome first, then Brave. Use -Browser to force one.
  - Edit the constants below to change the user-data-dir or the portal URL.

.PARAMETER Browser
  Optional. Force "chrome" or "brave". If omitted, the script picks the first one found
  in standard install locations.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make_desktop_shortcut.ps1
  # Auto-detect Chrome or Brave, drop shortcut on Desktop

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make_desktop_shortcut.ps1 -Browser chrome
  # Force Chrome even if Brave is also installed
#>

param(
    [ValidateSet("auto", "chrome", "brave")]
    [string]$Browser = "auto"
)

$ErrorActionPreference = "Stop"

# ── EDIT THESE IF YOU NEED TO OVERRIDE ──────────────────────────
$PortalUrl      = "https://de.aipass.net/chat"
$UserDataDir    = "C:\Temp\chrome-hermes"
$DebugPort      = 9222
$ShortcutName   = "ThaiAI-Pass Bridge"
# ────────────────────────────────────────────────────────────────

function Find-Executable {
    param([string]$Leaf, [string[]]$CandidatePaths)
    foreach ($p in $CandidatePaths) {
        if (Test-Path $p) { return $p }
    }
    # Fall back to Windows PATH lookup (resolves `where` style)
    $cmd = Get-Command $Leaf -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# Standard install locations for Chrome / Brave on Windows
$ChromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$BravePaths = @(
    "$env:ProgramFiles\BraveSoftware\Brave-Browser\Application\brave.exe",
    "${env:ProgramFiles(x86)}\BraveSoftware\Brave-Browser\Application\brave.exe"
)

$exe = $null
$label = ""

if ($Browser -eq "chrome" -or $Browser -eq "auto") {
    $exe = Find-Executable -Leaf "chrome.exe" -CandidatePaths $ChromePaths
    if ($exe) { $label = "Chrome" }
}

if (-not $exe -and ($Browser -eq "brave" -or $Browser -eq "auto")) {
    $exe = Find-Executable -Leaf "brave.exe" -CandidatePaths $BravePaths
    if ($exe) { $label = "Brave" }
}

if (-not $exe) {
    Write-Error "No Chromium-family browser found. Install Chrome or Brave, or pass -Browser with a path."
    exit 1
}

# Compose CDP args. Quote paths that may contain spaces.
$args = "--remote-debugging-port=$DebugPort --user-data-dir=`"$UserDataDir`" $PortalUrl"

# Create the .lnk
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"

$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath       = "`"$exe`""
$shortcut.Arguments        = $args
$shortcut.WorkingDirectory = Split-Path $exe -Parent
$shortcut.IconLocation     = "`"$exe`",0"
$shortcut.Description      = "Launch $label with CDP enabled and open ThaiAI-Pass chat"
$shortcut.WindowStyle      = 1   # normal window
$shortcut.Save()

Write-Host "Browser:   $label  ($exe)"
Write-Host "Shortcut:  $lnkPath"
Write-Host "URL:       $PortalUrl"
Write-Host "CDP port:  $DebugPort"
Write-Host "Profile:   $UserDataDir"
Write-Host ""
Write-Host "Double-click the shortcut to launch. First run: sign in once, then the session persists."