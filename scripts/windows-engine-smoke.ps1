# Cold-start smoke for the built Windows engine.
#
# Starts the staged engine the way the Tauri shell does (`--no-tray` with
# DICTATE_UI_SERVER=1 and the bundled model paths), against a throwaway
# LOCALAPPDATA/APPDATA, and measures:
#   - time from process start to the ui-server.json handshake
#   - time from process start to the first authenticated GET /api/state
# It also reports the engine folder's file count, size and longest path, so a
# build shows what the installed layout costs.
#
# The shell waits 8 s for the handshake (ensure_engine in ui-shell/src-tauri/src/lib.rs);
# a slower start is reported as a warning, not a failure.
#
# Usage:
#   .\scripts\windows-engine-smoke.ps1 -EngineDir ui-shell\src-tauri\engine
#   .\scripts\windows-engine-smoke.ps1 -EngineDir <dir> -Runs 3 -JsonPath smoke.json

[CmdletBinding()]
param(
    [string]$EngineDir = "ui-shell\src-tauri\engine",
    [int]$Runs = 2,
    [int]$TimeoutSeconds = 180,
    [string]$Label = "",
    [string]$SummaryPath = $env:GITHUB_STEP_SUMMARY,
    [string]$JsonPath = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

$ShellHandshakeWaitMs = 8000

$EngineDir = (Resolve-Path $EngineDir).Path
$EngineExe = Join-Path $EngineDir "dictate-engine.exe"
if (-not (Test-Path $EngineExe -PathType Leaf)) {
    throw "No engine at $EngineExe"
}
$Layout = if (Test-Path (Join-Path $EngineDir "_internal") -PathType Container) { "onedir" } else { "onefile" }

function Format-MB([long]$Bytes) {
    return "{0:N1} MB" -f ($Bytes / 1MB)
}

function Get-Inventory {
    param([Parameter(Mandatory = $true)][string]$Dir)

    $prefix = $Dir.TrimEnd("\") + "\"
    $files = @(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force)
    $runtime = @($files | Where-Object {
            $rel = $_.FullName.Substring($prefix.Length)
            $rel -eq "dictate-engine.exe" -or $rel.StartsWith("_internal\")
        })
    $models = @($files | Where-Object { $_.FullName.Substring($prefix.Length).StartsWith("models\") })
    $longest = $files |
        ForEach-Object { "engine\" + $_.FullName.Substring($prefix.Length) } |
        Sort-Object Length -Descending |
        Select-Object -First 1
    $sum = { param($set) [long](($set | Measure-Object -Property Length -Sum).Sum) }

    $internalTop = @()
    $internal = Join-Path $Dir "_internal"
    if (Test-Path $internal -PathType Container) {
        $internalPrefix = $internal + "\"
        $internalTop = @($runtime |
                Where-Object { $_.FullName.StartsWith($internalPrefix) } |
                Group-Object { ($_.FullName.Substring($internalPrefix.Length) -split "\\")[0] } |
                ForEach-Object {
                    [pscustomobject]@{
                        name = $_.Name
                        files = $_.Count
                        bytes = [long](($_.Group | Measure-Object -Property Length -Sum).Sum)
                    }
                } |
                Sort-Object bytes -Descending |
                Select-Object -First 12)
    }
    $extensions = @($runtime |
            Group-Object { if ($_.Extension) { $_.Extension.ToLowerInvariant() } else { "(none)" } } |
            ForEach-Object {
                [pscustomobject]@{
                    extension = $_.Name
                    files = $_.Count
                    bytes = [long](($_.Group | Measure-Object -Property Length -Sum).Sum)
                }
            } |
            Sort-Object files -Descending |
            Select-Object -First 12)

    return [pscustomobject]@{
        totalFiles = $files.Count
        totalBytes = & $sum $files
        runtimeFiles = $runtime.Count
        runtimeBytes = & $sum $runtime
        modelFiles = $models.Count
        modelBytes = & $sum $models
        longestPath = [string]$longest
        longestPathLength = ([string]$longest).Length
        internalTop = $internalTop
        runtimeExtensions = $extensions
    }
}

function Stop-EngineTree([int]$ProcessId) {
    & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
}

function Show-EngineLogs([string]$Root) {
    Get-ChildItem -LiteralPath $Root -Recurse -File -Include *.log, *.txt -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host "----- $($_.FullName)"
            Get-Content -LiteralPath $_.FullName -Tail 80 -ErrorAction SilentlyContinue | Write-Host
        }
}

function Invoke-ColdStart([int]$Run) {
    $tempBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
    $root = Join-Path $tempBase ("dictate-engine-smoke-" + [guid]::NewGuid().ToString("N"))
    $local = Join-Path $root "Local"
    $roaming = Join-Path $root "Roaming"
    New-Item -ItemType Directory -Force -Path $local, $roaming | Out-Null
    $handshakePath = Join-Path $local "dictate\ui-server.json"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $EngineExe
    $psi.Arguments = "--no-tray"
    $psi.WorkingDirectory = $EngineDir
    $psi.UseShellExecute = $false
    # Mirror spawn_engine() in ui-shell/src-tauri/src/lib.rs.
    $psi.EnvironmentVariables["LOCALAPPDATA"] = $local
    $psi.EnvironmentVariables["APPDATA"] = $roaming
    $psi.EnvironmentVariables["DICTATE_UI_SERVER"] = "1"
    $psi.EnvironmentVariables["PYANNOTE_METRICS_ENABLED"] = "0"
    $psi.EnvironmentVariables["HF_HUB_DISABLE_TELEMETRY"] = "1"
    $psi.EnvironmentVariables["ORT_DISABLE_TELEMETRY"] = "1"
    $parakeet = Join-Path $EngineDir "models\parakeet-tdt-0.6b-v2-onnx"
    if (Test-Path (Join-Path $parakeet "config.json")) {
        $psi.EnvironmentVariables["DICTATE_PARAKEET_MODEL_PATH"] = $parakeet
    }
    $pyannote = Join-Path $EngineDir "models\pyannote-speaker-diarization-community-1"
    if (Test-Path (Join-Path $pyannote "config.yaml")) {
        $psi.EnvironmentVariables["DICTATE_PYANNOTE_MODEL_PATH"] = $pyannote
    }

    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $process = [System.Diagnostics.Process]::Start($psi)
    $handshakeMs = $null
    $stateMs = $null
    $processCount = $null
    $failure = $null
    try {
        $deadline = $TimeoutSeconds * 1000
        $handshake = $null
        while ($clock.ElapsedMilliseconds -lt $deadline) {
            if ($process.HasExited) {
                $failure = "engine exited with code $($process.ExitCode) before writing the handshake"
                break
            }
            if (Test-Path -LiteralPath $handshakePath) {
                try {
                    $candidate = Get-Content -Raw -LiteralPath $handshakePath | ConvertFrom-Json
                    if ($candidate.url -and $candidate.token) {
                        $handshake = $candidate
                        $handshakeMs = $clock.ElapsedMilliseconds
                        break
                    }
                } catch {
                    # The engine writes the file in place; retry until it parses.
                }
            }
            Start-Sleep -Milliseconds 50
        }
        if (-not $handshake -and -not $failure) {
            $failure = "no handshake at $handshakePath within ${TimeoutSeconds}s"
        }

        if ($handshake) {
            $base = ([Uri]$handshake.url).GetLeftPart([UriPartial]::Authority)
            $headers = @{ Authorization = "Bearer $($handshake.token)" }
            while ($clock.ElapsedMilliseconds -lt $deadline) {
                try {
                    $response = Invoke-WebRequest -UseBasicParsing -Uri "$base/api/state" -Headers $headers -TimeoutSec 120
                    if ($response.StatusCode -eq 200) {
                        $null = $response.Content | ConvertFrom-Json
                        $stateMs = $clock.ElapsedMilliseconds
                        break
                    }
                } catch {
                    if ($process.HasExited) {
                        $failure = "engine exited with code $($process.ExitCode) before /api/state answered"
                        break
                    }
                }
                Start-Sleep -Milliseconds 100
            }
            if ($null -eq $stateMs -and -not $failure) {
                $failure = "authenticated GET /api/state did not answer within ${TimeoutSeconds}s"
            }
            $processCount = @(Get-Process -Name "dictate-engine" -ErrorAction SilentlyContinue).Count
        }
    } finally {
        if (-not $process.HasExited) {
            Stop-EngineTree $process.Id
            $null = $process.WaitForExit(15000)
        }
        if ($failure) {
            Write-Host "::error::run ${Run}: $failure"
            Show-EngineLogs $root
        }
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root
    }

    return [pscustomobject]@{
        run = $Run
        handshakeMs = $handshakeMs
        firstStateMs = $stateMs
        engineProcesses = $processCount
        failure = $failure
    }
}

# Stop leftover engines so they cannot skew the timings or the process count.
Get-Process -Name "dictate-engine" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "engine: $EngineExe ($Layout)"
$inventory = Get-Inventory -Dir $EngineDir
$results = @()
for ($i = 1; $i -le $Runs; $i++) {
    Write-Host "cold start run $i of $Runs"
    $result = Invoke-ColdStart -Run $i
    $results += $result
    Write-Host ("  handshake: {0} ms, first /api/state: {1} ms, engine processes: {2}" -f `
            $result.handshakeMs, $result.firstStateMs, $result.engineProcesses)
}

$report = [pscustomobject]@{
    label = $Label
    layout = $Layout
    engine = $EngineExe
    runs = $results
    inventory = $inventory
}
if ($JsonPath) {
    $report | ConvertTo-Json -Depth 6 | Set-Content -Path $JsonPath -Encoding UTF8
}

$title = if ($Label) { "Windows engine cold start ($Layout, $Label)" } else { "Windows engine cold start ($Layout)" }
$lines = @(
    "### $title",
    "",
    "| Run | Handshake | First authenticated /api/state | dictate-engine processes |",
    "| --- | ---: | ---: | ---: |"
)
foreach ($result in $results) {
    $handshakeText = if ($null -ne $result.handshakeMs) { "{0:N2} s" -f ($result.handshakeMs / 1000) } else { "failed" }
    $stateText = if ($null -ne $result.firstStateMs) { "{0:N2} s" -f ($result.firstStateMs / 1000) } else { "failed" }
    $lines += "| $($result.run) | $handshakeText | $stateText | $($result.engineProcesses) |"
}
$lines += @(
    "",
    "| Engine folder | Files | Size |",
    "| --- | ---: | ---: |",
    "| Runtime (exe + _internal) | $($inventory.runtimeFiles) | $(Format-MB $inventory.runtimeBytes) |",
    "| Models | $($inventory.modelFiles) | $(Format-MB $inventory.modelBytes) |",
    "| Total | $($inventory.totalFiles) | $(Format-MB $inventory.totalBytes) |",
    "",
    "Longest path ($($inventory.longestPathLength) chars): ``$($inventory.longestPath)``"
)
if ($inventory.internalTop.Count -gt 0) {
    $lines += @("", "| _internal entry | Files | Size |", "| --- | ---: | ---: |")
    foreach ($entry in $inventory.internalTop) {
        $lines += "| $($entry.name) | $($entry.files) | $(Format-MB $entry.bytes) |"
    }
}
$lines += @("", "| Runtime file type | Files | Size |", "| --- | ---: | ---: |")
foreach ($entry in $inventory.runtimeExtensions) {
    $lines += "| $($entry.extension) | $($entry.files) | $(Format-MB $entry.bytes) |"
}
$markdown = ($lines -join "`n") + "`n"
Write-Host $markdown
if ($SummaryPath) {
    Add-Content -Path $SummaryPath -Value $markdown -Encoding UTF8
}

$failed = @($results | Where-Object { $_.failure })
if ($failed.Count -gt 0) {
    throw "Windows engine smoke failed: $(($failed | ForEach-Object { "run $($_.run): $($_.failure)" }) -join '; ')"
}
$slow = @($results | Where-Object { $_.handshakeMs -gt $ShellHandshakeWaitMs })
if ($slow.Count -gt 0) {
    Write-Host "::warning::engine handshake took longer than the shell's ${ShellHandshakeWaitMs} ms wait on run(s) $(($slow | ForEach-Object { $_.run }) -join ', ')"
}
Write-Host "Windows engine smoke passed ($Layout)"
