param(
    [string]$InstallRoot,
    [switch]$Quiet,
    [switch]$RemoveUserData
)

$ErrorActionPreference = "Stop"

if (-not $InstallRoot) {
    $base = $env:LOCALAPPDATA
    if (-not $base) {
        $base = Join-Path $HOME "AppData\Local"
    }
    $InstallRoot = Join-Path $base "Dictate"
}

$installRootPath = [System.IO.Path]::GetFullPath($InstallRoot)
$sourceDir = Join-Path $installRootPath "source"
$uninstaller = Join-Path $sourceDir "uninstall-windows.ps1"

if (Test-Path $uninstaller) {
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $uninstaller)
    if ($Quiet) { $args += "-Quiet" }
    if ($RemoveUserData) { $args += "-RemoveUserData" }
    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "Dictate Windows uninstaller failed with exit code $LASTEXITCODE."
    }
} else {
    if (-not $Quiet) {
        Write-Host "Dictate source uninstaller not found: $uninstaller"
        Write-Host "Removing known Start Menu, startup, and Installed Apps entries."
    }
    $programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (-not $env:APPDATA) {
        $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
    }
    Remove-Item -Force -ErrorAction SilentlyContinue -Path `
        (Join-Path $programsDir "Dictate.lnk"), `
        (Join-Path $programsDir "Dictate Controls.lnk"), `
        (Join-Path $programsDir "Startup\Dictate.lnk")
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate"
}

if (Test-Path $installRootPath) {
    Remove-Item -Recurse -Force -Path $installRootPath
}

if (-not $Quiet) {
    Write-Host "Dictate removed from: $installRootPath"
}
