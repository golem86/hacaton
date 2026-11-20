[CmdletBinding(DefaultParameterSetName='Renew')]
param(
    [Parameter(ParameterSetName='Renew')][string]$StagingDirectory,
    [Parameter(ParameterSetName='Renew')][ValidateRange(7,45)][int]$RenewBeforeDays = 30,
    [Parameter(ParameterSetName='Renew')][switch]$Force,
    [Parameter(Mandatory,ParameterSetName='Fixture')][switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$hostName = 'v2-host.example.ts.net'
$address = '100.64.0.10'
$serviceName = 'integrity-v2-caddy'
$backendName = 'integrity-v2-backend'
$root = 'C:\srv\integrity-v2'
$work = 'C:\srv\V2-tls-maintenance'
$live = Join-Path $root 'caddy\tls'
$wrapper = Join-Path $root 'services\caddy\integrity-v2-caddy.exe'
$caddy = Join-Path $root 'caddy\bin\caddy.exe'
$config = Join-Path $root 'caddy\Caddyfile'
$python = 'C:\Program Files\Python313\python.exe'
$tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
$admin = 'S-1-5-32-544'
$system = 'S-1-5-18'

function Assert-TlsPath {
    param([string]$Path,[string]$Reader,[switch]$File,[switch]$Inheriting)
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.FullName -ine $Path -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        [bool]$item.PSIsContainer -eq [bool]$File) { throw 'Unexpected TLS path, variant, or reparse point' }
    $acl = Get-Acl -LiteralPath $Path
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    $operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($owner -notin $admin,$system,$operatorSid -or (-not $Inheriting -and -not $acl.AreAccessRulesProtected)) {
        throw 'Unexpected TLS path owner or inheritance'
    }
    $seen = @{}
    foreach ($ace in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        $sid = $ace.IdentityReference.Value
        if ($seen.ContainsKey($sid) -or $ace.AccessControlType -ne 'Allow' -or
            ($ace.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)) { throw 'Unexpected TLS ACE' }
        $seen[$sid] = $true
        $rights = [int]$ace.FileSystemRights
        if ($sid -in $admin,$system) {
            if ($rights -ne [int][Security.AccessControl.FileSystemRights]::FullControl) { throw 'Incomplete trusted control' }
        } elseif (-not $Reader -or $sid -ne $Reader -or $rights -notin 0x120089,0x1200A9) {
            throw 'Unexpected TLS path principal or permission'
        }
    }
    if (-not $seen[$admin] -or -not $seen[$system] -or
        ($Reader -and -not $seen[$Reader])) { throw 'Required TLS ACL missing' }
}

function New-TlsDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw 'TLS staging directory already exists' }
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
    [IO.Directory]::CreateDirectory($Path,$acl) | Out-Null
    Assert-TlsPath $Path
}

function Set-TlsReader {
    param([string]$Path,[string]$Reader,[switch]$File,[switch]$Revoke)
    $info = Get-Item -LiteralPath $Path -Force
    if ($info.FullName -ine $Path -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe TLS ACL path' }
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new($admin))
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($rule in @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))) {
        $acl.RemoveAccessRuleSpecific($rule)
    }
    $inheritance = if ($File) { 'None' } else { 'ObjectInherit,ContainerInherit' }
    foreach ($sid in $system,$admin) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($sid),'FullControl',$inheritance,'None','Allow'))
    }
    if (-not $Revoke) {
        $rights = if ($File) { 'Read' } else { 'ReadAndExecute' }
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($Reader),$rights,'None','None','Allow'))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
    $expected = if (-not $Revoke) { $Reader }
    Assert-TlsPath $Path -Reader $expected -File:$File
}

