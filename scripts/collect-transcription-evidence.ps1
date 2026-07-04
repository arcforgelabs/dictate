param(
    [string]$Output,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}
if (-not $Output) {
    $Output = Join-Path $RepoRoot "evidence-bundles"
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$BundleName = "transcription-evidence-$Timestamp"
$BundleDir = Join-Path $Output $BundleName
$ArchivePath = "$BundleDir.zip"

if ($DryRun) {
    Write-Output "Would create: $BundleDir"
    Write-Output "Would archive: $ArchivePath"
    Write-Output "Would collect:"
    Write-Output "  docs/TRANSCRIPTION_PLAN.md"
    Write-Output "  benchmarks/README.md"
    Write-Output "  benchmark-results/*.json"
    Write-Output "  audit.txt"
    Write-Output "  audit.json"
    Write-Output "  lane-runner-dry-run.txt"
    Write-Output "  human-lane-dry-run.txt"
    Write-Output "  lane-readiness.txt"
    Write-Output "  promotion-status.txt"
    Write-Output "  machine.txt"
    Write-Output "  git-status.txt"
    exit 0
}

New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BundleDir "docs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BundleDir "benchmarks") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BundleDir "benchmark-results") | Out-Null

function Copy-IfExists {
    param([string]$Source, [string]$Destination)
    if (Test-Path -LiteralPath $Source) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

Copy-IfExists (Join-Path $RepoRoot "docs\TRANSCRIPTION_PLAN.md") (Join-Path $BundleDir "docs\TRANSCRIPTION_PLAN.md")
Copy-IfExists (Join-Path $RepoRoot "benchmarks\README.md") (Join-Path $BundleDir "benchmarks\README.md")

$BenchmarkResults = Join-Path $RepoRoot "benchmark-results"
if (Test-Path -LiteralPath $BenchmarkResults) {
    Get-ChildItem -LiteralPath $BenchmarkResults -Filter "*.json" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $BundleDir "benchmark-results\$($_.Name)") -Force
    }
}

