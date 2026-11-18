# uninstall.ps1 - Remove CryptomatteExtractor installed by install.ps1.
# Also runs from Settings > Apps > Installed apps > Uninstall.
# Run:  powershell -ExecutionPolicy Bypass -File uninstall.ps1

$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'Programs\CryptomatteExtractor'
$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'Cryptomatte Extractor.lnk'
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CryptomatteExtractor'

Get-Process CryptomatteExtractor -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500  # let Windows release the exe file

foreach ($p in $lnk, $reg, $dir) {
    if (Test-Path $p) { Remove-Item $p -Recurse -Force; Write-Host "Removed: $p" }
}
Write-Host "CryptomatteExtractor uninstalled. Taskbar pins can be removed with right-click > Unpin."
