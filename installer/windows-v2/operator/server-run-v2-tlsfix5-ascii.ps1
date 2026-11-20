# One-time interactive launcher for the signed-in server desktop.
# Keep this file ASCII so Windows PowerShell 5.1 parses it on all system locales.
param(
    [switch] $PreflightOnly,
    [Parameter(Mandatory)][string] $TlsPairDirectory,
    [Parameter(Mandatory)][string] $TlsCertificateSha256
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $packageRoot 'candidate\clean-install.ps1'
$common = Join-Path $packageRoot 'candidate\V2-install-common.ps1'
$tools = Join-Path $packageRoot 'artifacts\integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip'
$deploy = Join-Path $packageRoot 'artifacts\integrity-v2-schema3-manager-deploy.zip'
$python = 'C:\Program Files\Python313\python.exe'

if ($env:COMPUTERNAME -ine 'V2-HOST') { throw 'Wrong target computer' }
foreach ($file in @($installer, $common, $tools, $deploy, $python)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing file: $file" }
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLower() -ne '856d5a7ccfa3c80e3d01b5db44c6862810d10e04ef1ac122f57155775ed733f2') { throw 'Installer hash mismatch' }
if ((Get-FileHash -LiteralPath $common -Algorithm SHA256).Hash.ToLower() -ne 'fb19f4d69a8d505ca17007c542387d4c89036bf5b4ac2e70d2e0aedb4872a56e') { throw 'Common installer hash mismatch' }
if ((Get-FileHash -LiteralPath $tools -Algorithm SHA256).Hash.ToLower() -ne 'abce6a9ce7afde4ab938d2d66062abf732668960c8c12b53fdd2e9d9b68fbaba') { throw 'Tools ZIP hash mismatch' }
if ((Get-FileHash -LiteralPath $deploy -Algorithm SHA256).Hash.ToLower() -ne 'd7c523a167eec578a03ed9b0ede62868aed1d4c59f50fbf2b78f997fbb79a5db') { throw 'Deploy ZIP hash mismatch' }
. $common
Assert-V2Ancestors | Out-Null
Assert-V2StagedTlsPair -Path $TlsPairDirectory -CertificateSha256 $TlsCertificateSha256 | Out-Null
if ($PreflightOnly) {
    Write-Output 'LAUNCHER_PREFLIGHT_PASS'
    return
}

$Host.UI.RawUI.WindowTitle = 'V2 TLSFIX5 Clean Install - enter settings here'
$adminEmail = Read-Host 'Bootstrap admin Gmail address'
if ($adminEmail -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') { throw 'Invalid admin email address' }

& $installer -DecisionRef 'Commander-5-20261120-Final-V2-GO' `
    -SrvDecisionRef 'User-2026-11-20-create-C-srv-for-V2' `
    -ToolsZip $tools -DeployZip $deploy -PyBase $python `
    -ExpectedWindowsBuild 26200 -AdminName 'V2 Administrator' -AdminEmail $adminEmail `
    -TlsPairDirectory $TlsPairDirectory -TlsCertificateSha256 $TlsCertificateSha256
exit $LASTEXITCODE
