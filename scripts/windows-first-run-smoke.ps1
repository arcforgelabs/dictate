# First-run latency smoke for a Dictate Windows NSIS installer on a fresh machine.
#
# Run it as an administrator on a throwaway Windows VM, with Microsoft Defender
# left as shipped. It installs a `*_x64-setup.exe` silently (per-user) and times
# what a new user waits through:
#
#   1. install            `setup.exe /S`
#   2. engine launch #1   the first launch after install, started the way the
#                         shell starts it (same env as spawn_engine() in
#                         ui-shell/src-tauri/src/lib.rs and
#                         scripts/windows-engine-smoke.ps1), split into
#                         process start -> "Loading STT backend" (unpack, imports,
#                         preflight) -> "Ready." (Parakeet model load) ->
#                         ui-server.json handshake -> first authenticated
#                         GET /api/state.
#   3. engine launch #2   the same again, warm, for comparison.
#   4. dictation latency  a `dictate-engine.exe benchmark` process transcribing
#                         short (~3 s), medium (~8 s) and long (~15 s) speech
#                         clips, twice each. Parakeet does not stream dictation
#                         (supports_streaming_chunks=False), so the whole clip is
#                         decoded after key release and the per-clip decode time
#                         is the end-of-audio -> text wait.
#
# Each step records Defender's CPU time (MsMpEng), so its share of a wait is
# visible. `-DefenderExclusion` adds the install folder to Defender's exclusions
# before installing; use it only on a separate throwaway VM, for diagnosis.
#
# Untimed setup first brings the VM to a typical desktop's state: Defender
# signatures updated (cloud images boot with old ones), and on Windows Server the
# WebView2 runtime installed (Windows 11 ships it; otherwise the installer would
# download it inside the timed install).
#
# Speech clips are synthesized on the VM with Windows' built-in System.Speech
# voice (16 kHz mono 16-bit), so the run needs no microphone and no fixtures.
#
# Usage (on the VM, elevated):
#   .\windows-first-run-smoke.ps1 -InstallerUrl <setup.exe or artifact zip URL> -Label release-2026.9.27
#   .\windows-first-run-smoke.ps1 -InstallerPath C:\dl\Dictate_x64-setup.exe -DefenderExclusion
# Output: a Markdown table on stdout (and -SummaryPath) and JSON at -JsonPath.

[CmdletBinding()]
param(
    [string]$InstallerUrl = "",
    [string]$InstallerPath = "",
    [string]$Label = "",
    [switch]$DefenderExclusion,
    [switch]$SkipWebView2Preinstall,
    [switch]$SkipDefenderUpdate,
    [string]$WorkDir = "C:\dictate-first-run",
    [int]$TimeoutSeconds = 900,
    [string]$JsonPath = "",
    [string]$SummaryPath = $env:GITHUB_STEP_SUMMARY
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

$Clips = [ordered]@{
    short = "Schedule a review with the platform team."
    medium = "Schedule a review with the project nova platform team for Thursday morning, and send the notes to everyone on the list."
    long = "Schedule a review with the project nova platform team for Thursday morning. Before then, please collect the latency numbers from the test machines, write a short summary of what changed since last week, and send the notes to everyone on the release list."
}
$clock = [System.Diagnostics.Stopwatch]::StartNew()
$steps = New-Object System.Collections.ArrayList
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

function Get-DefenderCpuSeconds {
    # Raw perf counters can read a protected process such as MsMpEng, where
    # Get-Process cannot. PercentProcessorTime is cumulative 100 ns units.
    $row = Get-CimInstance -ClassName Win32_PerfRawData_PerfProc_Process -Filter "Name='MsMpEng'" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $row) { return 0 }
    return [double]$row.PercentProcessorTime / 1e7
}