Push-Location $RepoRoot
try {
    & $Python scripts/transcription_plan_audit.py *> (Join-Path $BundleDir "audit.txt")
    & $Python scripts/transcription_plan_audit.py --json *> (Join-Path $BundleDir "audit.json")

    $LaneDryRun = Join-Path $BundleDir "lane-runner-dry-run.txt"
    $Bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($Bash) {
        & $Bash.Source scripts/run-transcription-lane-benchmarks.sh --dry-run *> $LaneDryRun
    } else {
        @(
            "Bash was not available on this Windows machine.",
            "Run the canonical benchmark commands from benchmarks/README.md, then collect this bundle again.",
            "Expected artifact names:",
            "  benchmark-results/parakeet-v2-cpu-flite-long-3x-gated.json",
            "  benchmark-results/parakeet-v2-cuda-flite-long-3x-gated.json",
            "  benchmark-results/parakeet-v3-cuda-flite-long-3x-gated.json",
            "  benchmark-results/parakeet-v2-amd-flite-long-3x-gated.json",
            "  benchmark-results/parakeet-v3-amd-flite-long-3x-gated.json",
            "  benchmark-results/parakeet-pyannote-cuda-flite-meeting.json",
            "  benchmark-results/parakeet-diarizen-cuda-flite-meeting.json",
            "  benchmark-results/parakeet-sortformer-cuda-flite-meeting.json"
        ) | Set-Content -Path $LaneDryRun -Encoding UTF8
    }

    $HumanLaneDryRun = Join-Path $BundleDir "human-lane-dry-run.txt"
    if ($Bash) {
        $HumanLanes = @(
            "cuda-human",
            "cuda-human-v3",
            "amd-human",
            "amd-human-v3",
            "meeting-human",
            "meeting-diarizen-human",
            "meeting-sortformer-human"
        )
        Set-Content -Path $HumanLaneDryRun -Value "" -Encoding UTF8
        foreach ($Lane in $HumanLanes) {
            "## $Lane" | Add-Content -Path $HumanLaneDryRun -Encoding UTF8
            & $Bash.Source scripts/run-transcription-lane-benchmarks.sh --dry-run --lane $Lane *>> $HumanLaneDryRun
            "" | Add-Content -Path $HumanLaneDryRun -Encoding UTF8
        }
    } else {
        @(
            "Bash was not available on this Windows machine.",
            "Use benchmarks/README.md for curated-human promotion commands.",
            "Expected human artifact names:",
            "  benchmark-results/parakeet-v2-cuda-human-gated.json",
            "  benchmark-results/parakeet-v3-cuda-human-gated.json",
            "  benchmark-results/parakeet-v2-amd-human-gated.json",
            "  benchmark-results/parakeet-v3-amd-human-gated.json",
            "  benchmark-results/parakeet-pyannote-cuda-human-meeting.json",
            "  benchmark-results/parakeet-diarizen-cuda-human-meeting.json",
            "  benchmark-results/parakeet-sortformer-cuda-human-meeting.json"
        ) | Set-Content -Path $HumanLaneDryRun -Encoding UTF8
    }

    $PromotionStatus = Join-Path $BundleDir "promotion-status.txt"
    @(
        "Promotion artifact status",
        "Collected at UTC: $Timestamp",
        ""
    ) | Set-Content -Path $PromotionStatus -Encoding UTF8
    $ExpectedPromotionArtifacts = @(
        "benchmark-results/parakeet-v2-cuda-human-gated.json",
        "benchmark-results/parakeet-v3-cuda-human-gated.json",
        "benchmark-results/parakeet-v2-amd-human-gated.json",
        "benchmark-results/parakeet-v3-amd-human-gated.json",
        "benchmark-results/parakeet-pyannote-cuda-human-meeting.json",
        "benchmark-results/parakeet-diarizen-cuda-human-meeting.json",
        "benchmark-results/parakeet-sortformer-cuda-human-meeting.json"
    )
    foreach ($Relative in $ExpectedPromotionArtifacts) {
        $Path = Join-Path $RepoRoot $Relative
        if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path).Length -gt 0)) {
            "present  $Relative" | Add-Content -Path $PromotionStatus -Encoding UTF8
        } else {
            "missing  $Relative" | Add-Content -Path $PromotionStatus -Encoding UTF8
        }
    }
    "" | Add-Content -Path $PromotionStatus -Encoding UTF8
    "Audit summary:" | Add-Content -Path $PromotionStatus -Encoding UTF8
    & $Python scripts/transcription_plan_audit.py *>> $PromotionStatus

    $Readiness = Join-Path $BundleDir "lane-readiness.txt"
    @(
        "Dictate transcription lane readiness",
        "Collected at UTC: $Timestamp",
        ""
    ) | Set-Content -Path $Readiness -Encoding UTF8

    function Invoke-LaneReadiness {
        param([string]$Label, [string[]]$Arguments)
        "## $Label" | Add-Content -Path $Readiness -Encoding UTF8
        "+ $Python $($Arguments -join ' ')" | Add-Content -Path $Readiness -Encoding UTF8
        & $Python @Arguments *>> $Readiness
        "exit_code=$LASTEXITCODE" | Add-Content -Path $Readiness -Encoding UTF8
        "" | Add-Content -Path $Readiness -Encoding UTF8
    }

    Invoke-LaneReadiness "cpu-parakeet-v2" @("-m", "dictate", "doctor", "--stt-backend", "parakeet", "--model", "parakeet-tdt-0.6b-v2", "--device", "cpu", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "cuda-parakeet-v2" @("-m", "dictate", "doctor", "--stt-backend", "parakeet", "--model", "parakeet-tdt-0.6b-v2", "--device", "cuda", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "cuda-parakeet-v3" @("-m", "dictate", "doctor", "--stt-backend", "parakeet", "--model", "parakeet-tdt-0.6b-v3", "--device", "cuda", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "amd-parakeet-v2" @("-m", "dictate", "doctor", "--stt-backend", "parakeet", "--model", "parakeet-tdt-0.6b-v2", "--device", "amd", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "amd-parakeet-v3" @("-m", "dictate", "doctor", "--stt-backend", "parakeet", "--model", "parakeet-tdt-0.6b-v3", "--device", "amd", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "meeting-pyannote" @("-m", "dictate", "doctor", "--stt-backend", "parakeet-pyannote", "--model", "parakeet-tdt-0.6b-v2", "--device", "cuda", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "meeting-diarizen" @("-m", "dictate", "doctor", "--stt-backend", "parakeet-diarizen", "--model", "parakeet-tdt-0.6b-v2", "--device", "cuda", "--quick", "--type-backend", "pynput")
    Invoke-LaneReadiness "meeting-sortformer" @("-m", "dictate", "doctor", "--stt-backend", "parakeet-sortformer", "--model", "parakeet-tdt-0.6b-v2", "--device", "cuda", "--quick", "--type-backend", "pynput")

    $Machine = Join-Path $BundleDir "machine.txt"
    @(
        "Collected at UTC: $Timestamp",
        "Repository: $RepoRoot",
        "",
        "Computer: $env:COMPUTERNAME",
        "OS: $([System.Environment]::OSVersion.VersionString)",
        "Processor architecture: $env:PROCESSOR_ARCHITECTURE",
        "",
        "ONNX Runtime providers:"
    ) | Set-Content -Path $Machine -Encoding UTF8
    & $Python -c "import onnxruntime as ort; print(','.join(ort.get_available_providers()))" *>> $Machine

    & git status --short *> (Join-Path $BundleDir "git-status.txt")
} finally {
    Pop-Location
}

if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}
Compress-Archive -Path $BundleDir -DestinationPath $ArchivePath -Force
Write-Output $ArchivePath
