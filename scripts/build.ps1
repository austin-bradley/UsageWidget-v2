# Build UsageWidget-v2.exe (windowed one-file).
# Usage: .\scripts\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Get-Process UsageWidget-v2 -ErrorAction SilentlyContinue | Stop-Process -Force
python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller UsageWidget-v2.spec --noconfirm
$exe = Join-Path $root "dist\UsageWidget-v2.exe"
if (-not (Test-Path $exe)) {
    throw "Build failed: $exe not found"
}
$item = Get-Item $exe
Write-Host "Built $($item.FullName) ($([math]::Round($item.Length/1MB, 1)) MB) at $($item.LastWriteTime)"
