param(
    [string]$RootDir,
    [string]$InstallRoot,
    [switch]$KeepInstallRoot
)

$ErrorActionPreference = "Stop"

if (-not $RootDir) {
    $RootDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}
if (-not $InstallRoot) {
    $InstallRoot = Join-Path $env:TEMP "dictate-user-smoke"
}

$RootDir = [System.IO.Path]::GetFullPath($RootDir)
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$SourceDir = Join-Path $InstallRoot "source"
$ScriptsDir = Join-Path $SourceDir ".venv\Scripts"
$ArchivePath = Join-Path $env:TEMP ("dictate-user-smoke-" + [guid]::NewGuid().ToString("N") + ".zip")

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-PathExists {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path) "Expected path to exist: $Path"
}

function Assert-PathMissing {
    param([string]$Path)
    Assert-True (-not (Test-Path -LiteralPath $Path)) "Expected path to be absent: $Path"
}

function Invoke-Checked {
    param(
        [string]$Description,
        [string]$Exe,
        [string[]]$ArgumentList
    )
    Write-Step $Description
    & $Exe @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Invoke-DoctorSmoke {
    param(
        [string]$Description,
        [string[]]$ArgumentList
    )
    Write-Step $Description
    & (Join-Path $ScriptsDir "dictate.exe") @ArgumentList
    if (($LASTEXITCODE -ne 0) -and ($LASTEXITCODE -ne 2)) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
    if ($LASTEXITCODE -eq 2) {
        Write-Host "Doctor reported hosted-runner device limitations; continuing after install surface checks."
    }
}

function Get-StartMenuProgramsDir {
    if ($env:APPDATA) {
        return (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
    }
    return (Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs")
}

function Get-StartupShortcutPath {
    return (Join-Path (Join-Path (Get-StartMenuProgramsDir) "Startup") "Dictate.lnk")
}

function Get-StartMenuShortcutPath {
    return (Join-Path (Get-StartMenuProgramsDir) "Dictate.lnk")
}

function Get-UninstallKeyPath {
    return "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate"
}

function Read-Shortcut {
    param([string]$Path)
    $shell = New-Object -ComObject WScript.Shell
    return $shell.CreateShortcut($Path)
}

function Assert-ShortcutTargetsTray {
    param([string]$Path)
    Assert-PathExists $Path
    $shortcut = Read-Shortcut -Path $Path
    $expectedTarget = Join-Path $env:WINDIR "System32\wscript.exe"
    $expectedArguments = '"' + (Join-Path $ScriptsDir "dictate-tray.vbs") + '"'
    Assert-True ($shortcut.TargetPath -ieq $expectedTarget) "Shortcut $Path target was $($shortcut.TargetPath), expected $expectedTarget"
    Assert-True ($shortcut.Arguments -ieq $expectedArguments) "Shortcut $Path arguments were $($shortcut.Arguments), expected $expectedArguments"
    Assert-True ($shortcut.WorkingDirectory -ieq $SourceDir) "Shortcut $Path working directory was $($shortcut.WorkingDirectory), expected $SourceDir"
    Assert-True ($shortcut.Description -like "*Dictate*") "Shortcut $Path did not include a Dictate description"
}

function Assert-InstalledUserSurface {
    Write-Step "Checking installed Windows user surface"
    Assert-PathExists $SourceDir
    Assert-PathExists (Join-Path $ScriptsDir "dictate.exe")
    Assert-PathExists (Join-Path $ScriptsDir "dictate-tray.cmd")
    Assert-PathExists (Join-Path $ScriptsDir "dictate-tray.vbs")
    Assert-PathExists (Join-Path $ScriptsDir "dictate-daemon.cmd")
    Assert-PathExists (Join-Path $ScriptsDir "dictate-once.cmd")
    Assert-PathExists (Join-Path $ScriptsDir "dictate-controls.cmd")
    Assert-ShortcutTargetsTray -Path (Get-StartMenuShortcutPath)
    Assert-ShortcutTargetsTray -Path (Get-StartupShortcutPath)
    Assert-PathMissing (Join-Path (Get-StartMenuProgramsDir) "Dictate Controls.lnk")

    $keyPath = Get-UninstallKeyPath
    Assert-PathExists $keyPath
    $entry = Get-ItemProperty -Path $keyPath
    Assert-True ($entry.DisplayName -eq "Dictate") "Installed Apps display name was $($entry.DisplayName)"
    Assert-True ($entry.DisplayVersion -eq "2026.9.19") "Installed Apps version was $($entry.DisplayVersion)"
    Assert-True ($entry.Publisher -eq "Arc Forge Labs") "Installed Apps publisher was $($entry.Publisher)"
    Assert-True ($entry.InstallLocation -ieq $SourceDir) "InstallLocation was $($entry.InstallLocation), expected $SourceDir"
    Assert-True ($entry.UninstallString -like "*uninstall-windows.ps1*") "UninstallString did not reference uninstall-windows.ps1"

    $configPath = Join-Path $env:APPDATA "dictate\config.yaml"
    Assert-PathExists $configPath
}

function Assert-UninstalledUserSurface {
    Write-Step "Checking uninstall cleanup"
    Assert-PathMissing (Get-StartMenuShortcutPath)
    Assert-PathMissing (Get-StartupShortcutPath)
    Assert-PathMissing (Join-Path (Get-StartMenuProgramsDir) "Dictate Controls.lnk")
    Assert-PathMissing (Get-UninstallKeyPath)
    Assert-PathMissing (Join-Path $SourceDir ".venv")
}

try {
    Write-Step "Creating deterministic source archive"
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -Force -LiteralPath $ArchivePath
    }
    Invoke-Checked "Archive current Git tree" "git" @(
        "-C",
        $RootDir,
        "archive",
        "--format=zip",
        "--output=$ArchivePath",
        "--prefix=dictate-ci/",
        "HEAD"
    )

    if (Test-Path -LiteralPath $InstallRoot) {
        Write-Step "Removing previous smoke install root"
        Remove-Item -Recurse -Force -LiteralPath $InstallRoot
    }

    Invoke-Checked "Run hosted Windows bootstrap installer" "powershell" @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $RootDir "install.ps1"),
        "-InstallRoot",
        $InstallRoot,
        "-ArchiveUrl",
        $ArchivePath,
        "-NoPrepareTurbo",
        "-NoVerify",
        "-RecreateVenv"
    )
    Assert-InstalledUserSurface

    Invoke-Checked "Show installed Dictate version" (Join-Path $ScriptsDir "dictate.exe") @("--version")
    Invoke-DoctorSmoke "Run quick doctor" @("doctor", "--quick", "--type-backend", "pynput")

    Write-Step "Deleting shortcuts to verify doctor --fix repairs launchers"
    Remove-Item -Force -ErrorAction SilentlyContinue -LiteralPath (Get-StartMenuShortcutPath), (Get-StartupShortcutPath)
    Invoke-DoctorSmoke "Run doctor repair" @("doctor", "--quick", "--fix", "--type-backend", "pynput")
    Assert-ShortcutTargetsTray -Path (Get-StartMenuShortcutPath)
    Assert-ShortcutTargetsTray -Path (Get-StartupShortcutPath)

    Invoke-Checked "Run hosted Windows updater" "powershell" @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $RootDir "update.ps1"),
        "-InstallRoot",
        $InstallRoot,
        "-ArchiveUrl",
        $ArchivePath,
        "-NoPrepareTurbo",
        "-NoVerify",
        "-ForceStartup",
        "-RecreateVenv"
    )
    Assert-InstalledUserSurface

    Invoke-Checked "Run Windows uninstaller" "powershell" @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $SourceDir "uninstall-windows.ps1"),
        "-Quiet"
    )
    Assert-UninstalledUserSurface

    Write-Host "Dictate Windows user smoke passed."
} finally {
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -Force -LiteralPath $ArchivePath
    }
    if ((-not $KeepInstallRoot) -and (Test-Path -LiteralPath $InstallRoot)) {
        Remove-Item -Recurse -Force -LiteralPath $InstallRoot
    }
}