function Invoke-TlsRotation {
    param([string]$Active,[string]$Incoming,[string]$Previous,[string]$Failed,
          [scriptblock]$Stop,[scriptblock]$Start,[scriptblock]$VerifyNew,[scriptblock]$VerifyOld)
    $stopped = $false
    $saved = $false
    $promoted = $false
    try {
        & $Stop
        $stopped = $true
        [IO.Directory]::Move($Active,$Previous)
        $saved = $true
        [IO.Directory]::Move($Incoming,$Active)
        $promoted = $true
        & $Start
        & $VerifyNew
    } catch {
        if (-not $stopped) { throw 'Initial Caddy stop was not verified. No certificate files were moved.' }
        try {
            if ($promoted) {
                & $Stop
                [IO.Directory]::Move($Active,$Failed)
            }
            if ($saved) { [IO.Directory]::Move($Previous,$Active) }
            & $Start
            & $VerifyOld | Out-Null
        } catch {
            try { & $Stop } catch { }
            throw 'Renewal and rollback failed. Preserve the transaction directory and check Caddy state.'
        }
        throw 'Renewal failed. Previous pair restored and HTTPS verified.'
    }
}

if ($SelfTest) {
    $fixture = Join-Path ([IO.Path]::GetTempPath()) ('v2-tls-renew-fixture-' + [guid]::NewGuid().ToString('N'))
    foreach ($scenario in 'Promote','Rollback','MissingIncoming','StopFailure') {
        $dir = Join-Path $fixture $scenario
        $active = Join-Path $dir 'active'
        $incoming = Join-Path $dir 'incoming'
        $previous = Join-Path $dir 'previous'
        $failed = Join-Path $dir 'failed'
        $dirs = if ($scenario -eq 'MissingIncoming') { @($active) } else { @($active,$incoming) }
        foreach ($p in $dirs) {
            [IO.Directory]::CreateDirectory($p) | Out-Null
            foreach ($name in 'site.crt','site.key') { [IO.File]::WriteAllText((Join-Path $p $name),[IO.Path]::GetFileName($p)) }
        }
        $state = @{ Running=$true; Stops=0 }
        $stop = {
            if ($scenario -eq 'StopFailure') { throw 'Simulated stop failure' }
            $state.Stops++
            $state.Running=$false
        }
        $start = {$state.Running=$true}
        $verifyNew = {
            if ($scenario -eq 'Rollback') { throw 'Simulated HTTPS failure' }
            foreach ($name in 'site.crt','site.key') {
                if (-not $state.Running -or [IO.File]::ReadAllText((Join-Path $active $name)) -ne 'incoming') { throw 'Mixed or unserved fixture pair' }
            }
        }
        $verifyOld = {
            foreach ($name in 'site.crt','site.key') {
                if (-not $state.Running -or [IO.File]::ReadAllText((Join-Path $active $name)) -ne 'active') { throw 'Old fixture pair unavailable' }
            }
        }
        $failure = ''
        try { Invoke-TlsRotation $active $incoming $previous $failed $stop $start $verifyNew $verifyOld } catch { $failure = $_.Exception.Message }
        switch ($scenario) {
            'Promote' {
                if ($failure -or $state.Stops -ne 1 -or -not (Test-Path -LiteralPath $previous)) { throw 'Promotion fixture failed' }
                & $verifyNew
            }
            'Rollback' {
                if ($failure -notlike '*Previous pair restored*' -or $state.Stops -ne 2 -or -not (Test-Path -LiteralPath $failed)) {
                    throw 'Rollback fixture failed'
                }
                & $verifyOld
            }
            'MissingIncoming' {
                if ($failure -notlike '*Previous pair restored*' -or $state.Stops -ne 1 -or
                    (Test-Path -LiteralPath $previous) -or (Test-Path -LiteralPath $failed)) {
                    throw 'Failed promotion fixture did not restore the old pair'
                }
                & $verifyOld
            }
            'StopFailure' {
                if ($failure -notlike '*No certificate files were moved*' -or (Test-Path -LiteralPath $previous)) { throw 'Stop failure fixture moved files' }
                & $verifyOld
            }
        }
        Write-Output "$scenario PASS"
    }
    Write-Output "Fixtures: $fixture"
    return
}

