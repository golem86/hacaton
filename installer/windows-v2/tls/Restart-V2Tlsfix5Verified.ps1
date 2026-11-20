$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:COMPUTERNAME -ne 'DESKTOP-JTGC2SG') { throw 'Wrong host' }
$candidate = 'C:\srv\V2-release-TLSFIX5-20261120\package\candidate'
$common = Join-Path $candidate 'V2-install-common.ps1'
if ((Get-FileHash -LiteralPath $common).Hash -ne 'FB19F4D69A8D505CA17007C542387D4C89036BF5B4AC2E70D2E0AEDB4872A56E') { throw 'Common script hash mismatch' }
. $common
$null = Assert-V2Root
$data = Join-Path $V2Root 'data'
$null = Assert-V2DataReady -DataDir $data
$backendName = 'integrity-v2-backend'
$caddyName = 'integrity-v2-caddy'
$address = '100.111.221.74'
$hostName = 'desktop-jtgc2sg.taild5c033.ts.net'
$pin = @{ HostName = $hostName; Addresses = @($address) }
$record = [ordered]@{ BeganUtc = [DateTime]::UtcNow.ToString('o'); Before = @(); Backups = @(); After = @(); State = 'InProgress' }
$trees = @{}
$py = 'C:\Program Files\Python313\python.exe'
$dbTool = Join-Path $candidate 'v2_db_tool.py'
if ((Get-FileHash -LiteralPath $dbTool).Hash -ne 'C81E40A851ED9DBC7F5A187A521B46B6F368502CC6C700220A9D9446E5C1A837') { throw 'Database tool hash mismatch' }

function Capture-Service([string]$Name,$Store) {
    $null = Assert-V2Service -Name $Name -State Running
    $service = Get-V2Service $Name
    $unresolved = New-Object 'System.Collections.Generic.List[object]'
    $tree = Get-V2ServiceTree -Name $Name -Unresolved $unresolved
    if ($unresolved.Count -or -not $tree.Count -or $tree[0].Pid -ne $service.ProcessId) { throw "Incomplete process evidence: $Name" }
    $owner = $V2Services[$Name].Account
    $expectedSid = Get-V2ServiceSid $Name
    foreach ($p in $tree) {
        $proc = Get-V2CimProcess $p.Pid
        if (-not $proc) { throw "Process changed during capture: $Name" }
        $check = Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid
        if ($p.Owner -ine $owner -or $check.ReturnValue -ne 0 -or $check.Sid -ne $expectedSid) {
            throw "Unexpected process owner: $Name"
        }
    }
    $Store[$Name] = $tree
    $bind = if ($Name -eq $backendName) { '127.0.0.1' } else { $address }
    $null = Wait-V2Listener -Port $V2Services[$Name].Port -Tree $tree -Addresses $bind
    [pscustomobject]@{ Name = $Name; PID = $service.ProcessId; Sid = $expectedSid; Members = @($tree | Select-Object -ExpandProperty Pid) }
}

function Stop-VerifiedService([string]$Name) {
    $null = Assert-V2Service -Name $Name -State Running
    $service = Get-V2Service $Name
    $known = $trees[$Name]
    if ($service.ProcessId -ne $known[0].Pid -or (Test-V2HandleExited $known[0].Handle)) { throw "Wrapper PID changed: $Name" }
    $controller = Get-Service -Name $Name
    if (@($controller.DependentServices | Where-Object Status -ne 'Stopped').Count) { throw "Active service dependency: $Name" }
    $controller.Stop()
    $controller.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    $null = Assert-V2Service -Name $Name -State Stopped
    if ((Get-V2Service $Name).ProcessId) { throw "SCM still reports a PID: $Name" }
    $null = Assert-V2TreeExited -Tree $known
    if (@(Get-V2LateDescendants -Tree $known).Count -or @(Get-V2Listeners -Ports @($V2Services[$Name].Port)).Count) {
        throw "Service left a child or listener: $Name"
    }
}

function Start-VerifiedServices {
    if ((Get-V2Service $backendName).State -eq 'Stopped') {
        $null = Invoke-V2ServiceStart -Name $backendName -Checks {
            Assert-V2ServiceRunning -Name $backendName -Addresses '127.0.0.1'
            Wait-V2Http -Url 'http://127.0.0.1:8100/api/health' -Expected 200
        }
    }
    if ((Get-V2Service $backendName).State -ne 'Running') { throw 'Backend did not start cleanly' }
    if ((Get-V2Service $caddyName).State -eq 'Stopped') {
        $null = Invoke-V2ServiceStart -Name $caddyName -Checks {
            Assert-V2ServiceRunning -Name $caddyName -Addresses $address
            Assert-V2PinnedHttps @pin -Path '/api/health' -Expected 200
        }
    }
    if ((Get-V2Service $caddyName).State -ne 'Running') { throw 'Caddy did not start cleanly' }
}

$record.Before = @(Capture-Service $backendName $trees; Capture-Service $caddyName $trees)
$known = @($trees[$backendName].ToArray() + $trees[$caddyName].ToArray())
$record.PreRestartHTTPS = [bool](Assert-V2PinnedHttps @pin -Path '/api/health' -Expected 200)
$backupError = $null
Stop-VerifiedService $caddyName
Stop-VerifiedService $backendName
$null = Assert-V2NoProcesses -DataDir $data -Known $known
$record.FullStop = 'PASS: SCM, both known trees, late descendants, sockets and SQLite handles'
try {
    $stamp = Get-Date -Format yyyyMMdd-HHmmss
    $dir = Join-Path $V2Root "backups\restart-verified-$stamp"
    $null = New-Item -ItemType Directory -Path $dir
    $null = Assert-V2NoReparseChain $dir
    $null = Assert-V2AclExact -Acl (Get-V2Acl $dir) -Label $dir -IsContainer
    $record.Backups = @(Use-V2Env -Vars @{ TEMP = $dir; TMP = $dir } -Body {
        foreach ($spec in @(@('integrity_v2.db','3'), @('v2_auth.db','1'))) {
            $dest = Join-Path $dir $spec[0]
            $result = Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('backup', (Join-Path $data $spec[0]), $dest, '--expect-version', $spec[1])
            $sha = (Get-FileHash -LiteralPath $dest).Hash.ToLowerInvariant()
            if ($result -notmatch "restore-test=ok sha256=$sha$") { throw 'Backup restoration check incomplete' }
            if ($spec[1] -eq '1') {
                $null = Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('auth-schema', $dest)
            }
            [pscustomobject]@{ Name = $spec[0]; Version = [int]$spec[1]; SHA256 = $sha; RestoreCheck = 'PASS'; ServerPath = $dest }
        }
    })
} catch {
    $backupError = $_.Exception.GetType().Name
}
$null = Assert-V2DataReady -DataDir $data
$null = Assert-V2NoProcesses -DataDir $data -Known $known
Start-VerifiedServices
$after = @{}
$record.After = @(Capture-Service $backendName $after; Capture-Service $caddyName $after)
$record.PostRestartHTTPS = [bool](Assert-V2PinnedHttps @pin -Path '/api/health' -Expected 200)
$record.EndedUtc = [DateTime]::UtcNow.ToString('o')
$record.State = if ($backupError) { 'RepairBackupVerification' } else {'PASS'}
$record.BackupError = $backupError
[pscustomobject]$record | ConvertTo-Json -Depth 6 -Compress
