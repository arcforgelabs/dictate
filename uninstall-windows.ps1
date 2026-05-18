param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Remove-IfExists {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -Force -Path $Path
    }
}

$programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (-not $env:APPDATA) {
    $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
}
$startupDir = Join-Path $programsDir "Startup"

Remove-IfExists -Path (Join-Path $programsDir "Dictate.lnk")
Remove-IfExists -Path (Join-Path $programsDir "Dictate Controls.lnk")
Remove-IfExists -Path (Join-Path $startupDir "Dictate.lnk")

$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate"
if (Test-Path $uninstallKey) {
    Remove-Item -Recurse -Force -Path $uninstallKey
}

if (-not $Quiet) {
    Write-Host "Dictate shortcuts and Installed Apps registration removed."
    Write-Host "Project files were left in place: $PSScriptRoot"
}
