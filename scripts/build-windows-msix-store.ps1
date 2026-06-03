# Build a Microsoft Store MSIX package for the reserved Arc Forge Dictate app.
#
# This path targets Partner Center product 9P5S7747V0BP (MSIX or PWA app).
# It is separate from the MSI/NSIS direct-download builder.
#
# Produces:
#   packaging\msix\out\ArcForgeDictate_<version>_x64.msix
#
# Requirements:
#   - Windows 11 runner or workstation
#   - Python 3.11/3.12
#   - Node/npm
#   - Rust toolchain
#   - winapp CLI (`winget install microsoft.winappcli --source winget`)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-msix-store.ps1

[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Architecture = "x64"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command '$Name'. Install it before building the Store MSIX package."
    }
}

function Convert-ToMsixVersion {
    param([Parameter(Mandatory = $true)][string]$Version)
    $parts = @($Version.Split(".") | ForEach-Object { [int]$_ })
    if ($parts.Count -gt 4) {
        throw "MSIX version must have at most four numeric parts: $Version"
    }
    while ($parts.Count -lt 4) {
        $parts += 0
    }
    foreach ($part in $parts) {
        if ($part -lt 0 -or $part -gt 65535) {
            throw "MSIX version component is outside 0..65535: $part"
        }
    }
    return ($parts -join ".")
}

function Resize-Png {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][int]$Width,
        [Parameter(Mandatory = $true)][int]$Height
    )

    Add-Type -AssemblyName System.Drawing
    $sourceImage = [System.Drawing.Image]::FromFile($Source)
    try {
        $bitmap = New-Object System.Drawing.Bitmap $Width, $Height
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            try {
                $graphics.Clear([System.Drawing.Color]::Transparent)
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $graphics.DrawImage($sourceImage, 0, 0, $Width, $Height)
            } finally {
                $graphics.Dispose()
            }
            $bitmap.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
        } finally {
            $bitmap.Dispose()
        }
    } finally {
        $sourceImage.Dispose()
    }
}

Write-Host "preflight"
if (-not $IsWindows) {
    throw "MSIX packaging must run on Windows."
}
Require-Command $Python
Require-Command "npm"
Require-Command "cargo"
Require-Command "winapp"

$TauriConfigPath = Join-Path $Root "ui-shell\src-tauri\tauri.conf.json"
$TauriConfig = Get-Content $TauriConfigPath -Raw | ConvertFrom-Json
$MsixVersion = Convert-ToMsixVersion $TauriConfig.version

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

Push-Location (Join-Path $Root "packaging")
try {
    & $VenvPython -m PyInstaller dictate-engine.spec --noconfirm `
        --distpath dist --workpath build --log-level WARN
} finally {
    Pop-Location
}

$Engine = Join-Path $Root "packaging\dist\dictate-engine.exe"
if (-not (Test-Path $Engine)) {
    throw "Freeze did not produce $Engine"
}

Write-Host "smoke-testing the frozen binary"
& $Engine --version | Out-Null

Write-Host "building the Tauri shell executable without an installer"
Push-Location (Join-Path $Root "ui-shell")
try {
    try {
        npm --prefix . exec -- tauri --version | Out-Null
    } catch {
        npm install
    }
    npm run tauri -- build --no-bundle
} finally {
    Pop-Location
}

$ShellExe = Join-Path $Root "ui-shell\src-tauri\target\release\dictate-ui-shell.exe"
if (-not (Test-Path $ShellExe)) {
    throw "Tauri build did not produce $ShellExe"
}

$MsixRoot = Join-Path $Root "packaging\msix"
$Dist = Join-Path $MsixRoot "dist"
$Assets = Join-Path $Dist "Assets"
$OutDir = Join-Path $MsixRoot "out"
$ManifestTemplate = Join-Path $MsixRoot "Package.appxmanifest.in"
$Manifest = Join-Path $Dist "Package.appxmanifest"
$Output = Join-Path $OutDir "ArcForgeDictate_${MsixVersion}_${Architecture}.msix"

Write-Host "staging MSIX loose layout"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Dist, $OutDir
New-Item -ItemType Directory -Force -Path $Dist, $Assets, (Join-Path $Dist "engine"), $OutDir | Out-Null
Copy-Item $ShellExe (Join-Path $Dist "dictate-ui-shell.exe")
Copy-Item $Engine (Join-Path $Dist "engine\dictate-engine.exe")

$ManifestContent = Get-Content $ManifestTemplate -Raw
$ManifestContent = $ManifestContent.Replace("{{VERSION}}", $MsixVersion)
Set-Content -Path $Manifest -Value $ManifestContent -Encoding UTF8

$Icon = Join-Path $Root "ui-shell\src-tauri\icons\icon.png"
Resize-Png $Icon (Join-Path $Assets "StoreLogo.png") 50 50
Resize-Png $Icon (Join-Path $Assets "Square44x44Logo.png") 44 44
Resize-Png $Icon (Join-Path $Assets "Square150x150Logo.png") 150 150

Write-Host "packing MSIX"
if (Test-Path $Output) {
    Remove-Item -Force $Output
}
winapp tool makeappx pack /d $Dist /p $Output /o

if (-not (Test-Path $Output)) {
    throw "MSIX package was not produced: $Output"
}

Write-Host ""
Write-Host "artifact:"
Write-Host $Output