function Get-CaddyService {
    $s = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
    if (-not $s -or $s.StartName -ine "NT SERVICE\$serviceName" -or $s.PathName.Trim().Trim('"') -ine $wrapper) {
        throw 'Unexpected Caddy service identity'
    }
    $s
}

function Assert-BackendStable {
    $s = Get-CimInstance Win32_Service -Filter "Name='$backendName'"
    if (-not $s -or $s.State -ne 'Running' -or $s.ProcessId -ne $backend.ProcessId -or
        (Get-Process -Id $s.ProcessId).StartTime.ToUniversalTime().Ticks -ne $backendTicks) {
        throw 'V2 backend changed during Caddy renewal'
    }
}

function Get-HttpsListeners {
    @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 443)
}

function Assert-Listener($Service) {
    $listeners = @(Get-HttpsListeners)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne $address) { throw 'Unexpected HTTPS listeners' }
    $child = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if (-not $child -or $child.ExecutablePath -ine $caddy -or $child.ParentProcessId -ne $Service.ProcessId) {
        throw 'HTTPS socket is not owned by the expected Caddy child'
    }
    $owner = Invoke-CimMethod -InputObject $child -MethodName GetOwnerSid
    if ($owner.ReturnValue -ne 0 -or $owner.Sid -ne $serviceSid) { throw 'Caddy is not running as its virtual account' }
}

function Stop-CaddyOnly {
    $s = Get-CaddyService
    if ($s.State -notin 'Running','Stopped') { throw 'Caddy SCM still transitional' }
    if ($s.State -eq 'Running') {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($s.ProcessId)"
        if (-not $process -or $process.ExecutablePath -ine $wrapper) { throw 'Caddy wrapper process did not match' }
        $controller = Get-Service $serviceName
        if (@($controller.DependentServices | Where-Object Status -ne 'Stopped').Count) { throw 'Caddy has a running dependent' }
        $controller.Stop()
        $controller.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
    }
    $state = Get-CaddyService
    $left = @(Get-CimInstance Win32_Process -Filter "Name='caddy.exe' OR Name='integrity-v2-caddy.exe'" |
        Where-Object { -not $_.ExecutablePath -or $_.ExecutablePath -in $wrapper,$caddy })
    if ($state.State -ne 'Stopped' -or $state.ProcessId -or $left.Count -or @(Get-HttpsListeners).Count) {
        throw 'Caddy process and listener stop not proven'
    }
    Assert-BackendStable
}

function Start-CaddyOnly {
    Assert-BackendStable
    $s = Get-CaddyService
    if ($s.State -ne 'Stopped' -or $s.StartMode -notin 'Auto','Manual') { throw 'Unexpected state before Caddy restart' }
    $controller = Get-Service $serviceName
    $controller.Start()
    $controller.WaitForStatus('Running',[TimeSpan]::FromSeconds(30))
    for ($i = 0; $i -lt 15; $i++) {
        if (@(Get-HttpsListeners).Count) { return }
        if ((Get-CaddyService).State -ne 'Running') { throw 'Caddy stopped before opening HTTPS' }
        Start-Sleep -Seconds 1
    }
    throw 'Caddy did not open HTTPS after restart'
}

function Invoke-TlsProbe([string[]]$Arguments) {
    $lines = @(& $python -I -B $probePath @Arguments 2>$null)
    if ($LASTEXITCODE -or $lines.Count -ne 1) { throw 'Trusted TLS, exact SAN, certificate/key pair or HTTPS probe failed' }
    $lines[0] | ConvertFrom-Json
}

