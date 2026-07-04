param(
    [ValidateSet("cpu", "cuda", "amd", "auto")]
    [string]$Device = "auto",
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

Push-Location $RepoRoot
try {
    Write-Host "==> Human-test readiness"
    & $Python scripts\transcription_plan_audit.py --readiness
    if ($LASTEXITCODE -ne 0) {
        throw "readiness report failed with exit code $LASTEXITCODE"
    }

    if (-not $SkipDoctor) {
        Write-Host ""
        Write-Host "==> Local Parakeet doctor ($Device)"
        & $Python -m dictate doctor `
            --stt-backend parakeet `
            --model parakeet-tdt-0.6b-v2 `
            --device $Device `
            --quick `
            --type-backend pynput
        if ($LASTEXITCODE -ne 0) {
            throw "Parakeet doctor failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host ""
    Write-Host "==> Manual microphone checks"
    Write-Host "Run these on each human-test machine and speak real audio when prompted:"
    Write-Host ""
    Write-Host "  $Python -m dictate --once --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device $Device --language en --type-backend pynput"
    Write-Host ""
    Write-Host "Expected:"
    Write-Host "  - The transcript reflects what was spoken."
    Write-Host "  - It does not repeat stale fixture text."
    Write-Host "  - Plain Record and push-to-talk use the same non-meeting ASR behavior."
    Write-Host ""
    Write-Host "For Meeting validation on a CUDA tester with the Sortformer lane installed:"
    Write-Host ""
    Write-Host "  $Python -m dictate doctor --stt-backend parakeet-sortformer --model parakeet-tdt-0.6b-v2 --device cuda --quick --type-backend pynput"
    Write-Host ""
    Write-Host "Expected:"
    Write-Host "  - The app allows Meeting only when a speaker-attribution lane is ready."
    Write-Host "  - A Meeting capture produces speaker/timestamp segment metadata."
    Write-Host ""
    Write-Host "For AMD/Radeon promotion:"
    Write-Host ""
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\run-amd-promotion-benchmarks.ps1 -CollectEvidence"
    Write-Host ""
    Write-Host "Expected:"
    Write-Host "  - benchmark-results\parakeet-v2-amd-human-gated.json is produced."
    Write-Host "  - benchmark-results\parakeet-v3-amd-human-gated.json is produced."
    Write-Host "  - The artifact environment shows AMD/Radeon hardware provenance."
} finally {
    Pop-Location
}