function Get-DefenderStatus {
    try {
        $s = Get-MpComputerStatus
        return [pscustomobject]@{
            antivirusEnabled = $s.AntivirusEnabled
            realTimeProtectionEnabled = $s.RealTimeProtectionEnabled
            onAccessProtectionEnabled = $s.OnAccessProtectionEnabled
            amRunningMode = $s.AMRunningMode
            amProductVersion = $s.AMProductVersion
            amEngineVersion = $s.AMEngineVersion
            signatureVersion = $s.AntivirusSignatureVersion
            exclusionPaths = @((Get-MpPreference).ExclusionPath | Where-Object { $_ })
        }
    } catch {
        return [pscustomobject]@{ error = $_.Exception.Message }
    }
}

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "== $Name"
    $defenderBefore = Get-DefenderCpuSeconds
    $start = $clock.ElapsedMilliseconds
    $detail = & $Body
    $end = $clock.ElapsedMilliseconds
    $defenderCpu = [math]::Round((Get-DefenderCpuSeconds) - $defenderBefore, 1)
    if ($defenderCpu -lt 0) { $defenderCpu = $null } # MsMpEng restarted (engine update)
    $step = [pscustomobject]@{
        name = $Name
        durationMs = $end - $start
        defenderCpuSeconds = $defenderCpu
        detail = $detail
    }
    [void]$steps.Add($step)
    Write-Host ("   {0:N1} s wall, Defender CPU {1:N1} s" -f ($step.durationMs / 1000), $step.defenderCpuSeconds)
    return $step
}

function Get-Download([string]$Url, [string]$OutFile) {
    & curl.exe --fail --location --silent --show-error --retry 3 --output $OutFile $Url
    if ($LASTEXITCODE -ne 0) { throw "download failed ($LASTEXITCODE): $Url" }
    return (Get-Item -LiteralPath $OutFile).Length
}

function Test-WebView2 {
    $id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    foreach ($key in @(
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$id",
            "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id",
            "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$id")) {
        $pv = Get-ItemProperty -Path $key -Name pv -ErrorAction SilentlyContinue
        if ($pv -and $pv.pv -and $pv.pv -ne "0.0.0.0") { return [string]$pv.pv }
    }
    return $null
}

function Find-InstallDir {
    foreach ($root in @(
            "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
            "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")) {
        foreach ($key in @(Get-ChildItem -Path $root -ErrorAction SilentlyContinue)) {
            $props = Get-ItemProperty -Path $key.PSPath -ErrorAction SilentlyContinue
            if (-not $props) { continue }
            $names = $props.PSObject.Properties.Name
            if (($names -contains "DisplayName") -and $props.DisplayName -like "Dictate*") {
                if (($names -contains "InstallLocation") -and $props.InstallLocation) {
                    return $props.InstallLocation.Trim('"').TrimEnd("\")
                }
                if ($names -contains "UninstallString") {
                    return Split-Path -Parent ($props.UninstallString.Trim().Trim('"'))
                }
            }
        }
    }
    return (Join-Path $env:LOCALAPPDATA "Dictate")
}

function New-SpeechWav([string]$Path, [string]$Text) {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        if (@($synth.GetInstalledVoices() | Where-Object { $_.Enabled }).Count -eq 0) {
            throw "System.Speech has no installed voices"
        }
        $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
            [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
            [System.Speech.AudioFormat.AudioChannel]::Mono)
        $synth.SetOutputToWaveFile($Path, $format)
        $synth.Speak($Text)
        $synth.SetOutputToNull()
        return $synth.Voice.Name
    } finally {
        $synth.Dispose()
    }
}

function Start-Engine([string]$EngineExe, [string]$EngineDir, [string]$Arguments, [hashtable]$ExtraEnv) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $EngineExe
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $EngineDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.EnvironmentVariables["HF_HUB_DISABLE_TELEMETRY"] = "1"
    $psi.EnvironmentVariables["HF_HUB_OFFLINE"] = "1"
    $psi.EnvironmentVariables["ORT_DISABLE_TELEMETRY"] = "1"
    $parakeet = Join-Path $EngineDir "models\parakeet-tdt-0.6b-v2-onnx"
    if (Test-Path (Join-Path $parakeet "config.json")) {
        $psi.EnvironmentVariables["DICTATE_PARAKEET_MODEL_PATH"] = $parakeet
    }
    foreach ($name in $ExtraEnv.Keys) { $psi.EnvironmentVariables[$name] = $ExtraEnv[$name] }
    return [System.Diagnostics.Process]::Start($psi)
}

function New-LineReader($Process) {
    return [pscustomobject]@{
        out = $Process.StandardOutput.ReadLineAsync()
        err = $Process.StandardError.ReadLineAsync()
        outDone = $false
        errDone = $false
    }
}

