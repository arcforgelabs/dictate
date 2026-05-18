param(
    [switch]$NoVerify,
    [switch]$NoPrepareTurbo,
    [switch]$NoShortcut,
    [switch]$NoStartup,
    [switch]$RecreateVenv,
    [switch]$SkipGitPull
)

$ErrorActionPreference = "Stop"

function Get-StartMenuProgramsDir {
    $programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (-not $env:APPDATA) {
        $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
    }
    return $programsDir
}

function Remove-LegacyEntries {
    $programsDir = Get-StartMenuProgramsDir
    Remove-Item -Force -ErrorAction SilentlyContinue -Path (Join-Path $programsDir "Dictate Controls.lnk")
}

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

if ((-not $SkipGitPull) -and (Test-Path (Join-Path $PSScriptRoot ".git"))) {
    Write-Host "==> Updating source checkout"
    & git -C $PSScriptRoot pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "git pull failed with exit code $LASTEXITCODE."
    }
}

Remove-LegacyEntries
Stop-DictateProcesses

$installerArgs = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "install-windows.ps1"))
if ($NoVerify) { $installerArgs += "-NoVerify" }
if ($NoPrepareTurbo) { $installerArgs += "-NoPrepareTurbo" }
if ($NoShortcut) { $installerArgs += "-NoShortcut" }
if ($NoStartup) { $installerArgs += "-NoStartup" }
if ($RecreateVenv) { $installerArgs += "-RecreateVenv" }

& powershell @installerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Dictate Windows update failed with exit code $LASTEXITCODE."
}
