# Verify that Windows installer artifacts are signed before they are attached to
# a public GitHub release.

[CmdletBinding()]
param(
    [string]$BundleRoot = "ui-shell\src-tauri\target\release\bundle"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path $BundleRoot)) {
    throw "Bundle root not found: $BundleRoot"
}

$Artifacts = Get-ChildItem $BundleRoot -Recurse -File |
    Where-Object { $_.Extension -in ".msi", ".exe" }

if (-not $Artifacts) {
    throw "No Windows installer artifacts found under $BundleRoot"
}

$Unsigned = @()
foreach ($Artifact in $Artifacts) {
    $Signature = Get-AuthenticodeSignature -FilePath $Artifact.FullName
    if ($Signature.Status -ne "Valid") {
        $Unsigned += [pscustomobject]@{
            Path = $Artifact.FullName
            Status = [string]$Signature.Status
            Message = [string]$Signature.StatusMessage
        }
    }
}

if ($Unsigned.Count -gt 0) {
    Write-Host "Unsigned or invalid Windows artifacts:"
    $Unsigned | Format-Table -AutoSize | Out-String | Write-Host
    throw "Windows artifacts must be Authenticode-signed before public release upload."
}

Write-Host "All Windows installer artifacts are signed:"
$Artifacts | ForEach-Object { Write-Host $_.FullName }
