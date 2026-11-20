[CmdletBinding()]
param([switch] $ProveAcquisition)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$folder = 'C:\srv\V2-release-TLSFIX5-20261120\tls-maintenance'
$root = 'C:\srv\integrity-v2'
$renew = Join-Path $folder 'Renew-V2TlsPair.ps1'
$request = Join-Path $folder 'Request-V2TlsPair.ps1'
$common = 'C:\srv\V2-release-TLSFIX5-20261120\package\candidate\V2-install-common.ps1'
$log = if ($ProveAcquisition) { Join-Path $folder 'smoke.json' } else { Join-Path $folder 'latest.json' }
$state = [ordered]@{ Utc = [DateTime]::UtcNow.ToString('o'); Status = 'Blocked'; Acquisition = $null }
$code = 1
try {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($env:COMPUTERNAME -ne 'DESKTOP-JTGC2SG' -or $sid -ne 'S-1-5-18') { throw 'Unexpected host or identity' }
    foreach ($entry in @(
        @($common, 'FB19F4D69A8D505CA17007C542387D4C89036BF5B4AC2E70D2E0AEDB4872A56E'),
        @($renew, '62344FAD161B0AA0E45D94CD5F02EC7E0E98FE8D13D145910D1221BF6EF6BFAF'),
        @($request, 'AFDDD64B44BF3B43C19874B764CC92DAE498FC6FF4A6C0FC8AC5BAE12189B008')
    )) {
        if ((Get-FileHash -LiteralPath $entry[0]).Hash -cne $entry[1]) { throw 'Maintenance hash mismatch' }
    }
    . $common
    $null = Assert-V2DataReady -DataDir (Join-Path $root 'data')
    $state.Principal = $sid
    $state.Renewal = & $renew | ConvertFrom-Json
    if ($ProveAcquisition) {
        if ($state.Renewal.Status -ne 'NotDue') { throw 'Expected no live replacement on first smoke' }
        $state.Acquisition = & $request -DecisionRef 'Commander-5-20261120-TLS-Renewal-SYSTEM-Smoke' | ConvertFrom-Json
        if (-not $state.Acquisition.TrustedChainAndSni -or -not $state.Acquisition.KeyMatches) { throw 'Certificate acquisition proof incomplete' }
    }
    $state.Status = 'PASS'
    $code = 0
} catch {
    $state.ErrorCategory = [string]$_.CategoryInfo.Category
    $state.ErrorType = $_.Exception.GetType().Name
    $state.ErrorScript = [IO.Path]::GetFileName($_.InvocationInfo.ScriptName)
    $state.ErrorLine = $_.InvocationInfo.ScriptLineNumber
} finally {
    [IO.File]::WriteAllText($log, ($state | ConvertTo-Json -Depth 7 -Compress))
}
exit $code
