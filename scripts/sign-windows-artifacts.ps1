# Authenticode-sign Windows installer artifacts before public release upload.
#
# Supported credential modes:
# - WINDOWS_SIGNING_PFX_B64 + WINDOWS_SIGNING_PFX_PASSWORD
# - WINDOWS_SIGNING_CERT_PATH + WINDOWS_SIGNING_PFX_PASSWORD
#
# The script writes decoded PFX material only to RUNNER_TEMP and deletes it when
# finished. It never prints certificate secrets.

[CmdletBinding()]
param(
    [string]$BundleRoot = "ui-shell\src-tauri\target\release\bundle",
    [string]$TimestampUrl = $env:WINDOWS_SIGNING_TIMESTAMP_URL,
    [string]$CertificatePath = $env:WINDOWS_SIGNING_CERT_PATH,
    [string]$PfxBase64 = $env:WINDOWS_SIGNING_PFX_B64,
    [string]$PfxPassword = $env:WINDOWS_SIGNING_PFX_PASSWORD
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $TimestampUrl) {
    $TimestampUrl = "http://timestamp.digicert.com"
}

if (-not (Test-Path $BundleRoot)) {
    throw "Bundle root not found: $BundleRoot"
}

$Artifacts = Get-ChildItem $BundleRoot -Recurse -File |
    Where-Object { $_.Extension -in ".msi", ".exe" }

if (-not $Artifacts) {
    throw "No Windows installer artifacts found under $BundleRoot"
}

$TempPfx = $null
try {
    if (-not $CertificatePath -and $PfxBase64) {
        $TempRoot = $env:RUNNER_TEMP
        if (-not $TempRoot) {
            $TempRoot = [System.IO.Path]::GetTempPath()
        }
        $TempPfx = Join-Path $TempRoot "dictate-windows-signing.pfx"
        [System.IO.File]::WriteAllBytes($TempPfx, [System.Convert]::FromBase64String($PfxBase64))
        $CertificatePath = $TempPfx
    }

    if (-not $CertificatePath) {
        throw "No signing certificate configured. Set WINDOWS_SIGNING_PFX_B64 or WINDOWS_SIGNING_CERT_PATH."
    }
    if (-not (Test-Path $CertificatePath)) {
        throw "Signing certificate path not found: $CertificatePath"
    }

    $SignTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $SignTool) {
        $Candidates = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
            -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        $SignTool = $Candidates | Select-Object -First 1
    }
    if (-not $SignTool) {
        throw "signtool.exe was not found. Install the Windows SDK signing tools."
    }

    foreach ($Artifact in $Artifacts) {
        Write-Host "Signing $($Artifact.FullName)"
        $Args = @(
            "sign",
            "/f", $CertificatePath,
            "/fd", "SHA256",
            "/tr", $TimestampUrl,
            "/td", "SHA256",
            $Artifact.FullName
        )
        if ($PfxPassword) {
            $Args = @(
                "sign",
                "/f", $CertificatePath,
                "/p", $PfxPassword,
                "/fd", "SHA256",
                "/tr", $TimestampUrl,
                "/td", "SHA256",
                $Artifact.FullName
            )
        }
        & $SignTool.Source @Args
        if ($LASTEXITCODE -ne 0) {
            throw "signtool failed for $($Artifact.FullName)"
        }
    }

    & (Join-Path $PSScriptRoot "assert-windows-artifacts-signed.ps1") -BundleRoot $BundleRoot
}
finally {
    if ($TempPfx -and (Test-Path $TempPfx)) {
        Remove-Item -Force $TempPfx
    }
}
