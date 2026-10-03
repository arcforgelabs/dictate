# Build the Dictate desktop UI (Tauri shell) into installable Windows artifacts.
#
# Produces .msi and/or NSIS .exe installers under:
#   ui-shell\src-tauri\target\release\bundle\
#
# Requirements:
#   - Windows runner or workstation
#   - Python 3.11/3.12
#   - Node/npm
#   - Rust toolchain
#   - Tauri Windows bundling dependencies for the selected bundles
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-desktop.ps1
#   $env:DICTATE_BUNDLES = "msi"; .\scripts\build-windows-desktop.ps1
#   $env:DICTATE_BUNDLES = "no-bundle"; .\scripts\build-windows-desktop.ps1

[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Bundles = $env:DICTATE_BUNDLES
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$HuggingFaceToken = @($env:DICTATE_HF_TOKEN, $env:HUGGINGFACE_HUB_TOKEN, $env:HF_TOKEN) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($HuggingFaceToken)) {
    throw "Staging pyannote Community-1 requires a Hugging Face token via DICTATE_HF_TOKEN, HUGGINGFACE_HUB_TOKEN, or HF_TOKEN."
}

if ([string]::IsNullOrWhiteSpace($Bundles)) {
    $Bundles = "msi,nsis"
}
$NoBundle = $Bundles -in @("none", "no-bundle", "unbundled")

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command '$Name'. Install it before building the Windows desktop bundle."
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )
    Write-Host $Description
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @ArgumentList
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
}

Write-Host "preflight"
Require-Command $Python
Require-Command "npm"
Require-Command "cargo"

Write-Host "building the front-end (ui/ -> dist/)"
try {
    Invoke-Native "installing UI dependencies with npm ci" "npm" @("--prefix", "ui", "ci")
} catch {
    Invoke-Native "installing UI dependencies with npm install" "npm" @("--prefix", "ui", "install")
}
Invoke-Native "building UI assets" "npm" @("--prefix", "ui", "run", "build")

$BuildVenv = Join-Path $Root "packaging\.build-venv-windows"
$VenvPython = Join-Path $BuildVenv "Scripts\python.exe"

Write-Host "creating isolated Windows build venv"
if (Test-Path $BuildVenv) {
    Remove-Item -Recurse -Force $BuildVenv
}
& $Python -m venv $BuildVenv
Invoke-Native "upgrading pip" $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
Invoke-Native "installing Windows build dependencies" $VenvPython @(
    "-m",
    "pip",
    "install",
    "-e",
    "$Root[windows,meeting]",
    "pyinstaller",
    "--quiet"
)

