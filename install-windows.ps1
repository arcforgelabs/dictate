param(
    [switch]$NoVerify,
    [switch]$NoPrepareTurbo,
    [switch]$NoShortcut,
    [switch]$NoStartup,
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

function Get-StartMenuProgramsDir {
    $programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (-not $env:APPDATA) {
        $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
    }
    return $programsDir
}

function Get-StartupDir {
    return (Join-Path (Get-StartMenuProgramsDir) "Startup")
}

function New-DictateShortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkingDirectory,
        [string]$Description
    )

    $iconPath = Join-Path $PSScriptRoot "assets\dictate.ico"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = $Description
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Save()
}

function Install-StartMenuShortcut {
    param(
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkingDirectory
    )

    $programsDir = Get-StartMenuProgramsDir
    New-Item -ItemType Directory -Force -Path $programsDir | Out-Null

    $shortcutPath = Join-Path $programsDir "Dictate.lnk"
    $legacyShortcutPath = Join-Path $programsDir "Dictate Controls.lnk"

    if ($NoShortcut) {
        Remove-Item -Force -ErrorAction SilentlyContinue -Path $shortcutPath, $legacyShortcutPath
        Write-Host "==> Removed Start Menu shortcuts"
        return
    }

    Remove-Item -Force -ErrorAction SilentlyContinue -Path $legacyShortcutPath
    New-DictateShortcut -ShortcutPath $shortcutPath -TargetPath $TargetPath -Arguments $Arguments -WorkingDirectory $WorkingDirectory -Description "Start Dictate push-to-talk tray"

    Write-Host "==> Installed Start Menu shortcut: $shortcutPath"
}

function Install-StartupShortcut {
    param(
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkingDirectory
    )

    if ($NoShortcut -or $NoStartup) {
        $startupDir = Get-StartupDir
        $shortcutPath = Join-Path $startupDir "Dictate.lnk"
        if (Test-Path $shortcutPath) {
            Remove-Item -Force $shortcutPath
            Write-Host "==> Removed startup shortcut: $shortcutPath"
        }
        return
    }

    $startupDir = Get-StartupDir
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null

    $shortcutPath = Join-Path $startupDir "Dictate.lnk"
    New-DictateShortcut -ShortcutPath $shortcutPath -TargetPath $TargetPath -Arguments $Arguments -WorkingDirectory $WorkingDirectory -Description "Start Dictate automatically at sign-in"

    Write-Host "==> Installed startup shortcut: $shortcutPath"
}

