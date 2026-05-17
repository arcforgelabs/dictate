param(
    [string]$InstallRoot,
    [string]$ArchiveUrl = "https://github.com/arcforgelabs/dictate/archive/refs/heads/master.zip",
    [switch]$NoVerify,
    [switch]$NoPrepareTurbo,
    [switch]$NoShortcut,
    [switch]$RecreateVenv
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
$stagingRoot = Join-Path $env:TEMP ("dictate-install-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $stagingRoot "dictate.zip"

Write-Host "==> Installing Dictate to $installRootPath"
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
New-Item -ItemType Directory -Force -Path $installRootPath | Out-Null

try {
    Write-Host "==> Downloading $ArchiveUrl"
    Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $archivePath

    Write-Host "==> Expanding source archive"
    Expand-Archive -Force -Path $archivePath -DestinationPath $stagingRoot
    $expanded = Get-ChildItem -Path $stagingRoot -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "install-windows.ps1") } |
        Select-Object -First 1
    if (-not $expanded) {
        throw "Downloaded archive did not contain install-windows.ps1."
    }

    if (Test-Path $sourceDir) {
        Write-Host "==> Replacing existing managed source: $sourceDir"
        Remove-Item -Recurse -Force $sourceDir
    }
    Move-Item -Path $expanded.FullName -Destination $sourceDir

    $installerArgs = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $sourceDir "install-windows.ps1"))
    if ($NoVerify) { $installerArgs += "-NoVerify" }
    if ($NoPrepareTurbo) { $installerArgs += "-NoPrepareTurbo" }
    if ($NoShortcut) { $installerArgs += "-NoShortcut" }
    if ($RecreateVenv) { $installerArgs += "-RecreateVenv" }

    Write-Host "==> Running Dictate Windows installer"
    & powershell @installerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Dictate Windows installer failed with exit code $LASTEXITCODE."
    }
} finally {
    if (Test-Path $stagingRoot) {
        Remove-Item -Recurse -Force $stagingRoot
    }
}

Write-Host ""
Write-Host "Dictate install source: $sourceDir"
Write-Host "Start Dictate from the Start Menu shortcut named 'Dictate'."