function Assert-ServedLeaf([string]$Expected) {
    $s = Get-CaddyService
    if ($s.State -ne 'Running') { throw 'Caddy is not running' }
    Assert-Listener $s
    $p = Invoke-TlsProbe @('live',$hostName,$address)
    if ($p.LeafSHA256 -cne $Expected -or $p.Status -ne 200) { throw 'Served HTTPS certificate or API status differs' }
    Assert-BackendStable
    $p
}

function Assert-TlsPair([string]$Dir,[string]$Reader) {
    Assert-TlsPath $Dir -Reader $Reader -Inheriting:([bool]$Reader)
    if ($Reader) {
        $names = @(Get-ChildItem -LiteralPath $Dir -Force | Sort-Object Name | Select-Object -ExpandProperty Name)
        if (($names -join ',') -cne 'site.crt,site.key') { throw 'Unexpected contents in the live TLS directory' }
    }
    foreach ($file in 'site.crt','site.key') {
        $path = Join-Path $Dir $file
        Assert-TlsPath $path -Reader $Reader -File -Inheriting
        $bytes = (Get-Item -LiteralPath $path).Length
        if ($bytes -lt 1 -or $bytes -gt 1048576) { throw 'Unexpected size of TLS input' }
    }
}

if ($env:COMPUTERNAME -ine 'V2-HOST') { throw 'Wrong host' }
$operator = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $operator.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Elevated operator required' }
Assert-TlsPath 'C:\srv'
foreach ($p in $root,(Join-Path $root 'caddy'),(Join-Path $root 'services')) { Assert-TlsPath $p -Inheriting }
$serviceSid = [Security.Principal.NTAccount]::new("NT SERVICE\$serviceName").Translate([Security.Principal.SecurityIdentifier]).Value
foreach ($p in (Join-Path $root 'caddy\bin'),(Join-Path $root 'services\caddy')) {
    Assert-TlsPath $p -Reader $serviceSid -Inheriting
}
$dns = @([Net.Dns]::GetHostAddresses($hostName) | ForEach-Object IPAddressToString)
$local = @(Get-NetIPAddress -IPAddress $address)
if ($dns.Count -ne 1 -or $dns[0] -ne $address -or $local.Count -ne 1 -or
    $local[0].AddressState -ne 'Preferred' -or $local[0].InterfaceAlias -ne 'Tailscale') {
    throw 'Expected private name and Tailscale address not confirmed'
}
foreach ($expected in @(
    @{ Path=$wrapper; SHA='05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da' },
    @{ Path=$caddy; SHA='2622e239c79df700b0eb92cbd950d1edee365e155a7859f358f0e55f002df591' }
)) {
    if ((Get-FileHash -LiteralPath $expected.Path).Hash -ine $expected.SHA) { throw 'Caddy or WinSW binary changed' }
}
$xml = [xml][IO.File]::ReadAllText([IO.Path]::ChangeExtension($wrapper,'xml'))
if ($xml.service.id -cne $serviceName -or $xml.service.executable -ine $caddy -or
    $xml.service.workingdirectory -ine (Join-Path $root 'caddy\bin') -or
    $xml.service.arguments.Trim() -ine "run --config $config --adapter caddyfile") { throw 'Unexpected WinSW configuration' }
Assert-TlsPath $config -Reader $serviceSid -File -Inheriting
$cfg = [IO.File]::ReadAllText($config)
$crtPath = ($live -replace '\\','/') + '/site.crt'
$keyPath = ($live -replace '\\','/') + '/site.key'
$directive = "(?m)^\s*tls\s+$([regex]::Escape($crtPath))\s+$([regex]::Escape($keyPath))\s*$"
if ([regex]::Matches($cfg,$directive).Count -ne 1) { throw 'Caddy is not using the expected TLS files' }
$markers = @(Get-ChildItem -LiteralPath (Join-Path $root 'data') -File)
if (@($markers | Where-Object Name -like 'CLEAN-INIT-OK-*').Count -ne 1 -or
    @($markers | Where-Object Name -match '^CLEAN-INIT-(FAILED|REVOKED)').Count) { throw 'V2 database activation has not passed' }
