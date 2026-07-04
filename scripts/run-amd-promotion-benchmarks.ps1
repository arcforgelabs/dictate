param(
    [switch]$DryRun,
    [switch]$SkipPreflight,
    [switch]$CollectEvidence,
    [switch]$NoInstallAmdExtra
)

$ErrorActionPreference = "Stop"

# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\run-amd-promotion-benchmarks.ps1 -CollectEvidence
#
# By default this installs the Windows AMD extra with:
#   python -m pip install -e .[amd]
# Use -NoInstallAmdExtra only when the target venv is already prepared.
#
# Windows Radeon promotion requires ONNX Runtime DirectML to expose
# DmlExecutionProvider, plus benchmark environment hardware provenance showing
# AMD/Radeon graphics. Synthetic DirectML readiness on non-Radeon hardware is
# not accepted by scripts/transcription_plan_audit.py.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

function Invoke-Step {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [string]$Description
    )

    if ($DryRun) {
        Write-Output ("+ {0} {1}" -f $Exe, ($Arguments -join " "))
        return
    }

    Write-Host "==> $Description"
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Ensure-CuratedAsrFixture {
    if ($env:DICTATE_HUMAN_MANIFEST) {
        if (-not $env:DICTATE_HUMAN_AUDIO_ROOT) {
            $env:DICTATE_HUMAN_AUDIO_ROOT = Split-Path -Parent $env:DICTATE_HUMAN_MANIFEST
        }
        return
    }

    $FixtureDir = Join-Path $RepoRoot "benchmark-curated\open-speech-harvard"
    $Generator = @'
from __future__ import annotations

import audioop
import csv
import json
import urllib.request
import wave
from pathlib import Path

out_dir = Path(r"__FIXTURE_DIR__")
out_dir.mkdir(parents=True, exist_ok=True)
source_url = "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0010_8k.wav"
source_wav = out_dir / "OSR_us_000_0010_8k.wav"
target_wav = out_dir / "osr_us_000_0010_harvard_list_1.wav"
manifest = out_dir / "manifest.csv"
source_note = out_dir / "SOURCE.txt"

if not source_wav.exists() or source_wav.stat().st_size == 0:
    urllib.request.urlretrieve(source_url, source_wav)

with wave.open(str(source_wav), "rb") as handle:
    channels = handle.getnchannels()
    sample_width = handle.getsampwidth()
    frame_rate = handle.getframerate()
    frames = handle.readframes(handle.getnframes())

if channels != 1:
    frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
if frame_rate != 16000:
    frames, _state = audioop.ratecv(frames, sample_width, 1, frame_rate, 16000, None)

with wave.open(str(target_wav), "wb") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(sample_width)
    handle.setframerate(16000)
    handle.writeframes(frames)

with wave.open(str(target_wav), "rb") as handle:
    duration = handle.getnframes() / float(handle.getframerate())

reference = (
    "The birch canoe slid on the smooth planks. "
    "Glue the sheet to the dark blue background. "
    "It's easy to tell the depth of a well. "
    "These days a chicken leg is a rare dish. "
    "Rice is often served in round bowls. "
    "The juice of lemons makes fine punch. "
    "The box was thrown beside the parked truck. "
    "The hogs were fed chopped corn and garbage. "
    "Four hours of steady work faced us. "
    "A large size in stockings is hard to sell."
)
segments_json = json.dumps([{"text": reference, "start": 0.0, "end": round(duration, 3)}])
with manifest.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
    writer.writeheader()
    writer.writerow(
        {
            "id": "osr_us_000_0010_harvard_list_1",
            "audio": target_wav.name,
            "text": reference,
            "segments_json": segments_json,
        }
    )

source_note.write_text(
    "Fixture source: Open Speech Repository, American English Harvard sentences.\n"
    "Source page: https://www.voiptroubleshooter.com/open_speech/american.html\n"
    "Audio file: OSR_us_000_0010_8k.wav\n"
    "Transcript source: Harvard Sentences List 1, https://www.cs.columbia.edu/~hgs/audio/harvard.html\n",
    encoding="utf-8",
)
print(manifest)
'@
    $Generator = $Generator.Replace("__FIXTURE_DIR__", $FixtureDir.Replace("\", "\\"))
    $GeneratorPath = Join-Path $env:TEMP "dictate-amd-curated-fixture.py"
    Set-Content -Path $GeneratorPath -Value $Generator -Encoding UTF8
    Invoke-Step $Python @($GeneratorPath) "Prepare curated ASR fixture"
    $env:DICTATE_HUMAN_MANIFEST = Join-Path $FixtureDir "manifest.csv"
    $env:DICTATE_HUMAN_AUDIO_ROOT = $FixtureDir
}

function Invoke-AmdLane {
    param(
        [string]$Model,
        [string]$Artifact,
        [string]$Label
    )

    if (-not $SkipPreflight) {
        Invoke-Step $Python @(
            "-m", "dictate", "doctor",
            "--stt-backend", "parakeet",
            "--model", $Model,
            "--device", "amd",
            "--quick",
            "--type-backend", "pynput"
        ) "Preflight $Label"
    }

    Invoke-Step $Python @(
        "-m", "dictate", "benchmark",
        "--manifest", $env:DICTATE_HUMAN_MANIFEST,
        "--audio-root", $env:DICTATE_HUMAN_AUDIO_ROOT,
        "--stt-backend", "parakeet",
        "--model", $Model,
        "--device", "amd",
        "--language", "en",
        "--fixture-class", "curated-human",
        "--require-timestamp-metrics",
        "--max-mean-wer", "0.60",
        "--max-mean-rtf", "1.00",
        "--max-mean-segment-boundary-mae-s", "1.00",
        "--json-output", (Join-Path $RepoRoot "benchmark-results\$Artifact"),
        "--run-label", $Label
    ) "Benchmark $Label"
}

Push-Location $RepoRoot
try {
    Ensure-CuratedAsrFixture
    if (-not $NoInstallAmdExtra) {
        Invoke-Step $Python @("-m", "pip", "install", "-e", ".[amd]") "Install Windows AMD DirectML extra"
    }
    Invoke-AmdLane "parakeet-tdt-0.6b-v2" "parakeet-v2-amd-human-gated.json" "local-amd-human-gated"
    Invoke-AmdLane "parakeet-tdt-0.6b-v3" "parakeet-v3-amd-human-gated.json" "local-amd-parakeet-v3-human-gated"
    Invoke-Step $Python @("scripts/transcription_plan_audit.py") "Run transcription plan audit"
    if ($CollectEvidence) {
        Invoke-Step "powershell.exe" @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts\collect-transcription-evidence.ps1"
        ) "Collect transcription evidence"
    }
} finally {
    Pop-Location
}
