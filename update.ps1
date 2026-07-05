param(
    [string]$InstallRoot,
    [string]$ArchiveUrl,
    [switch]$NoVerify,
    [switch]$NoPrepareTurbo,
    [switch]$NoShortcut,
    [switch]$NoStartup,
    [switch]$ForceStartup,
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"
$DictateVersion = "2026.7.4"

if (-not $ArchiveUrl) {
    $ArchiveUrl = "https://github.com/arcforgelabs/dictate/archive/refs/tags/v$DictateVersion.zip"
}

if (-not $InstallRoot) {
    $currentDirectory = [System.IO.Directory]::GetCurrentDirectory()
    $candidateSource = Join-Path $currentDirectory "source"
    if (
        (Test-Path (Join-Path $candidateSource "update-windows.ps1")) -and
        (Test-Path (Join-Path $candidateSource "pyproject.toml")) -and
        (Test-Path (Join-Path $candidateSource "src\dictate"))
    ) {
        $InstallRoot = $currentDirectory
    } else {
        $base = $env:LOCALAPPDATA
        if (-not $base) {
            $base = Join-Path $HOME "AppData\Local"
        }
        $InstallRoot = Join-Path $base "Dictate"
    }
}

$installRootPath = [System.IO.Path]::GetFullPath($InstallRoot)
$sourceDir = Join-Path $installRootPath "source"
$stagingRoot = Join-Path $env:TEMP ("dictate-update-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $stagingRoot "dictate.zip"

function Stop-DictateProcesses {
    $currentPid = $PID
    $matches = Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $currentPid -and (
                $_.Name -in @("dictate.exe", "dictate-controls.exe") -or
                $_.CommandLine -like '*dictate.exe* --type-backend pynput*' -or
                $_.CommandLine -like '*pythonw.exe* -m dictate --type-backend pynput*' -or
                $_.CommandLine -like '*dictate-daemon.cmd*' -or
                $_.CommandLine -like '*dictate-controls*'
            )
        }
    foreach ($match in $matches) {
        Stop-Process -Id $match.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "==> Updating Dictate in $installRootPath"
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
New-Item -ItemType Directory -Force -Path $installRootPath | Out-Null

try {
    if (Test-Path -LiteralPath $ArchiveUrl) {
        Write-Host "==> Copying local archive $ArchiveUrl"
        Copy-Item -Force -LiteralPath $ArchiveUrl -Destination $archivePath
    } else {
        Write-Host "==> Downloading $ArchiveUrl"
        Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $archivePath
    }

    Write-Host "==> Expanding source archive"
    Expand-Archive -Force -Path $archivePath -DestinationPath $stagingRoot
    $expanded = Get-ChildItem -Path $stagingRoot -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "update-windows.ps1") } |
        Select-Object -First 1
    if (-not $expanded) {
        throw "Downloaded archive did not contain update-windows.ps1."
    }

    if (Test-Path $sourceDir) {
        Stop-DictateProcesses
        Write-Host "==> Replacing existing managed source: $sourceDir"
        Remove-Item -Recurse -Force $sourceDir
    }
    Move-Item -Path $expanded.FullName -Destination $sourceDir

    $updaterArgs = @(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $sourceDir "update-windows.ps1"),
        "-SkipGitPull"
    )
    if ($NoVerify) { $updaterArgs += "-NoVerify" }
    if ($NoPrepareTurbo) { $updaterArgs += "-NoPrepareTurbo" }
    if ($NoShortcut) { $updaterArgs += "-NoShortcut" }
    if ($NoStartup) { $updaterArgs += "-NoStartup" }
    if ($ForceStartup) { $updaterArgs += "-ForceStartup" }
    if ($RecreateVenv) { $updaterArgs += "-RecreateVenv" }

    Write-Host "==> Running Dictate Windows updater"
    & powershell @updaterArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Dictate Windows updater failed with exit code $LASTEXITCODE."
    }
    $dictateExe = Join-Path $installRootPath ".venv\Scripts\dictate.exe"
    if (Test-Path $dictateExe) {
        & $dictateExe set-installed-package-version $DictateVersion | Out-Null
    }
} finally {
    if (Test-Path $stagingRoot) {
        Remove-Item -Recurse -Force $stagingRoot
    }
}

Write-Host ""
Write-Host "Dictate updated from: $sourceDir"