$backend = Get-CimInstance Win32_Service -Filter "Name='$backendName'"
if (-not $backend -or $backend.State -ne 'Running' -or $backend.StartName -ine "NT SERVICE\$backendName" -or -not $backend.ProcessId) {
    throw 'V2 backend must already run'
}
$backendTicks = (Get-Process -Id $backend.ProcessId).StartTime.ToUniversalTime().Ticks
Assert-TlsPair $live $serviceSid
if (-not (Test-Path -LiteralPath $work)) { New-TlsDirectory $work }
Assert-TlsPath $work
$lockPath = Join-Path $work 'renew.lock'
if (Test-Path -LiteralPath $lockPath) { Assert-TlsPath $lockPath -File -Inheriting }
$lock = [IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$tx = $null
try {
    $tx = Join-Path $work ('rotation-' + (Get-Date -Format yyyyMMdd-HHmmss) + '-' + [guid]::NewGuid().ToString('N'))
    New-TlsDirectory $tx
    $probePath = Join-Path $tx 'probe.py'
    $probe = @'
import hashlib
import http.client
import json
import os
import socket
import ssl
import sys

os.environ.pop('SSL_CERT_FILE', None)
os.environ.pop('SSL_CERT_DIR', None)
trust = ssl.create_default_context()
trust.hostname_checks_common_name = False
trust.minimum_version = ssl.TLSVersion.TLSv1_2

def evidence(tls, host):
    leaf = tls.getpeercert()
    if ('DNS', host) not in leaf.get('subjectAltName', ()):
        raise ValueError('Exact certificate SAN is absent')
    return {'LeafSHA256': hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest(),
            'Expiry': ssl.cert_time_to_seconds(leaf['notAfter'])}

def pair(host, cert, key):
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    ci, co, si, so = (ssl.MemoryBIO() for _ in range(4))
    client = trust.wrap_bio(ci, co, server_hostname=host)
    server = server_context.wrap_bio(si, so, server_side=True)
    done = [False, False]
    for _ in range(20):
        for n, (peer, outgoing, other_input) in enumerate(((client, co, si), (server, so, ci))):
            if not done[n]:
                try:
                    peer.do_handshake()
                    done[n] = True
                except ssl.SSLWantReadError:
                    pass
            if outgoing.pending:
                other_input.write(outgoing.read())
        if all(done):
            return evidence(client, host)
    raise RuntimeError('TLS fixture or pair negotiation did not complete')

def https(host, address):
    with socket.create_connection((address, 443), timeout=10) as raw:
        with trust.wrap_socket(raw, server_hostname=host) as tls:
            info = evidence(tls, host)
            tls.sendall(f'GET /api/health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode('ascii'))
            with http.client.HTTPResponse(tls) as response:
                response.begin()
                info['Status'] = response.status
    return info

mode, host, *paths = sys.argv[1:]
print(json.dumps({'pair': pair, 'live': https}[mode](host, *paths)))
'@
    [IO.File]::WriteAllText($probePath,$probe,[Text.UTF8Encoding]::new($false))
    $old = Invoke-TlsProbe @('pair',$hostName,(Join-Path $live 'site.crt'),(Join-Path $live 'site.key'))
    $null = Assert-ServedLeaf $old.LeafSHA256
    $deadline = [DateTimeOffset]::UtcNow.AddDays($RenewBeforeDays)
    if (-not $Force -and [DateTimeOffset]::FromUnixTimeSeconds($old.Expiry) -gt $deadline) {
        $result = [pscustomobject]@{
            Status='NotDue'
            ExpiryUtc=[DateTimeOffset]::FromUnixTimeSeconds($old.Expiry).UtcDateTime.ToString('o')
        } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText((Join-Path $tx 'result.json'),$result)
        $result
        return
    }
    $incoming = Join-Path $tx 'incoming'
    $previous = Join-Path $tx 'previous'
    $failed = Join-Path $tx 'failed'
    New-TlsDirectory $incoming
    $newCert = Join-Path $incoming 'site.crt'
    $newKey = Join-Path $incoming 'site.key'
    if ($StagingDirectory) {
        if ($StagingDirectory -inotmatch '^C:\\srv\\V2-tls-staging-[0-9]{8}-[0-9]{6}$') { throw 'Unexpected TLS staging directory' }
        Assert-TlsPair $StagingDirectory
        [IO.File]::Copy((Join-Path $StagingDirectory 'site.crt'),$newCert,$false)
        [IO.File]::Copy((Join-Path $StagingDirectory 'site.key'),$newKey,$false)
    } else {
        $signature = Get-AuthenticodeSignature -LiteralPath $tailscale
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|, )O=Tailscale Inc\.(,|$)') {
            throw 'Unexpected Tailscale signature'
        }
        $state = & $tailscale status --json | ConvertFrom-Json
        if ($LASTEXITCODE -or $state.BackendState -ne 'Running' -or $state.CertDomains -notcontains $hostName -or
            $state.Self.DNSName.TrimEnd('.') -ine $hostName -or $state.Self.TailscaleIPs -notcontains $address) {
            throw 'Wrong Tailscale domain or node address'
        }
        $minimum = 24 * ($RenewBeforeDays + 2)
        & $tailscale cert "--min-validity=$($minimum)h" "--cert-file=$newCert" "--key-file=$newKey" $hostName *> $null
        if ($LASTEXITCODE) { throw "Certificate renewal failed with exit $LASTEXITCODE" }
    }
    Assert-TlsPair $incoming
    $replacement = Invoke-TlsProbe @('pair',$hostName,$newCert,$newKey)
    $expiry = [DateTimeOffset]::FromUnixTimeSeconds($replacement.Expiry)
    if ($replacement.LeafSHA256 -ceq $old.LeafSHA256 -or $replacement.Expiry -le $old.Expiry -or $expiry -le $deadline) {
        throw 'Replacement certificate is not newer with sufficient validity'
    }
    foreach ($p in $newCert,$newKey) { Set-TlsReader $p -Reader $serviceSid -File }
    Set-TlsReader $incoming -Reader $serviceSid
    try {
        $rotation = @{
            Active=$live; Incoming=$incoming; Previous=$previous; Failed=$failed
            Stop={Stop-CaddyOnly}; Start={Start-CaddyOnly}
            VerifyNew={Assert-TlsPair $live $serviceSid; Assert-ServedLeaf $replacement.LeafSHA256}
            VerifyOld={Assert-TlsPair $live $serviceSid; Assert-ServedLeaf $old.LeafSHA256}
        }
        $served = Invoke-TlsRotation @rotation
    } finally {
        foreach ($archive in $incoming,$previous,$failed) {
            if (Test-Path -LiteralPath $archive) {
                foreach ($name in 'site.crt','site.key') {
                    Set-TlsReader (Join-Path $archive $name) -Reader $serviceSid -File -Revoke
                }
                Set-TlsReader $archive -Reader $serviceSid -Revoke
            }
        }
    }
    $result = [pscustomobject]@{
        Status='Renewed'; OldLeafSHA256=$old.LeafSHA256; NewLeafSHA256=$served.LeafSHA256
        ExpiryUtc=$expiry.UtcDateTime.ToString('o'); HTTPSStatus=$served.Status; Backup=$previous
    } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText((Join-Path $tx 'result.json'),$result)
    $result
} catch {
    if ($tx -and (Test-Path -LiteralPath $tx -PathType Container)) {
        $failure = [pscustomobject]@{Status='Failed';Reason=$_.Exception.Message} | ConvertTo-Json -Compress
        [IO.File]::WriteAllText((Join-Path $tx 'result.json'),$failure)
    }
    throw
} finally {
    $lock.Dispose()
}
