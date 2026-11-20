# Restart-V2Tlsfix5Verified.ps1 — доведений перезапуск Caddy і backend V2 із перевіреними копіями БД між зупинкою й стартом.
# Поточний реліз: служби Automatic (Delayed Start) або Manual; версії БД — з самих файлів (v2_db_tool user-version, лише записи
# SCHEMA_SPECS) і строга схема цих версій; служба integrity-v2-lm (якщо встановлена) НЕ зупиняється, але має працювати до і після.
# common і v2_db_tool — з каталогу інсталятора цього релізу (..\); -CommonSha256 / -DbToolSha256 — необов'язкове закріплення.
[CmdletBinding()]
param([string] $CommonSha256, [string] $DbToolSha256, [string] $Python = 'C:\Program Files\Python313\python.exe')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:COMPUTERNAME -ne 'V2-HOST') { throw 'Wrong host' }
$kit = Split-Path -Parent $PSScriptRoot
$common = Join-Path $kit 'V2-install-common.ps1'
$dbTool = Join-Path $kit 'v2_db_tool.py'
if ($CommonSha256 -and (Get-FileHash -LiteralPath $common).Hash -ne $CommonSha256) { throw 'Common script hash mismatch' }
if ($DbToolSha256 -and (Get-FileHash -LiteralPath $dbTool).Hash -ne $DbToolSha256) { throw 'Database tool hash mismatch' }
. $common
$null = Assert-V2Root
$data = Join-Path $V2Root 'data'
$null = Assert-V2DataReady -DataDir $data
$backendName = 'integrity-v2-backend'
$caddyName = 'integrity-v2-caddy'
$address = '100.64.0.10'
$hostName = 'v2-host.example.ts.net'
$pin = @{ HostName = $hostName; Addresses = @($address) }
$record = [ordered]@{ BeganUtc = [DateTime]::UtcNow.ToString('o'); Before = @(); Backups = @(); After = @(); State = 'InProgress' }
$trees = @{}
$py = $Python

function Capture-Service([string]$Name,$Store) {
    $null = Assert-V2Service -Name $Name -State Running -StartModes Manual, Auto
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
    [pscustomobject]@{ Name = $Name; PID = $service.ProcessId; Sid = $expectedSid; StartMode = $service.StartMode; Members = @($tree | Select-Object -ExpandProperty Pid) }
}

function Stop-VerifiedService([string]$Name) {
    $null = Assert-V2Service -Name $Name -State Running -StartModes Manual, Auto
    $service = Get-V2Service $Name
    $known = $trees[$Name]
    if ($service.ProcessId -ne $known[0].Pid -or (Test-V2HandleExited $known[0].Handle)) { throw "Wrapper PID changed: $Name" }
    $controller = Get-Service -Name $Name
    if (@($controller.DependentServices | Where-Object Status -ne 'Stopped').Count) { throw "Active service dependency: $Name" }
    $controller.Stop()
    $controller.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    $null = Assert-V2Service -Name $Name -State Stopped -StartModes Manual, Auto
    if ((Get-V2Service $Name).ProcessId) { throw "SCM still reports a PID: $Name" }
    $null = Assert-V2TreeExited -Tree $known
    if (@(Get-V2LateDescendants -Tree $known).Count -or @(Get-V2Listeners -Ports @($V2Services[$Name].Port)).Count) {
        throw "Service left a child or listener: $Name"
    }
}

# Invoke-V2ServiceStart зі стандартним PreCheck вимагає Manual; тут — та сама перевірка ідентичності для Manual/Auto + готовність даних
$preCheck = { param($n) $null = Assert-V2Service -Name $n -State Stopped -StartModes Manual, Auto; if ($n -eq $backendName) { $null = Assert-V2DataReady -DataDir $data } }
function Start-VerifiedServices {
    if ((Get-V2Service $backendName).State -eq 'Stopped') {
        $null = Invoke-V2ServiceStart -Name $backendName -PreCheck $preCheck -Checks {
            Assert-V2ServiceRunning -Name $backendName -Addresses '127.0.0.1'
            Wait-V2Http -Url 'http://127.0.0.1:8100/api/health' -Expected 200
        }
    }
    if ((Get-V2Service $backendName).State -ne 'Running') { throw 'Backend did not start cleanly' }
    if ((Get-V2Service $caddyName).State -eq 'Stopped') {
        $null = Invoke-V2ServiceStart -Name $caddyName -PreCheck $preCheck -Checks {
            Assert-V2ServiceRunning -Name $caddyName -Addresses $address
            Assert-V2PinnedHttps @pin -Path '/api/health' -Expected 200
        }
    }
    if ((Get-V2Service $caddyName).State -ne 'Running') { throw 'Caddy did not start cleanly' }
}

