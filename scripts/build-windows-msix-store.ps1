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
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command '$Name'. Install it before building the Store MSIX package."
    }
}

function Find-MakeAppxCommand {
    $WinApp = Get-Command "winapp" -ErrorAction SilentlyContinue
    if ($WinApp) {
        return @{ Kind = "winapp"; Path = $WinApp.Source }
    }

    $MakeAppx = Get-Command "makeappx.exe" -ErrorAction SilentlyContinue
    if ($MakeAppx) {
        return @{ Kind = "makeappx"; Path = $MakeAppx.Source }
    }

    $SdkRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (Test-Path $SdkRoot) {
        $SdkMakeAppx = Get-ChildItem $SdkRoot -Recurse -Filter "makeappx.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\makeappx\.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($SdkMakeAppx) {
            return @{ Kind = "makeappx"; Path = $SdkMakeAppx.FullName }
        }
    }

    throw "Missing MSIX packaging tool. Install winapp CLI or the Windows SDK MakeAppx tool."
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

function Invoke-MakeAppx {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    if ($Command.Kind -eq "winapp") {
        & $Command.Path tool makeappx @Arguments
    } else {
        & $Command.Path @Arguments
    }
}

function Assert-MsixPackage {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Command,
        [Parameter(Mandatory = $true)][string]$PackagePath,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    $InspectDir = Join-Path ([System.IO.Path]::GetTempPath()) ("dictate-msix-inspect-" + [guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Force -Path $InspectDir | Out-Null
        Invoke-MakeAppx -Command $Command -Arguments @("unpack", "/p", $PackagePath, "/d", $InspectDir, "/o")
        $ManifestPath = Join-Path $InspectDir "AppxManifest.xml"
        if (-not (Test-Path $ManifestPath)) {
            throw "MSIX validation failed: missing AppxManifest.xml"
        }
        [xml]$Manifest = Get-Content $ManifestPath -Raw
        $Identity = $Manifest.Package.Identity
        if ($Identity.Name -ne "ArcForgeLabs.ArcForgeDictate") {
            throw "MSIX validation failed: unexpected identity '$($Identity.Name)'"
        }
        if ($Identity.Publisher -ne "CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C") {
            throw "MSIX validation failed: unexpected publisher '$($Identity.Publisher)'"
        }
        if ($Identity.Version -ne $ExpectedVersion) {
            throw "MSIX validation failed: expected version '$ExpectedVersion', got '$($Identity.Version)'"
        }
        foreach (
            $Payload in @(
                "dictate-ui-shell.exe",
                "engine\dictate-engine.exe",
                "engine\models\parakeet-tdt-0.6b-v2-onnx\config.json",
                "engine\models\parakeet-tdt-0.6b-v2-onnx\vocab.txt",
                "engine\models\pyannote-speaker-diarization-community-1\config.*"
            )
        ) {
            $PayloadPath = Join-Path $InspectDir $Payload
            if (-not (Test-Path $PayloadPath)) {
                throw "MSIX validation failed: missing payload '$Payload'"
            }
        }
    } finally {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $InspectDir
    }
}

function Assert-MsixStagePayload {
    param(
        [Parameter(Mandatory = $true)][string]$StageDir
    )

    foreach (
        $Payload in @(
            "dictate-ui-shell.exe",
            "engine\dictate-engine.exe",
            "engine\models\parakeet-tdt-0.6b-v2-onnx\config.json",
            "engine\models\parakeet-tdt-0.6b-v2-onnx\vocab.txt",
            "engine\models\pyannote-speaker-diarization-community-1\config.*"
        )
    ) {
        $PayloadPath = Join-Path $StageDir $Payload
        if (-not (Test-Path $PayloadPath)) {
            throw "MSIX staging failed: missing payload '$Payload'"
        }
    }
}

Write-Host "preflight"
$IsWindowsVariable = Get-Variable -Name IsWindows -ErrorAction SilentlyContinue
$RunningOnWindows = if ($IsWindowsVariable) { [bool]$IsWindowsVariable.Value } else { $env:OS -eq "Windows_NT" }
if (-not $RunningOnWindows) {
    throw "MSIX packaging must run on Windows."
}
Require-Command $Python
Require-Command "npm"
Require-Command "cargo"
$MakeAppxCommand = Find-MakeAppxCommand

$TauriConfigPath = Join-Path $Root "ui-shell\src-tauri\tauri.conf.json"
$TauriConfig = Get-Content $TauriConfigPath -Raw | ConvertFrom-Json
$MsixVersion = Convert-ToMsixVersion $TauriConfig.version

Write-Host "building shared Windows desktop payload"
& (Join-Path $Root "scripts\build-windows-desktop.ps1") -Python $Python -Bundles "no-bundle"
if ($LASTEXITCODE -ne 0) {
    throw "Windows desktop payload build failed with exit code $LASTEXITCODE."
}

$ShellExe = Join-Path $Root "ui-shell\src-tauri\target\release\dictate-ui-shell.exe"
if (-not (Test-Path $ShellExe)) {
    throw "Tauri build did not produce $ShellExe"
}
$Engine = Join-Path $Root "ui-shell\src-tauri\target\release\engine\dictate-engine.exe"
if (-not (Test-Path $Engine)) {
    throw "Desktop payload build did not produce $Engine"
}

$MsixRoot = Join-Path $Root "packaging\msix"
$Dist = Join-Path $MsixRoot "dist"
$Assets = Join-Path $Dist "Assets"
$OutDir = Join-Path $MsixRoot "out"
$ManifestTemplate = Join-Path $MsixRoot "Package.appxmanifest.in"
$Manifest = Join-Path $Dist "AppxManifest.xml"
$Output = Join-Path $OutDir "ArcForgeDictate_${MsixVersion}_${Architecture}.msix"

Write-Host "staging MSIX loose layout"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Dist, $OutDir
New-Item -ItemType Directory -Force -Path $Dist, $Assets, (Join-Path $Dist "engine"), $OutDir | Out-Null
Copy-Item $ShellExe (Join-Path $Dist "dictate-ui-shell.exe")
Copy-Item (Join-Path $Root "ui-shell\src-tauri\engine\*") (Join-Path $Dist "engine") -Recurse -Force

Assert-MsixStagePayload -StageDir $Dist

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
Invoke-MakeAppx -Command $MakeAppxCommand -Arguments @("pack", "/d", $Dist, "/p", $Output, "/o")

if (-not (Test-Path $Output)) {
    throw "MSIX package was not produced: $Output"
}

Write-Host "validating MSIX package contents"
Assert-MsixPackage -Command $MakeAppxCommand -PackagePath $Output -ExpectedVersion $MsixVersion

Write-Host ""
Write-Host "artifact:"
Write-Host $Output