function Read-ReadyLines($Process, $Reader, $Clock, $Lines) {
    # Collect whatever lines are ready on stdout/stderr, timestamped on arrival.
    $got = $true
    while ($got) {
        $got = $false
        if (-not $Reader.outDone -and $Reader.out.IsCompleted) {
            $text = $Reader.out.Result
            if ($null -eq $text) { $Reader.outDone = $true } else {
                [void]$Lines.Add([pscustomobject]@{ ms = $Clock.ElapsedMilliseconds; stream = "out"; text = $text })
                $Reader.out = $Process.StandardOutput.ReadLineAsync()
                $got = $true
            }
        }
        if (-not $Reader.errDone -and $Reader.err.IsCompleted) {
            $text = $Reader.err.Result
            if ($null -eq $text) { $Reader.errDone = $true } else {
                [void]$Lines.Add([pscustomobject]@{ ms = $Clock.ElapsedMilliseconds; stream = "err"; text = $text })
                $Reader.err = $Process.StandardError.ReadLineAsync()
                $got = $true
            }
        }
    }
}

function First-LineMs($Lines, [string]$Pattern) {
    $hit = $Lines | Where-Object { $_.text -match $Pattern } | Select-Object -First 1
    if ($hit) { return $hit.ms }
    return $null
}

