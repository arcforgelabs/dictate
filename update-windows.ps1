param(
    [switch]$NoVerify,
    [switch]$NoPrepareTurbo,
    [switch]$NoShortcut,
    [switch]$NoStartup,
    [switch]$ForceStartup,
    [switch]$RecreateVenv,
    [switch]$SkipGitPull,
    [switch]$ForceCuda,
    [switch]$NoCuda
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

function Get-StartupShortcutPath {
    $programsDir = Get-StartMenuProgramsDir
    return (Join-Path (Join-Path $programsDir "Startup") "Dictate.lnk")
}

function Stop-DictateProcesses {
    $currentPid = $PID
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        $matches = @(Get-CimInstance Win32_Process |
            Where-Object {
                $_.ProcessId -ne $currentPid -and (
                    $_.Name -in @("Dictate.exe", "dictate.exe", "dictate-controls.exe", "dictate-ui-shell.exe", "dictate-engine.exe") -or
                    $_.ExecutablePath -like '*\Dictate\source\*' -or
                    $_.CommandLine -like '*dictate.exe* --type-backend pynput*' -or
                    $_.CommandLine -like '*pythonw.exe* -m dictate --type-backend pynput*' -or
                    $_.CommandLine -like '*dictate-daemon.cmd*' -or
                    $_.CommandLine -like '*dictate-controls*' -or
                    $_.CommandLine -like '*dictate-ui-shell.exe*' -or
                    $_.CommandLine -like '*dictate-engine.exe*'
                )
            })
        if ($matches.Count -eq 0) {
            return
        }
        foreach ($match in ($matches | Sort-Object ParentProcessId -Descending)) {
            Stop-Process -Id $match.ProcessId -Force -ErrorAction SilentlyContinue
        }
        foreach ($match in $matches) {
            Wait-Process -Id $match.ProcessId -Timeout 5 -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 500
    }
    $remaining = @(Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $currentPid -and (
                $_.Name -in @("Dictate.exe", "dictate.exe", "dictate-controls.exe", "dictate-ui-shell.exe", "dictate-engine.exe") -or
                $_.ExecutablePath -like '*\Dictate\source\*' -or
                $_.CommandLine -like '*dictate-ui-shell.exe*' -or
                $_.CommandLine -like '*dictate-engine.exe*'
            )
        })
    if ($remaining.Count -gt 0) {
        $details = ($remaining | ForEach-Object { "$($_.ProcessId):$($_.Name)" }) -join ", "
        throw "Could not stop running Dictate processes: $details"
    }
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
if ($NoStartup -or ((-not $ForceStartup) -and (-not (Test-Path (Get-StartupShortcutPath))))) { $installerArgs += "-NoStartup" }
if ($RecreateVenv) { $installerArgs += "-RecreateVenv" }
if ($ForceCuda) { $installerArgs += "-ForceCuda" }
if ($NoCuda) { $installerArgs += "-NoCuda" }

& powershell @installerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Dictate Windows update failed with exit code $LASTEXITCODE."
}