function Register-InstalledApp {
    param(
        [string]$InstallLocation,
        [string]$DisplayIcon
    )

    $keyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate"
    New-Item -Force -Path $keyPath | Out-Null
    New-ItemProperty -Force -Path $keyPath -Name "DisplayName" -Value "Dictate" -PropertyType String | Out-Null
    New-ItemProperty -Force -Path $keyPath -Name "DisplayVersion" -Value "2026.7.2-2" -PropertyType String | Out-Null
    New-ItemProperty -Force -Path $keyPath -Name "Publisher" -Value "Arc Forge Labs" -PropertyType String | Out-Null
    New-ItemProperty -Force -Path $keyPath -Name "InstallLocation" -Value $InstallLocation -PropertyType String | Out-Null
    if (Test-Path $DisplayIcon) {
        New-ItemProperty -Force -Path $keyPath -Name "DisplayIcon" -Value $DisplayIcon -PropertyType String | Out-Null
    }
    $uninstallScript = Join-Path $InstallLocation "uninstall-windows.ps1"
    if (Test-Path $uninstallScript) {
        $uninstallCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$uninstallScript`""
        New-ItemProperty -Force -Path $keyPath -Name "UninstallString" -Value $uninstallCommand -PropertyType String | Out-Null
        New-ItemProperty -Force -Path $keyPath -Name "QuietUninstallString" -Value "$uninstallCommand -Quiet" -PropertyType String | Out-Null
    }
    New-ItemProperty -Force -Path $keyPath -Name "NoModify" -Value 1 -PropertyType DWord | Out-Null
    New-ItemProperty -Force -Path $keyPath -Name "NoRepair" -Value 1 -PropertyType DWord | Out-Null
    Write-Host "==> Registered Dictate in Windows Installed Apps"
}

function Normalize-PathForCompare {
    param([string]$Path)
    if (-not $Path) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($Path).TrimEnd("\").ToLowerInvariant()
    } catch {
        return $Path.TrimEnd("\").ToLowerInvariant()
    }
}

function Remove-StaleUserInstallSurface {
    param([string]$CurrentInstallLocation)

    $currentInstall = Normalize-PathForCompare -Path $CurrentInstallLocation
    $shell = $null
    try {
        $shell = New-Object -ComObject WScript.Shell
    } catch {
        Write-Host "==> Could not inspect Windows shortcuts for stale Dictate entries"
    }

    $profilesRoot = Join-Path $env:SystemDrive "Users"
    if (Test-Path $profilesRoot) {
        Get-ChildItem -Path $profilesRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notin @("Public", "Default", "Default User", "All Users") } |
            ForEach-Object {
                $profile = $_.FullName
                $programsDir = Join-Path $profile "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
                $startupDir = Join-Path $programsDir "Startup"
                $legacyShortcut = Join-Path $programsDir "Dictate Controls.lnk"
                if (Test-Path -LiteralPath $legacyShortcut) {
                    Remove-Item -Force -LiteralPath $legacyShortcut -ErrorAction SilentlyContinue
                    Write-Host "==> Removed stale Dictate shortcut: $legacyShortcut"
                }

                foreach ($shortcutPath in @(
                    (Join-Path $programsDir "Dictate.lnk"),
                    (Join-Path $startupDir "Dictate.lnk")
                )) {
                    if (-not (Test-Path -LiteralPath $shortcutPath)) {
                        continue
                    }
                    $removeShortcut = $false
                    if ($shell) {
                        $shortcut = $shell.CreateShortcut($shortcutPath)
                        $workingDirectory = Normalize-PathForCompare -Path $shortcut.WorkingDirectory
                        $argumentTarget = ""
                        if ($shortcut.Arguments -match '"([^"]+dictate-tray\.vbs)"') {
                            $argumentTarget = $matches[1]
                        }
                        if (
                            ($workingDirectory -and ($workingDirectory -ne $currentInstall)) -or
                            ($argumentTarget -and (-not (Test-Path -LiteralPath $argumentTarget)))
                        ) {
                            $removeShortcut = $true
                        }
                    } else {
                        $removeShortcut = $true
                    }
                    if ($removeShortcut) {
                        Remove-Item -Force -LiteralPath $shortcutPath -ErrorAction SilentlyContinue
                        Write-Host "==> Removed stale Dictate shortcut: $shortcutPath"
                    }
                }

                $hostedSource = Join-Path $profile "AppData\Local\Dictate\source"
                $hostedRoot = Join-Path $profile "AppData\Local\Dictate"
                if (
                    (Test-Path -LiteralPath (Join-Path $hostedSource "install-windows.ps1")) -and
                    ((Normalize-PathForCompare -Path $hostedSource) -ne $currentInstall)
                ) {
                    Remove-Item -Recurse -Force -LiteralPath $hostedRoot -ErrorAction SilentlyContinue
                    Write-Host "==> Removed stale Dictate managed source: $hostedRoot"
                }
            }
    }

    Get-ChildItem Registry::HKEY_USERS -ErrorAction SilentlyContinue | ForEach-Object {
        $keyPath = Join-Path $_.PSPath "Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate"
        if (Test-Path $keyPath) {
            $entry = Get-ItemProperty -Path $keyPath
            if ((Normalize-PathForCompare -Path $entry.InstallLocation) -ne $currentInstall) {
                Remove-Item -Recurse -Force -Path $keyPath -ErrorAction SilentlyContinue
                Write-Host "==> Removed stale Dictate Installed Apps entry"
            }
        }
    }
}

$pythonCommand = Resolve-Python
$venvDir = Join-Path $PSScriptRoot ".venv"
$scriptsDir = Join-Path $venvDir "Scripts"
$venvPython = Join-Path $scriptsDir "python.exe"

Remove-StaleUserInstallSurface -CurrentInstallLocation $PSScriptRoot
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
$trayVbs = Join-Path $scriptsDir "dictate-tray.vbs"
$wscript = Join-Path $env:WINDIR "System32\wscript.exe"
$trayArgs = "`"$trayVbs`""
Install-StartMenuShortcut -TargetPath $wscript -Arguments $trayArgs -WorkingDirectory $PSScriptRoot
Install-StartupShortcut -TargetPath $wscript -Arguments $trayArgs -WorkingDirectory $PSScriptRoot
Register-InstalledApp -InstallLocation $PSScriptRoot -DisplayIcon (Join-Path $PSScriptRoot "assets\dictate.ico")

if (-not $NoPrepareTurbo) {
    # Omit --model so prepare-model resolves the hardware-aware local default
    # (turbo on capable hardware, small on a weak CPU) instead of forcing turbo.
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "dictate", "prepare-model", "--stt-backend", "faster-whisper", "--device", "auto", "--compute-type", "int8") -Description "Preparing faster-whisper model"
}

if (-not $NoVerify) {
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "dictate", "doctor", "--quick", "--type-backend", "pynput") -Description "Running Dictate doctor"
}

Write-Host ""
Write-Host "Dictate is installed."
if ($NoShortcut -or $NoStartup) {
    Write-Host "Dictate startup shortcut was not installed."
} else {
    Write-Host "Dictate starts automatically when you sign in."
}
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