# Служба LM (необов'язкова): перевіряється, але не зупиняється; її дерево виключається з евристик «процесів V2»
$lmBefore = Get-V2LmServiceEvidence
$lmPids = @(if ($lmBefore) { $lmBefore.Pids })
$record.LmBefore = if ($lmBefore) { [pscustomobject]@{ WrapperPid = $lmBefore.WrapperPid; StartMode = $lmBefore.StartMode; Members = $lmBefore.Pids } } else { 'NotInstalled' }
$record.Before = @(Capture-Service $backendName $trees; Capture-Service $caddyName $trees)
$known = @($trees[$backendName].ToArray() + $trees[$caddyName].ToArray())
$record.PreRestartHTTPS = [bool](Assert-V2PinnedHttps @pin -Path '/api/health' -Expected 200)
$backupError = $null
Stop-VerifiedService $caddyName
Stop-VerifiedService $backendName
$null = Assert-V2NoProcesses -DataDir $data -Known $known -IgnorePids $lmPids
$record.FullStop = 'PASS: SCM, both known trees, late descendants, sockets and SQLite handles (LM untouched)'
try {
    $stamp = Get-Date -Format yyyyMMdd-HHmmss
    $dir = Join-Path $V2Root "backups\restart-verified-$stamp"
    $null = New-Item -ItemType Directory -Path $dir
    $null = Assert-V2NoReparseChain $dir
    $null = Assert-V2AclExact -Acl (Get-V2Acl $dir) -Label $dir -IsContainer
    $record.Backups = @(Use-V2Env -Vars @{ TEMP = $dir; TMP = $dir } -Body {
        foreach ($spec in @(@('integrity_v2.db', 'integrity'), @('v2_auth.db', 'auth'))) {
            $live = Join-Path $data $spec[0]
            $version = Get-V2DbVersion -Py $py -DbTool $dbTool -Path $live -Kind $spec[1]
            $dest = Join-Path $dir $spec[0]
            $result = Invoke-V2DbTool -Py $py -DbTool $dbTool -ArgList @('backup', $live, $dest, '--expect-version', "$version", '--kind', $spec[1], '--strict')
            $sha = (Get-FileHash -LiteralPath $dest).Hash.ToLowerInvariant()
            if ($result -notmatch "restore-test=ok sha256=$sha$") { throw 'Backup restoration check incomplete' }
            $strict = Assert-V2DbStrict -Py $py -DbTool $dbTool -Path $dest -Kind $spec[1]
            [pscustomobject]@{ Name = $spec[0]; Version = $version; SHA256 = $sha; RestoreCheck = 'PASS'; Schema = $strict.Schema; ServerPath = $dest }
        }
    })
} catch {
    $backupError = $_.Exception.GetType().Name
}
$null = Assert-V2DataReady -DataDir $data
$null = Assert-V2NoProcesses -DataDir $data -Known $known -IgnorePids $lmPids
Start-VerifiedServices
$after = @{}
$record.After = @(Capture-Service $backendName $after; Capture-Service $caddyName $after)
$record.PostRestartHTTPS = [bool](Assert-V2PinnedHttps @pin -Path '/api/health' -Expected 200)
$lmAfter = Get-V2LmServiceEvidence
if ([bool]$lmBefore -ne [bool]$lmAfter -or ($lmBefore -and $lmAfter.WrapperPid -ne $lmBefore.WrapperPid)) { throw 'LM service changed during restart (must not be touched)' }
$record.LmAfter = if ($lmAfter) { 'Running, same wrapper PID' } else { 'NotInstalled' }
$record.EndedUtc = [DateTime]::UtcNow.ToString('o')
$record.State = if ($backupError) { 'RepairBackupVerification' } else {'PASS'}
$record.BackupError = $backupError
[pscustomobject]$record | ConvertTo-Json -Depth 6 -Compress
