$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:COMPUTERNAME -ne 'DESKTOP-JTGC2SG') { throw 'Wrong host' }

$release = 'C:\srv\V2-release-TLSFIX5-20261120'
$candidate = Join-Path $release 'package\candidate'
$common = Join-Path $candidate 'V2-install-common.ps1'
if ((Get-FileHash -LiteralPath $common).Hash -ne 'FB19F4D69A8D505CA17007C542387D4C89036BF5B4AC2E70D2E0AEDB4872A56E') {
    throw 'Installer common hash mismatch'
}
. $common
foreach ($parent in 'C:\', 'C:\srv') {
    if (@(Get-V2AclRisk -Acl (Get-V2Acl $parent) -Kind ancestor).Count) { throw 'Unsafe V2 ancestor ACL' }
}
$null = Assert-V2Root
$null = Assert-V2DataReady -DataDir (Join-Path $V2Root 'data')
$address = '100.111.221.74'
$hostName = 'desktop-jtgc2sg.taild5c033.ts.net'
$null = Assert-V2TargetIdentity -HostName $hostName -Addresses @($address)
$serviceEvidence = foreach ($name in 'integrity-v2-backend','integrity-v2-caddy') {
    $service = Get-V2Service $name
    $null = Assert-V2Service -Name $name -State Running
    $unresolved = New-Object 'System.Collections.Generic.List[object]'
    $tree = Get-V2ServiceTree -Name $name -Unresolved $unresolved
    if ($unresolved.Count -or -not $tree.Count) { throw "Incomplete service tree: $name" }
    foreach ($p in $tree) {
        if ($p.Owner -ne $V2Services[$name].Account) { throw "Unexpected process owner: $name" }
    }
    $bind = if ($name -eq 'integrity-v2-backend') { '127.0.0.1' } else { $address }
    $null = Wait-V2Listener -Port $V2Services[$name].Port -Tree $tree -Addresses $bind
    [pscustomobject]@{
        Name = $name
        State = $service.State
        Account = $service.StartName
        StartMode = $service.StartMode
        WrapperPid = $service.ProcessId
        WrapperStartUtcTicks = $tree[0].StartUtcTicks
        Tree = @($tree | ForEach-Object { [pscustomobject]@{ Pid = $_.Pid; ParentPid = $_.ParentPid; Owner = $_.Owner } })
    }
}
$ports = @(Get-V2Listeners -Ports @(80,443,8100,8199))
$unexpected = @($ports | Where-Object LocalPort -in 80,8199)
$expectedPids = @($serviceEvidence | ForEach-Object { $_.Tree | Select-Object -ExpandProperty Pid })
if ($unexpected.Count -or @(Get-V2UdpEndpoints -Ports @(443)).Count -or @(Get-V2SuspectProcesses | Where-Object { $_.ProcessId -notin $expectedPids }).Count) {
    throw 'Unexpected V2 process or listener'
}
$py = 'C:\Program Files\Python313\python.exe'
$dbTool = Join-Path $candidate 'v2_db_tool.py'
$expectedDbTool = 'C81E40A851ED9DBC7F5A187A521B46B6F368502CC6C700220A9D9446E5C1A837'
if ((Get-FileHash -LiteralPath $dbTool).Hash -ne $expectedDbTool) { throw 'DB tool hash mismatch' }
$data = Join-Path $V2Root 'data'
$backup = Join-Path $V2Root 'backups'
$liveDb = @(
    Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('verify', (Join-Path $data 'integrity_v2.db'), '--expect-version', '3')
    Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('verify', (Join-Path $data 'v2_auth.db'), '--expect-version', '1')
    Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('auth-schema', (Join-Path $data 'v2_auth.db'))
    Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('users', (Join-Path $data 'v2_auth.db'))
)
$fingerprint = Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('fingerprint', (Join-Path $data 'integrity_v2.db'))
$lines = @(Get-Content -LiteralPath (Join-Path $backup 'SHA256SUMS.txt') | Where-Object { $_ })
if ($lines.Count -ne 2) { throw 'Expected two initial backup hashes' }
$types = @{}
$initialBackups = foreach ($line in $lines) {
    if ($line -notmatch '^([0-9a-f]{64})  ((integrity_v2|v2_auth)-initial-[0-9]{8}-[0-9]{6}\.db)$') {
        throw 'Invalid backup manifest entry'
    }
    $sha, $leaf, $dbName = $Matches[1], $Matches[2], $Matches[3]
    if ($types.ContainsKey($dbName)) { throw 'Duplicate database in backup manifest' }
    $types[$dbName] = $true
    $path = Join-Path $backup $leaf
    $version = if ($dbName -eq 'integrity_v2') { '3' } else { '1' }
    if ((Get-FileHash -LiteralPath $path).Hash -ne $sha) { throw 'Initial backup checksum mismatch' }
    $check = Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('verify', $path, '--expect-version', $version)
    $schema = if ($dbName -eq 'v2_auth') { Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('auth-schema', $path) }
    [pscustomobject]@{ File = $leaf; SHA256 = $sha; Verify = $check; AuthSchema = $schema }
}
[pscustomobject]@{
    Utc = [DateTime]::UtcNow.ToString('o')
    Identity = @{ HostName = $hostName; Address = $address; TargetCheck = 'PASS' }
    Services = @($serviceEvidence)
    TcpListeners = @($ports | Select-Object LocalAddress,LocalPort,OwningProcess)
    DB = $liveDb
    InitialBackups = @($initialBackups)
    IntegrityFingerprint = $fingerprint
    ReleaseSHA256 = (Get-FileHash -LiteralPath (Join-Path $release 'TLSFIX5.zip')).Hash
    PublicCertificateSHA256 = (Get-FileHash -LiteralPath (Join-Path $V2Root 'caddy\tls\site.crt')).Hash
    CaddyfileSHA256 = (Get-FileHash -LiteralPath (Join-Path $V2Root 'caddy\Caddyfile')).Hash
} | ConvertTo-Json -Depth 7 -Compress