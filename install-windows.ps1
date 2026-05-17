param(
    [switch]$NoVerify,
    [switch]$NoPrepareTurbo,
    [switch]$NoShortcut,
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"

function Test-PythonVersion {
    param(
        [string]$Exe,
        [string[]]$ArgumentList
    )

    & $Exe @ArgumentList -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info < (3, 13) else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Resolve-Python {
    $candidates = @()

    if ($env:PYTHON) {
        $candidates += [pscustomobject]@{ Exe = $env:PYTHON; ArgumentList = @() }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += [pscustomobject]@{ Exe = $python.Source; ArgumentList = @() }
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3) {
        $candidates += [pscustomobject]@{ Exe = $python3.Source; ArgumentList = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += [pscustomobject]@{ Exe = $py.Source; ArgumentList = @("-3.12") }
        $candidates += [pscustomobject]@{ Exe = $py.Source; ArgumentList = @("-3.11") }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonVersion -Exe $candidate.Exe -ArgumentList $candidate.ArgumentList) {
            return $candidate
        }
    }

    throw "Python 3.11 or 3.12 was not found. Install Python from python.org or winget, then rerun this script."
}

function Invoke-Checked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [string]$Description
    )

    Write-Host "==> $Description"
    & $Exe @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Test-VcRuntime {
    $system32 = Join-Path $env:WINDIR "System32"
    $required = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    foreach ($dll in $required) {
        if (-not (Test-Path (Join-Path $system32 $dll))) {
            return $false
        }
    }
    return $true
}

function Ensure-VcRuntime {
    if (Test-VcRuntime) {
        Write-Host "==> Microsoft Visual C++ runtime already installed"
        return
    }

    $installer = Join-Path $env:TEMP "vc_redist.x64.exe"
    $url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    Write-Host "==> Installing Microsoft Visual C++ runtime"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer
    $process = Start-Process -FilePath $installer -ArgumentList "/install", "/quiet", "/norestart" -Wait -PassThru
    if (($process.ExitCode -ne 0) -and ($process.ExitCode -ne 3010)) {
        throw "Microsoft Visual C++ runtime install failed with exit code $($process.ExitCode)."
    }
}

function Get-AppDataConfigPath {
    $base = $env:APPDATA
    if (-not $base) {
        $base = Join-Path $HOME "AppData\Roaming"
    }
    return Join-Path $base "dictate\config.yaml"
}

function Seed-Config {
    $configPath = Get-AppDataConfigPath
    if (Test-Path $configPath) {
        Write-Host "==> Config already exists: $configPath"
        return
    }

    $defaultConfig = Join-Path $PSScriptRoot "config\default-config.yaml"
    $configDir = Split-Path -Parent $configPath
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    Copy-Item -Path $defaultConfig -Destination $configPath
    Write-Host "==> Seeded config: $configPath"
}

function Write-LauncherScripts {
    param([string]$ScriptsDir)

    $daemonPath = Join-Path $ScriptsDir "dictate-daemon.cmd"
    $oncePath = Join-Path $ScriptsDir "dictate-once.cmd"
    $controlsPath = Join-Path $ScriptsDir "dictate-controls.cmd"
    $trayPath = Join-Path $ScriptsDir "dictate-tray.cmd"
    $trayVbsPath = Join-Path $ScriptsDir "dictate-tray.vbs"

    Set-Content -Path $trayPath -Encoding ASCII -Value @(
        "@echo off",
        'set "SCRIPT_DIR=%~dp0"',
        '"%SCRIPT_DIR%dictate.exe" --type-backend pynput %*'
    )

    Set-Content -Path $daemonPath -Encoding ASCII -Value @(
        "@echo off",
        'set "SCRIPT_DIR=%~dp0"',
        '"%SCRIPT_DIR%dictate.exe" --no-tray --type-backend pynput %*'
    )

    Set-Content -Path $oncePath -Encoding ASCII -Value @(
        "@echo off",
        'set "SCRIPT_DIR=%~dp0"',
        '"%SCRIPT_DIR%dictate.exe" --once %*'
    )

    Set-Content -Path $controlsPath -Encoding ASCII -Value @(
        "@echo off",
        'set "SCRIPT_DIR=%~dp0"',
        'start "" "%SCRIPT_DIR%dictate-controls.exe" %*'
    )

    Set-Content -Path $trayVbsPath -Encoding ASCII -Value @(
        'Set shell = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)',
        'venvDir = fso.GetParentFolderName(scriptDir)',
        'shell.CurrentDirectory = fso.GetParentFolderName(venvDir)',
        'shell.Run """" & scriptDir & "\pythonw.exe"" -m dictate --type-backend pynput", 0, False'
    )

    Write-Host "==> Wrote launchers:"
    Write-Host "    $trayPath"
    Write-Host "    $trayVbsPath"
    Write-Host "    $daemonPath"
    Write-Host "    $oncePath"
    Write-Host "    $controlsPath"
}

function Install-StartMenuShortcut {
    param(
        [string]$TargetPath,
        [string]$WorkingDirectory
    )

    if ($NoShortcut) {
        return
    }

    $programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (-not $env:APPDATA) {
        $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
    }
    New-Item -ItemType Directory -Force -Path $programsDir | Out-Null

    $shortcutPath = Join-Path $programsDir "Dictate.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $iconPath = Join-Path $PSScriptRoot "assets\dictate-controls.ico"
    $shortcut.Description = "Start Dictate push-to-talk tray"
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Save()

    Write-Host "==> Installed Start Menu shortcut: $shortcutPath"
}

function Install-ControlsShortcut {
    param(
        [string]$TargetPath,
        [string]$WorkingDirectory
    )

    if ($NoShortcut) {
        return
    }

    $programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (-not $env:APPDATA) {
        $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
    }
    New-Item -ItemType Directory -Force -Path $programsDir | Out-Null

    $shortcutPath = Join-Path $programsDir "Dictate Controls.lnk"
    $iconPath = Join-Path $PSScriptRoot "assets\dictate-controls.ico"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = "Open Dictate configuration and recent history"
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Save()

    Write-Host "==> Installed Start Menu shortcut: $shortcutPath"
}

$pythonCommand = Resolve-Python
$venvDir = Join-Path $PSScriptRoot ".venv"
$scriptsDir = Join-Path $venvDir "Scripts"
$venvPython = Join-Path $scriptsDir "python.exe"

Ensure-VcRuntime

if ($RecreateVenv -and (Test-Path $venvDir)) {
    Write-Host "==> Removing existing virtual environment: $venvDir"
    Remove-Item -Recurse -Force $venvDir
}

if (-not (Test-Path $venvPython)) {
    Invoke-Checked -Exe $pythonCommand.Exe -ArgumentList @($pythonCommand.ArgumentList + @("-m", "venv", $venvDir)) -Description "Creating virtual environment"
}

Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip") -Description "Upgrading pip"
Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "pip", "install", "-e", "${PSScriptRoot}[windows]") -Description "Installing Dictate Windows package"