function Invoke-EngineLaunch([string]$EngineExe, [string]$EngineDir, [int]$Run) {
    $root = Join-Path $WorkDir ("engine-launch-$Run-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    $local = Join-Path $root "Local"
    $roaming = Join-Path $root "Roaming"
    New-Item -ItemType Directory -Force -Path $local, $roaming | Out-Null
    $handshakePath = Join-Path $local "dictate\ui-server.json"

    Get-Process -Name "dictate-engine" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    $launchClock = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Engine $EngineExe $EngineDir "--no-tray" @{
        LOCALAPPDATA = $local
        APPDATA = $roaming
        DICTATE_UI_SERVER = "1"
    }
    $reader = New-LineReader $process
    $lines = New-Object System.Collections.ArrayList
    $handshake = $null
    $handshakeMs = $null
    $stateMs = $null
    $failure = $null
    try {
        while (-not $handshake) {
            Read-ReadyLines $process $reader $launchClock $lines
            if ($process.HasExited) { $failure = "engine exited with code $($process.ExitCode) before the handshake"; break }
            if ($launchClock.ElapsedMilliseconds -gt $TimeoutSeconds * 1000) { $failure = "no handshake within ${TimeoutSeconds}s"; break }
            if (Test-Path -LiteralPath $handshakePath) {
                try {
                    $candidate = Get-Content -Raw -LiteralPath $handshakePath | ConvertFrom-Json
                    if ($candidate.url -and $candidate.token) { $handshake = $candidate; $handshakeMs = $launchClock.ElapsedMilliseconds }
                } catch {
                    # Written in place; retry until it parses.
                }
            }
            Start-Sleep -Milliseconds 25
        }
        if ($handshake) {
            $base = ([Uri]$handshake.url).GetLeftPart([UriPartial]::Authority)
            $headers = @{ Authorization = "Bearer $($handshake.token)" }
            while ($null -eq $stateMs -and -not $failure) {
                try {
                    $response = Invoke-WebRequest -UseBasicParsing -Uri "$base/api/state" -Headers $headers -TimeoutSec 120
                    if ($response.StatusCode -eq 200) { $stateMs = $launchClock.ElapsedMilliseconds }
                } catch {
                    if ($process.HasExited) { $failure = "engine exited before /api/state answered" }
                    elseif ($launchClock.ElapsedMilliseconds -gt $TimeoutSeconds * 1000) { $failure = "/api/state did not answer" }
                    else { Start-Sleep -Milliseconds 100 }
                }
            }
        }
        Read-ReadyLines $process $reader $launchClock $lines
    } finally {
        if (-not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
            $null = $process.WaitForExit(15000)
        }
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root
    }
    foreach ($line in $lines) { Write-Host "   [$($line.ms) ms $($line.stream)] $($line.text)" }
    if ($failure) { Write-Host "::warning::engine launch ${Run}: $failure" }

    $loadingMs = First-LineMs $lines "^Loading STT backend"
    $readyMs = First-LineMs $lines "^Ready\."
    return [pscustomobject]@{
        run = $Run
        failure = $failure
        loadingSttMs = $loadingMs
        readyMs = $readyMs
        modelLoadMs = if ($null -ne $loadingMs -and $null -ne $readyMs) { $readyMs - $loadingMs } else { $null }
        handshakeMs = $handshakeMs
        firstStateMs = $stateMs
        output = @($lines | ForEach-Object { "[{0} ms {1}] {2}" -f $_.ms, $_.stream, $_.text })
    }
}

function Invoke-DictationBenchmark([string]$EngineExe, [string]$EngineDir, [string]$Manifest) {
    $jsonOut = Join-Path $WorkDir "benchmark.json"
    $benchClock = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Engine $EngineExe $EngineDir ("benchmark --manifest `"$Manifest`" --audio-root `"$WorkDir`" " +
        "--stt-backend parakeet --json-output `"$jsonOut`" --run-label first-run-smoke") @{}
    $reader = New-LineReader $process
    $lines = New-Object System.Collections.ArrayList
    while (-not ($reader.outDone -and $reader.errDone)) {
        Read-ReadyLines $process $reader $benchClock $lines
        if ($benchClock.ElapsedMilliseconds -gt $TimeoutSeconds * 1000) {
            & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
            throw "benchmark did not finish within ${TimeoutSeconds}s"
        }
        Start-Sleep -Milliseconds 25
    }
    $process.WaitForExit()
    foreach ($line in $lines) { Write-Host "   [$($line.ms) ms $($line.stream)] $($line.text)" }
    if ($process.ExitCode -ne 0) { throw "benchmark exited with code $($process.ExitCode)" }
    $benchmark = Get-Content -Raw -LiteralPath $jsonOut | ConvertFrom-Json
    return [pscustomobject]@{
        wallMs = $benchClock.ElapsedMilliseconds
        samples = @($benchmark.samples | ForEach-Object {
                [pscustomobject]@{
                    id = $_.id
                    audioS = [math]::Round([double]$_.duration_s, 2)
                    latencyMs = [math]::Round([double]$_.latency_s * 1000)
                    wer = [math]::Round([double]$_.wer, 3)
                    hypothesis = $_.hypothesis
                }
            })
    }
}

# ---------------------------------------------------------------------------

$os = Get-CimInstance Win32_OperatingSystem
$machine = [pscustomobject]@{
    os = "$($os.Caption) $($os.Version)"
    cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    logicalProcessors = [int](Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
    memoryGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    defender = Get-DefenderStatus
    webView2BeforeSetup = Test-WebView2
}
Write-Host ($machine | ConvertTo-Json -Depth 4)

if ([bool]$InstallerPath -eq [bool]$InstallerUrl) { throw "Pass exactly one of -InstallerUrl or -InstallerPath" }
if ($InstallerUrl) {
    $download = Join-Path $WorkDir "download.bin"
    $dl = Invoke-Step "download installer (untimed setup)" { [pscustomobject]@{ bytes = Get-Download $InstallerUrl $download } }
    $stream = [System.IO.File]::OpenRead($download)
    try { $magic = @($stream.ReadByte(), $stream.ReadByte()) } finally { $stream.Dispose() }
    if ($magic[0] -eq 0x50 -and $magic[1] -eq 0x4B) {
        $unzipped = Join-Path $WorkDir "artifact"
        New-Item -ItemType Directory -Force -Path $unzipped | Out-Null
        # Expand-Archive takes many minutes on a ~500 MB zip in Windows PowerShell 5.1.
        & tar.exe -xf $download -C $unzipped
        if ($LASTEXITCODE -ne 0) { throw "could not unzip $download" }
        $found = Get-ChildItem -Path $unzipped -Recurse -Filter "*x64-setup.exe" | Select-Object -First 1
        if (-not $found) { throw "No *x64-setup.exe in the downloaded zip" }
        $InstallerPath = $found.FullName
    } else {
        $InstallerPath = Join-Path $WorkDir "Dictate_x64-setup.exe"
        Move-Item -Force -LiteralPath $download -Destination $InstallerPath
    }
}
$InstallerPath = (Resolve-Path $InstallerPath).Path
$installer = [pscustomobject]@{
    name = Split-Path -Leaf $InstallerPath
    bytes = (Get-Item -LiteralPath $InstallerPath).Length
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash
    authenticode = [string](Get-AuthenticodeSignature -LiteralPath $InstallerPath).Status
}
Write-Host ($installer | ConvertTo-Json)

# Windows 11 ships the WebView2 runtime and Windows Server does not; without it
# the installer's downloadBootstrapper would fold a WebView2 install into the
# timed install. Install it first (untimed) so the install matches Windows 11.
if (-not $machine.webView2BeforeSetup -and -not $SkipWebView2Preinstall) {
    Invoke-Step "preinstall WebView2 runtime (untimed setup)" {
        $bootstrapper = Join-Path $WorkDir "MicrosoftEdgeWebview2Setup.exe"
        Get-Download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $bootstrapper | Out-Null
        $p = Start-Process -FilePath $bootstrapper -ArgumentList "/silent", "/install" -Wait -PassThru
        [pscustomobject]@{ exitCode = $p.ExitCode; version = Test-WebView2 }
    } | Out-Null
}

# A fresh cloud image can boot with months-old Defender engine and signatures
# and update them in the background mid-run. A desktop that has been online is
# current, so update first (untimed) to measure that state.
if (-not $SkipDefenderUpdate) {
    Invoke-Step "update Defender signatures (untimed setup)" {
        # An engine update restarts MsMpEng mid-call, which surfaces as an RPC
        # failure; wait for Defender to answer again before going on.
        try { Update-MpSignature -ErrorAction Stop } catch { Write-Host "   Update-MpSignature: $($_.Exception.Message)" }
        $status = $null
        for ($i = 0; $i -lt 60 -and -not $status; $i++) {
            try { $status = Get-MpComputerStatus -ErrorAction Stop } catch { Start-Sleep -Seconds 5 }
        }
        if (-not $status) { throw "Defender did not answer after the signature update" }
        Start-Sleep -Seconds 30
        [pscustomobject]@{ amEngineVersion = $status.AMEngineVersion; signatureVersion = $status.AntivirusSignatureVersion }
    } | Out-Null
}

# Speech clips are made before install so System.Speech's own first-use cost
# stays out of the timed steps.
$manifestRows = @("id,audio,text")
$clipInfo = [ordered]@{}
foreach ($name in $Clips.Keys) {
    $wav = Join-Path $WorkDir "$name.wav"
    $voice = New-SpeechWav $wav $Clips[$name]
    $seconds = [math]::Round(((Get-Item -LiteralPath $wav).Length - 44) / 32000, 1)
    $clipInfo[$name] = [pscustomobject]@{ seconds = $seconds; voice = $voice; words = ($Clips[$name] -split "\s+").Count }
    $reference = ($Clips[$name].ToLowerInvariant() -replace "[^a-z ]", "")
    $manifestRows += "$name-1,$name.wav,$reference"
}
foreach ($name in $Clips.Keys) {
    $reference = ($Clips[$name].ToLowerInvariant() -replace "[^a-z ]", "")
    $manifestRows += "$name-2,$name.wav,$reference"
}
$manifest = Join-Path $WorkDir "manifest.csv"
$manifestRows | Set-Content -LiteralPath $manifest -Encoding ASCII
Write-Host ("speech clips: " + (($clipInfo.Keys | ForEach-Object { "$_ $($clipInfo[$_].seconds) s" }) -join ", ") + " ($($clipInfo['short'].voice))")

$defaultInstallDir = Join-Path $env:LOCALAPPDATA "Dictate"
if ($DefenderExclusion) {
    Add-MpPreference -ExclusionPath $defaultInstallDir
    Write-Host "::warning::Defender exclusion added for $defaultInstallDir (diagnostic run)"
}

# Let Defender settle after the downloads so its CPU time is attributed cleanly.
Start-Sleep -Seconds 30

$installStep = Invoke-Step "install (setup.exe /S)" {
    $p = Start-Process -FilePath $InstallerPath -ArgumentList "/S" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "installer exited with code $($p.ExitCode)" }
    [pscustomobject]@{ exitCode = $p.ExitCode }
}
$installDir = Find-InstallDir
if ($DefenderExclusion -and $installDir -ne $defaultInstallDir) {
    Write-Host "::warning::installed to $installDir, not the excluded $defaultInstallDir"
}
$engineExe = Get-ChildItem -LiteralPath $installDir -Recurse -Filter "dictate-engine.exe" -File | Select-Object -First 1
if (-not $engineExe) { throw "No dictate-engine.exe under $installDir" }
$engineDir = $engineExe.DirectoryName
$leftRunning = @(Get-Process -Name "dictate*" -ErrorAction SilentlyContinue | ForEach-Object { $_.ProcessName })
if ($leftRunning.Count -gt 0) {
    Write-Host "::warning::installer left processes running: $($leftRunning -join ', '); stopping them"
    Get-Process -Name "dictate*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
$engineFiles = @(Get-ChildItem -LiteralPath $engineDir -Recurse -File -Force)
$engine = [pscustomobject]@{
    path = $engineExe.FullName
    layout = if (Test-Path (Join-Path $engineDir "_internal") -PathType Container) { "onedir" } else { "onefile" }
    files = $engineFiles.Count
    bytes = [long](($engineFiles | Measure-Object -Property Length -Sum).Sum)
}
Write-Host "installed to $installDir; engine $($engine.layout), $($engine.files) files, $([math]::Round($engine.bytes / 1MB)) MB"

$launch1Step = Invoke-Step "engine launch 1 (first after install)" { Invoke-EngineLaunch $engineExe.FullName $engineDir 1 }
$launch2Step = Invoke-Step "engine launch 2 (warm)" { Invoke-EngineLaunch $engineExe.FullName $engineDir 2 }
$benchStep = Invoke-Step "dictation latency (benchmark process)" { Invoke-DictationBenchmark $engineExe.FullName $engineDir $manifest }

$report = [pscustomobject]@{
    label = $Label
    defenderExclusion = [bool]$DefenderExclusion
    machine = $machine
    installer = $installer
    installDir = $installDir
    engine = $engine
    leftRunningAfterInstall = $leftRunning
    clips = $clipInfo
    steps = $steps
    defenderAfter = Get-DefenderStatus
}
if (-not $JsonPath) { $JsonPath = Join-Path $WorkDir "first-run.json" }
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $JsonPath -Encoding UTF8

function Format-S($ms) { if ($null -eq $ms) { "n/a" } else { "{0:N1} s" -f ($ms / 1000) } }
$l1 = $launch1Step.detail
$l2 = $launch2Step.detail
$samples = @($benchStep.detail.samples)
$title = "Windows first run: $Label ($($engine.layout) engine" + $(if ($DefenderExclusion) { ", Defender exclusion on the install folder" } else { "" }) + ")"
$lines = @(
    "#### $title",
    "",
    "$($machine.os), $($machine.logicalProcessors) vCPU, $($machine.memoryGB) GB; Defender real-time protection: $($machine.defender.realTimeProtectionEnabled) (engine $($report.defenderAfter.amEngineVersion), signatures $($report.defenderAfter.signatureVersion))",
    "$($installer.name), $([math]::Round($installer.bytes / 1MB)) MB; engine folder $($engine.files) files, $([math]::Round($engine.bytes / 1MB)) MB",
    "",
    "| Step | Launch 1 (first after install) | Launch 2 (warm) |",
    "| --- | ---: | ---: |",
    "| Process start -> ``Loading STT backend`` (unpack, imports, preflight) | $(Format-S $l1.loadingSttMs) | $(Format-S $l2.loadingSttMs) |",
    "| Parakeet model load (``Loading STT backend`` -> ``Ready.``) | $(Format-S $l1.modelLoadMs) | $(Format-S $l2.modelLoadMs) |",
    "| Handshake (``ui-server.json`` written) | $(Format-S $l1.handshakeMs) | $(Format-S $l2.handshakeMs) |",
    "| First authenticated ``GET /api/state`` | $(Format-S $l1.firstStateMs) | $(Format-S $l2.firstStateMs) |",
    "| Defender CPU during the launch | $($launch1Step.defenderCpuSeconds) s | $($launch2Step.defenderCpuSeconds) s |",
    "",
    "Install (``setup.exe /S``): $(Format-S $installStep.durationMs), Defender CPU $($installStep.defenderCpuSeconds) s.",
    "",
    "| Clip | Audio | Decode, 1st time | Decode, 2nd time | WER |",
    "| --- | ---: | ---: | ---: | ---: |"
)
foreach ($name in $Clips.Keys) {
    $a = $samples | Where-Object { $_.id -eq "$name-1" } | Select-Object -First 1
    $b = $samples | Where-Object { $_.id -eq "$name-2" } | Select-Object -First 1
    $lines += "| $name | $($a.audioS) s | $(Format-S $a.latencyMs) | $(Format-S $b.latencyMs) | $($a.wer) |"
}
$lines += @(
    "",
    "Decode = end of audio -> text for a dictation of that length (Parakeet decodes the whole clip after key release). Benchmark process wall time $(Format-S $benchStep.detail.wallMs), Defender CPU $($benchStep.defenderCpuSeconds) s."
)
$markdown = ($lines -join "`n") + "`n"
Write-Host ""
Write-Host $markdown
if ($SummaryPath) { Add-Content -Path $SummaryPath -Value $markdown -Encoding UTF8 }
Write-Host "report: $JsonPath"
