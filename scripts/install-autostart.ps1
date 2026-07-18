# Install / remove a Startup shortcut for Usage Widget v2.
# Usage:
#   .\scripts\install-autostart.ps1
#   .\scripts\install-autostart.ps1 -Remove
#   .\scripts\install-autostart.ps1 -ExePath "C:\path\to\UsageWidget-v2.exe"

param(
    [string]$ExePath = "",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Usage Widget v2.lnk"

if ($Remove) {
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath -Force
        Write-Host "Removed: $shortcutPath"
    } else {
        Write-Host "No startup shortcut found."
    }
    exit 0
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ExePath) {
    $candidate = Join-Path $repoRoot "dist\UsageWidget-v2.exe"
    if (Test-Path $candidate) {
        $ExePath = $candidate
    } else {
        $ExePath = Join-Path $repoRoot "widget.py"
    }
}
$ExePath = (Resolve-Path $ExePath).Path

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ($ExePath.ToLower().EndsWith(".py")) {
    $pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($pythonw) {
        $shortcut.TargetPath = $pythonw.Source
    } else {
        $shortcut.TargetPath = (Get-Command python.exe).Source
    }
    $shortcut.Arguments = "`"$ExePath`""
    $shortcut.WorkingDirectory = Split-Path -Parent $ExePath
} else {
    $shortcut.TargetPath = $ExePath
    $shortcut.WorkingDirectory = Split-Path -Parent $ExePath
    $shortcut.Arguments = ""
}
$shortcut.WindowStyle = 7
$shortcut.Description = "Usage Widget v2"
$shortcut.Save()
Write-Host "Installed: $shortcutPath"
Write-Host "Target: $($shortcut.TargetPath) $($shortcut.Arguments)"
