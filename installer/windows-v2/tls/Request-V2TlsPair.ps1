# Use only after approval to request this node's TLS pair from Tailscale.
param([Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$DecisionRef)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$hostname = 'desktop-jtgc2sg.taild5c033.ts.net'
$tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
$python = 'C:\Program Files\Python313\python.exe'
if ($env:COMPUTERNAME -ine 'DESKTOP-JTGC2SG') { throw 'Wrong host' }
$identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'An elevated operator is required' }
$srv = Get-Item -LiteralPath 'C:\srv' -Force
if ($srv.FullName -ine 'C:\srv' -or ($srv.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected recovery parent' }
$trusted = @('S-1-5-18','S-1-5-32-544')
$parentAcl = Get-Acl -LiteralPath $srv.FullName
if (-not $parentAcl.AreAccessRulesProtected -or $trusted -notcontains $parentAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -or
    @($parentAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object {
        $_.AccessControlType -eq 'Allow' -and $trusted -notcontains $_.IdentityReference.Value
    }).Count) { throw 'Unexpected C:\srv ACL' }
$signature = Get-AuthenticodeSignature -LiteralPath $tailscale
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|, )O=Tailscale Inc\.(,|$)') { throw 'Unexpected Tailscale CLI signature' }
$state = & $tailscale status --json | ConvertFrom-Json
if ($LASTEXITCODE -or $state.BackendState -ne 'Running' -or $state.CertDomains -notcontains $hostname -or $state.Self.DNSName.TrimEnd('.') -ine $hostname) {
    throw 'The local Tailscale node does not advertise this certificate domain'
}
$name = 'V2-tls-staging-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$folder = Join-Path $srv.FullName $name
if (Test-Path -LiteralPath $folder) { throw 'Certificate staging folder already exists' }
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
[IO.Directory]::CreateDirectory($folder, $acl) | Out-Null
$item = Get-Item -LiteralPath $folder -Force
if ($item.FullName -ine $folder -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected TLS staging path' }
$checkedAcl = Get-Acl -LiteralPath $folder
$rules = @($checkedAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if (-not $checkedAcl.AreAccessRulesProtected -or $rules.Count -ne 2 -or @($rules | Where-Object {
    $_.IdentityReference.Value -notin 'S-1-5-18','S-1-5-32-544' -or
    $_.AccessControlType -ne 'Allow' -or $_.FileSystemRights -ne 'FullControl'
}).Count) { throw 'Certificate staging ACL mismatch' }
$cert = Join-Path $folder 'site.crt'
$key = Join-Path $folder 'site.key'
& $tailscale cert "--cert-file=$cert" "--key-file=$key" $hostname | Out-Null
if ($LASTEXITCODE) { throw "Tailscale certificate request failed with exit $LASTEXITCODE" }
foreach ($path in $cert,$key) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or -not $item.Length -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Certificate or key path is invalid'
    }
    $fileAcl = Get-Acl -LiteralPath $path
    if ($trusted -notcontains $fileAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -and
        $fileAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $identity.Identity.User.Value) { throw 'Unexpected TLS file owner' }
    if (@($fileAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object {
        $_.AccessControlType -ne 'Allow' -or $trusted -notcontains $_.IdentityReference.Value
    }).Count) { throw 'Certificate or key ACL permits an unexpected SID' }
    $fileAcl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    Set-Acl -LiteralPath $path -AclObject $fileAcl
    $readBack = Get-Acl -LiteralPath $path
    $aces = @($readBack.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    if ($readBack.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544' -or $aces.Count -ne 2 -or
        @($aces | Where-Object {
            $_.IdentityReference.Value -notin $trusted -or $_.AccessControlType -ne 'Allow' -or $_.FileSystemRights -ne 'FullControl'
        }).Count -or @($aces.IdentityReference.Value | Sort-Object -Unique).Count -ne 2) { throw 'Certificate or key DACL read-back failed' }
}
$check = @'
import json
import os
import ssl
import sys

cert, key, host = sys.argv[1:]
for name in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'SSLKEYLOGFILE'):
    os.environ.pop(name, None)
server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
server_context.load_cert_chain(cert, key)
client_context = ssl.create_default_context()
client_context.hostname_checks_common_name = False
client_in, client_out, server_in, server_out = [ssl.MemoryBIO() for _ in range(4)]
client = client_context.wrap_bio(client_in, client_out, server_hostname=host)
server = server_context.wrap_bio(server_in, server_out, server_side=True)
for _ in range(12):
    completed = 0
    for endpoint, outgoing, incoming in ((client, client_out, server_in), (server, server_out, client_in)):
        try:
            endpoint.do_handshake()
            completed += 1
        except ssl.SSLWantReadError:
            pass
        if outgoing.pending:
            incoming.write(outgoing.read())
    if completed == 2:
        leaf = client.getpeercert()
        if ('DNS', host) not in leaf.get('subjectAltName', ()):
            raise RuntimeError('Exact DNS SAN absent')
        print(json.dumps({
            'dns': host,
            'issuer': ', '.join(f'{name}={value}' for rdn in leaf['issuer'] for name, value in rdn),
            'expiry': ssl.cert_time_to_seconds(leaf['notAfter']),
            'protocol': client.version(),
        }))
        break
else:
    raise RuntimeError('TLS handshake did not complete')
'@
$verifyPath = Join-Path $folder 'verify-public-tls-chain.py'
[IO.File]::WriteAllText($verifyPath,$check,[Text.UTF8Encoding]::new($false))
$public = @(& $python -I -B $verifyPath $cert $key $hostname)
if ($LASTEXITCODE) { throw 'Certificate, key, exact SAN or trusted TLS handshake verification failed' }
$leaf = $public | ConvertFrom-Json
[pscustomobject]@{
    DecisionRef = $DecisionRef
    Staging = $folder
    DNSName = $leaf.dns
    Issuer = $leaf.issuer
    ExpiryUtc = [DateTimeOffset]::FromUnixTimeSeconds($leaf.expiry).ToString('o')
    TlsProtocol = $leaf.protocol
    CertificateSHA256 = (Get-FileHash -LiteralPath $cert).Hash
    KeyMatches = $true
    TrustedChainAndSni = $true
} | ConvertTo-Json -Compress