# Onedir, not onefile: a onefile engine unpacks its whole runtime into %TEMP% on
# every launch (~7 s for the 333 MB Store build), which outlasted the shell's
# handshake wait. The installed folder starts without unpacking.
Write-Host "freezing the Python engine sidecar (PyInstaller, onedir)"
Remove-Item Env:DICTATE_ONEFILE -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
    (Join-Path $Root "packaging\dist"), `
    (Join-Path $Root "packaging\build")

Push-Location $Root
try {
    Invoke-Native "freezing Python engine" $VenvPython @(
        "-m",
        "PyInstaller",
        (Join-Path $Root "packaging\dictate-engine.spec"),
        "--noconfirm",
        "--distpath",
        (Join-Path $Root "packaging\dist"),
        "--workpath",
        (Join-Path $Root "packaging\build"),
        "--log-level",
        "WARN"
    )
} finally {
    Pop-Location
}

$EngineDist = Join-Path $Root "packaging\dist\dictate-engine"
$Engine = Join-Path $EngineDist "dictate-engine.exe"
if (-not (Test-Path $Engine -PathType Leaf)) {
    throw "Freeze did not produce $Engine"
}
if (-not (Test-Path (Join-Path $EngineDist "_internal") -PathType Container)) {
    throw "Freeze did not produce the onedir runtime folder $EngineDist\_internal"
}

Write-Host "smoke-testing the frozen binary"
Invoke-Native "smoke-testing frozen engine" $Engine @("--version")

Write-Host "staging the engine folder into the Tauri bundle resources"
$StageDir = Join-Path $Root "ui-shell\src-tauri\engine"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $StageDir
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
# engine\dictate-engine.exe + engine\_internal\ (the shell starts the exe).
Copy-Item (Join-Path $EngineDist "*") $StageDir -Recurse -Force
if (-not (Test-Path (Join-Path $StageDir "_internal") -PathType Container)) {
    throw "Staging did not copy the engine runtime folder to $StageDir\_internal"
}
$PackageVersion = if ($env:DICTATE_PACKAGE_VERSION) { $env:DICTATE_PACKAGE_VERSION } else { "2026.7.4" }
$Distribution = @{ distribution = "direct"; packageVersion = $PackageVersion } | ConvertTo-Json -Compress
Set-Content -Path (Join-Path $StageDir "dictate-distribution.json") -Encoding ASCII -Value $Distribution

Write-Host "staging Parakeet v2 int8 for bundled local English ASR"
$ParakeetModelDir = Join-Path $StageDir "models\parakeet-tdt-0.6b-v2-onnx"
Invoke-Native "downloading Parakeet v2 int8 model files" $VenvPython @(
    (Join-Path $Root "scripts\prepare-parakeet-v2-int8-model.py"),
    "--output",
    $ParakeetModelDir
)

Write-Host "staging pyannote Community-1 for offline Meeting mode"
$PyannoteModelDir = Join-Path $StageDir "models\pyannote-speaker-diarization-community-1"
Invoke-Native "downloading pyannote Community-1 model snapshot" $VenvPython @(
    (Join-Path $Root "scripts\prepare-pyannote-community-model.py"),
    "--output",
    $PyannoteModelDir
)

Write-Host "staging third-party notices and model attributions"
Invoke-Native "staging third-party notices" $VenvPython @(
    (Join-Path $Root "scripts\stage-notices.py"),
    "--engine-dir",
    $StageDir
)

# The engine installs as a folder of files, so every path must fit under
# Windows/MSIX path limits once it sits below the install root
# (C:\Program Files\WindowsApps\<package full name>\ for the Store).
Write-Host "checking engine payload path lengths"
$MaxEnginePathLength = 150
$StagePrefix = $StageDir.TrimEnd("\") + "\"
$LongestEnginePath = Get-ChildItem -LiteralPath $StageDir -Recurse -File -Force |
    ForEach-Object { "engine\" + $_.FullName.Substring($StagePrefix.Length) } |
    Sort-Object Length -Descending |
    Select-Object -First 1
Write-Host "longest engine path ($($LongestEnginePath.Length) chars): $LongestEnginePath"
if ($LongestEnginePath.Length -gt $MaxEnginePathLength) {
    throw "Engine payload path is $($LongestEnginePath.Length) chars, over the $MaxEnginePathLength-char budget: $LongestEnginePath"
}

Write-Host "ensuring the Tauri CLI is available"
Invoke-Native "installing UI shell dependencies" "npm" @("--prefix", "ui-shell", "install")
Invoke-Native "checking Tauri CLI" "npm" @("--prefix", "ui-shell", "exec", "--", "tauri", "--version")

if ($NoBundle) {
    Write-Host "building Windows desktop executable (no installer bundle)"
} else {
    Write-Host "building Windows packages ($Bundles)"
}
Push-Location (Join-Path $Root "ui-shell")
try {
    if ($NoBundle) {
        Invoke-Native "building Tauri executable" "npm" @("run", "tauri", "--", "build", "--no-bundle")
    } else {
        Invoke-Native "building Tauri packages" "npm" @("run", "tauri", "--", "build", "--bundles", $Bundles)
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "artifacts:"
if ($NoBundle) {
    $Artifacts = @(
        Get-Item (Join-Path $Root "ui-shell\src-tauri\target\release\dictate-ui-shell.exe") -ErrorAction SilentlyContinue
    )
} else {
    $BundleRoot = Join-Path $Root "ui-shell\src-tauri\target\release\bundle"
    $Artifacts = Get-ChildItem $BundleRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".msi", ".exe" }
}

if (-not $Artifacts) {
    throw "No Windows desktop artifacts were produced."
}

$Artifacts | ForEach-Object { $_.FullName }