Seed-Config
Write-LauncherScripts -ScriptsDir $scriptsDir
Install-StartMenuShortcut -TargetPath (Join-Path $scriptsDir "dictate-tray.vbs") -WorkingDirectory $PSScriptRoot
Install-ControlsShortcut -TargetPath (Join-Path $scriptsDir "dictate-controls.exe") -WorkingDirectory $PSScriptRoot

if (-not $NoPrepareTurbo) {
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "dictate", "prepare-model", "--stt-backend", "faster-whisper", "--model", "turbo", "--device", "auto", "--compute-type", "int8") -Description "Preparing faster-whisper turbo model"
}

if (-not $NoVerify) {
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "dictate", "doctor", "--quick", "--type-backend", "pynput") -Description "Running Dictate doctor"
}

Write-Host ""
Write-Host "Dictate is installed."
Write-Host "Start push-to-talk with a Windows tray icon from the Start Menu shortcut named 'Dictate', or run:"
Write-Host "  .\.venv\Scripts\dictate-tray.cmd"
Write-Host ""
Write-Host "Headless push-to-talk daemon:"
Write-Host "  .\.venv\Scripts\dictate-daemon.cmd"
Write-Host ""
Write-Host "Control panel:"
Write-Host "  .\.venv\Scripts\dictate-controls.cmd"
Write-Host ""
Write-Host "One-shot mode:"
Write-Host "  .\.venv\Scripts\dictate-once.cmd"
