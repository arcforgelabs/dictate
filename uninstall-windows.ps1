param(
    [switch]$Quiet,
    [switch]$RemoveUserData
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

$venvDir = Join-Path $PSScriptRoot ".venv"
if (Test-Path $venvDir) {
    Remove-Item -Recurse -Force -Path $venvDir
}

$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) {
    $localAppData = Join-Path $HOME "AppData\Local"
}
$appData = $env:APPDATA
if (-not $appData) {
    $appData = Join-Path $HOME "AppData\Roaming"
}
$dataDir = Join-Path $localAppData "dictate"
$configDir = Join-Path $appData "dictate"

if ($RemoveUserData) {
    if (Test-Path $dataDir) {
        Remove-Item -Recurse -Force -Path $dataDir
    }
    if (Test-Path $configDir) {
        Remove-Item -Recurse -Force -Path $configDir
    }
}

if (-not $Quiet) {
    Write-Host "Dictate shortcuts, startup entry, app registration, and runtime venv removed."
    if ($RemoveUserData) {
        Write-Host "User config/data removed."
    } else {
        Write-Host "User config/data preserved. Re-run with -RemoveUserData to remove it."
    }
    Write-Host "Install source files were left in place: $PSScriptRoot"
}
