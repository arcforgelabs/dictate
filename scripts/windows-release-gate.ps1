# Dictate Windows release gate. Runs inside Windows as the signed-in user:
# removes any existing Dictate, installs the given setup.exe silently, checks
# the Installed Apps version, launches the app in the interactive session,
# waits for the engine's /api/health to report the expected version, then
# uninstalls. Used by scripts/windows-vm-release-gate.sh (over SSH) and by
# .github/workflows/windows-release-gate.yml (self-hosted runner on the VM).
param(
    [Parameter(Mandatory = $true)][string] $Installer,
    [Parameter(Mandatory = $true)][string] $ExpectedVersion,
    [int] $TimeoutSeconds = 300
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$taskName = 'DictateReleaseGate'
$handshake = Join-Path $env:LOCALAPPDATA 'dictate\ui-server.json'

function Step([string] $message) { Write-Output "==> $message" }

function Get-DictateEntry {
    $keys = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    Get-ItemProperty -Path $keys -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq 'Dictate' } |
        Select-Object -First 1
}

function Stop-Dictate {
    Get-Process -Name 'dictate-ui-shell', 'dictate-engine', 'Dictate' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Uninstall-Dictate($entry) {
    $command = [string] $entry.QuietUninstallString
    if (-not $command) { $command = [string] $entry.UninstallString }
    if (-not $command) { throw 'Dictate uninstall entry has no uninstall command' }
    $exe = if ($command -match '^"([^"]+)"') { $Matches[1] } else { ($command -split ' ')[0] }
    Start-Process -FilePath $exe -ArgumentList '/S' -Wait
    # NSIS copies its uninstaller to %TEMP% and returns early; wait for the
    # Installed Apps entry to disappear.
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-DictateEntry) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (Get-DictateEntry) { throw 'Dictate is still listed in Installed Apps after uninstall' }
}

function Remove-GateTask {
    schtasks.exe /Delete /TN $taskName /F 2>$null | Out-Null
}

try {
    Stop-Dictate
    $existing = Get-DictateEntry
    if ($existing) {
        Step "Removing existing Dictate $($existing.DisplayVersion)"
        Uninstall-Dictate $existing
    }
    Remove-Item -Force -ErrorAction SilentlyContinue $handshake

    Step "Installing $([IO.Path]::GetFileName($Installer)) silently"
    $install = Start-Process -FilePath $Installer -ArgumentList '/S' -Wait -PassThru
    if ($install.ExitCode -ne 0) { throw "installer exited with $($install.ExitCode)" }

    $entry = Get-DictateEntry
    if (-not $entry) { throw 'Dictate is not listed in Installed Apps after install' }
    if ($entry.DisplayVersion -ne $ExpectedVersion) {
        throw "Installed Apps reports $($entry.DisplayVersion), expected $ExpectedVersion"
    }
    Write-Output "Installed Apps: Dictate $($entry.DisplayVersion)"

    $installDir = [string] $entry.InstallLocation
    if (-not $installDir) {
        $uninstaller = [string] $entry.UninstallString
        if ($uninstaller -match '^"([^"]+)"') { $uninstaller = $Matches[1] }
        $installDir = Split-Path -Parent $uninstaller
    }
    $installDir = $installDir.Trim('"')
    $app = Get-ChildItem -Path $installDir -Filter '*.exe' -File |
        Where-Object { $_.Name -notmatch '^uninstall' } |
        Select-Object -First 1
    if (-not $app) { throw "no app executable in $installDir" }
    $engine = Get-ChildItem -Path $installDir -Recurse -Filter 'dictate-engine.exe' -File | Select-Object -First 1
    if (-not $engine) { throw "no dictate-engine.exe under $installDir" }
    Write-Output "App: $($app.FullName)"
    Write-Output "Engine: $($engine.FullName)"

    Step 'Launching Dictate in the signed-in desktop session'
    Remove-GateTask
    $run = '"' + $app.FullName + '"'
    schtasks.exe /Create /TN $taskName /TR $run /SC ONCE /ST 00:00 /IT /RL LIMITED /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'could not create the launch task' }
    schtasks.exe /Run /TN $taskName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'could not run the launch task' }

    Step "Waiting up to ${TimeoutSeconds}s for the engine to answer"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $handshake) {
            try {
                $url = ([Uri] (Get-Content -Raw $handshake | ConvertFrom-Json).url)
                $base = $url.GetLeftPart([UriPartial]::Authority)
                $health = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 5
                if ($health.status -eq 'ok') { break }
            } catch {
                $health = $null
            }
        }
        Start-Sleep -Seconds 3
    }
    if (-not $health) {
        $running = (Get-Process -Name 'dictate-ui-shell', 'dictate-engine' -ErrorAction SilentlyContinue).Name -join ', '
        throw "engine did not answer /api/health within ${TimeoutSeconds}s (running: $running)"
    }
    if ($health.version -ne $ExpectedVersion) {
        throw "running engine reports $($health.version), expected $ExpectedVersion"
    }
    Write-Output "Engine /api/health: ok, version $($health.version)"
    foreach ($name in 'dictate-ui-shell', 'dictate-engine') {
        if (-not (Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            throw "$name is not running after launch"
        }
    }
    Write-Output 'Window and engine processes are running'

    Step 'Uninstalling'
    Stop-Dictate
    Remove-GateTask
    Uninstall-Dictate (Get-DictateEntry)
    if (Test-Path $app.FullName) { throw "$($app.FullName) is still present after uninstall" }
    Write-Output 'Uninstalled: Installed Apps entry and app executable are gone'

    Write-Output "Dictate Windows release gate passed: $ExpectedVersion"
} finally {
    Remove-GateTask
}
