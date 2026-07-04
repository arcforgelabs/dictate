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
Set-StrictMode -Version Latest

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

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

Write-Host "preflight"
Require-Command $Python
Require-Command "npm"
Require-Command "cargo"

Write-Host "building the front-end (ui/ -> dist/)"
try {
    npm --prefix ui ci
} catch {
    npm --prefix ui install
}
npm --prefix ui run build

$BuildVenv = Join-Path $Root "packaging\.build-venv-windows"
$VenvPython = Join-Path $BuildVenv "Scripts\python.exe"

Write-Host "creating isolated Windows build venv"
if (Test-Path $BuildVenv) {
    Remove-Item -Recurse -Force $BuildVenv
}
& $Python -m venv $BuildVenv
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -e "$Root[windows]" pyinstaller --quiet

Write-Host "freezing the Python engine sidecar (PyInstaller, onefile)"
$env:DICTATE_ONEFILE = "1"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
    (Join-Path $Root "packaging\dist"), `
    (Join-Path $Root "packaging\build")

Push-Location $Root
try {
    & $VenvPython -m PyInstaller (Join-Path $Root "packaging\dictate-engine.spec") --noconfirm `
        --distpath (Join-Path $Root "packaging\dist") `
        --workpath (Join-Path $Root "packaging\build") `
        --log-level WARN
} finally {
    Pop-Location
}

$Engine = Join-Path $Root "packaging\dist\dictate-engine.exe"
if (-not (Test-Path $Engine)) {
    throw "Freeze did not produce $Engine"
}

Write-Host "smoke-testing the frozen binary"
& $Engine --version | Out-Null

Write-Host "staging the engine into the Tauri bundle resources"
$StageDir = Join-Path $Root "ui-shell\src-tauri\engine"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $StageDir
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
Copy-Item $Engine (Join-Path $StageDir "dictate-engine.exe")

Write-Host "ensuring the Tauri CLI is available"
npm --prefix ui-shell install
npm --prefix ui-shell exec -- tauri --version | Out-Null

if ($NoBundle) {
    Write-Host "building Windows desktop executable (no installer bundle)"
} else {
    Write-Host "building Windows packages ($Bundles)"
}
Push-Location (Join-Path $Root "ui-shell")
try {
    if ($NoBundle) {
        npm run tauri -- build --no-bundle
    } else {
        npm run tauri -- build --bundles $Bundles
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
