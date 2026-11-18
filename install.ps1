# install.ps1 - Install CryptomatteExtractor for the current user.
# Copies the exe to %LOCALAPPDATA%\Programs and adds a Start menu shortcut,
# so Windows lists it under "All apps" and it can be pinned to Start / taskbar.
# Run:  powershell -ExecutionPolicy Bypass -File install.ps1
# Uninstall: Settings > Apps > Installed apps, or run uninstall.ps1.

$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'dist\CryptomatteExtractor.exe'
if (-not (Test-Path $src)) { throw "Not found: $src  (run build.bat first)" }

$dir = Join-Path $env:LOCALAPPDATA 'Programs\CryptomatteExtractor'
New-Item -ItemType Directory -Force $dir | Out-Null
$exe = Join-Path $dir 'CryptomatteExtractor.exe'
Copy-Item $src $exe -Force

$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'Cryptomatte Extractor.lnk'
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sc.TargetPath = $exe
$sc.WorkingDirectory = $dir
$sc.IconLocation = "$exe,0"
$sc.Description = 'Split EXR / Cryptomatte layers for Photoshop'
$sc.Save()

# Register in Settings > Apps > Installed apps, with uninstall.ps1 as the uninstaller
$un = Join-Path $dir 'uninstall.ps1'
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') $un -Force
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CryptomatteExtractor'
New-Item -Force $reg | Out-Null
$vals = @{
    DisplayName     = 'Cryptomatte Extractor'
    DisplayIcon     = "$exe,0"
    InstallLocation = $dir
    Publisher       = 'UXBanos'
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$un`""
}
foreach ($k in $vals.Keys) { Set-ItemProperty $reg $k $vals[$k] }
Set-ItemProperty $reg NoModify 1 -Type DWord
Set-ItemProperty $reg NoRepair 1 -Type DWord

Write-Host "Installed: $exe"
Write-Host "Shortcut:  $lnk"
Write-Host "Open Start, search 'Cryptomatte Extractor', right-click > Pin to Start / Pin to taskbar."
