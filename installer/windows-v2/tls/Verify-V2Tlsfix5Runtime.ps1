# Verify-V2Tlsfix5Runtime.ps1 — read-only доказ стану працюючого V2 (TLS, служби, БД, початкові копії).
# Поточний реліз: служби Automatic (Delayed Start) або Manual; версії БД — з файлів (v2_db_tool user-version, лише SCHEMA_SPECS) +
# строга схема; служба integrity-v2-lm (якщо встановлена) має працювати (лише 127.0.0.1:8200), її дерево — не «зайвий процес V2».
# common і v2_db_tool — з каталогу інсталятора цього релізу (..\); -CommonSha256 / -DbToolSha256 — необов'язкове закріплення.
[CmdletBinding()]
param([string] $CommonSha256, [string] $DbToolSha256, [string] $Python = 'C:\Program Files\Python313\python.exe')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:COMPUTERNAME -ne 'DESKTOP-JTGC2SG') { throw 'Wrong host' }

$kit = Split-Path -Parent $PSScriptRoot
$common = Join-Path $kit 'V2-install-common.ps1'
$dbTool = Join-Path $kit 'v2_db_tool.py'
if ($CommonSha256 -and (Get-FileHash -LiteralPath $common).Hash -ne $CommonSha256) { throw 'Installer common hash mismatch' }
if ($DbToolSha256 -and (Get-FileHash -LiteralPath $dbTool).Hash -ne $DbToolSha256) { throw 'DB tool hash mismatch' }
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
    $null = Assert-V2Service -Name $name -State Running -StartModes Manual, Auto
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
        DelayedAutoStart = [bool]($service.PSObject.Properties['DelayedAutoStart'] -and $service.DelayedAutoStart)
        WrapperPid = $service.ProcessId
        WrapperStartUtcTicks = $tree[0].StartUtcTicks
        Tree = @($tree | ForEach-Object { [pscustomobject]@{ Pid = $_.Pid; ParentPid = $_.ParentPid; Owner = $_.Owner } })
    }
}
$lm = Get-V2LmServiceEvidence                                                  # $null — LM не встановлено; інакше Running, лише 127.0.0.1:8200
$ports = @(Get-V2Listeners -Ports @(80,443,8100,8199))
$unexpected = @($ports | Where-Object LocalPort -in 80,8199)
$expectedPids = @($serviceEvidence | ForEach-Object { $_.Tree | Select-Object -ExpandProperty Pid })
$lmPids = @(if ($lm) { $lm.Pids })
if ($unexpected.Count -or @(Get-V2UdpEndpoints -Ports @(443)).Count -or @(Get-V2SuspectProcesses -IgnorePids $lmPids | Where-Object { $_.ProcessId -notin $expectedPids }).Count) {
    throw 'Unexpected V2 process or listener'
}
$py = $Python
$data = Join-Path $V2Root 'data'
$backup = Join-Path $V2Root 'backups'
$liveDb = @(
    Assert-V2DbStrict -Py $py -DbTool $dbTool -Path (Join-Path $data 'integrity_v2.db') -Kind integrity
    Assert-V2DbStrict -Py $py -DbTool $dbTool -Path (Join-Path $data 'v2_auth.db') -Kind auth
)
$users = Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('users', (Join-Path $data 'v2_auth.db'))
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
    if ((Get-FileHash -LiteralPath $path).Hash -ne $sha) { throw 'Initial backup checksum mismatch' }
    # початкові копії мають версію схеми на момент Clean Install (напр. 3/1 у TLSFIX5, 6/2 у поточному) — з файла, строго
    $strict = Assert-V2DbStrict -Py $py -DbTool $dbTool -Path $path -Kind $(if ($dbName -eq 'integrity_v2') { 'integrity' } else { 'auth' })
    [pscustomobject]@{ File = $leaf; SHA256 = $sha; Version = $strict.Version; Verify = $strict.Verify; Schema = $strict.Schema }
}
$release = $null
try { $release = Split-Path -Leaf (Get-V2ReleaseDir) } catch { $release = "unknown: $($_.Exception.Message)" }
[pscustomobject]@{
    Utc = [DateTime]::UtcNow.ToString('o')
    Identity = @{ HostName = $hostName; Address = $address; TargetCheck = 'PASS' }
    Release = $release
    Services = @($serviceEvidence)
    Lm = if ($lm) { [pscustomobject]@{ State = $lm.State; StartMode = $lm.StartMode; WrapperPid = $lm.WrapperPid; Members = $lm.Pids; Listener = '127.0.0.1:8200' } } else { 'NotInstalled' }
    TcpListeners = @($ports | Select-Object LocalAddress,LocalPort,OwningProcess)
    DB = @($liveDb | Select-Object Kind, Version, Verify, Schema)
    Users = $users
    InitialBackups = @($initialBackups)
    IntegrityFingerprint = $fingerprint
    PublicCertificateSHA256 = $(if (Test-Path -LiteralPath (Join-Path $V2Root 'caddy\tls\site.crt')) { (Get-FileHash -LiteralPath (Join-Path $V2Root 'caddy\tls\site.crt')).Hash } else { 'NoFileTls' })
    CaddyfileSHA256 = (Get-FileHash -LiteralPath (Join-Path $V2Root 'caddy\Caddyfile')).Hash
} | ConvertTo-Json -Depth 7 -Compress
