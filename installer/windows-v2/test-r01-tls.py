"""Loopback TLS proof for the installer's pinned HTTPS request."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import shutil
import tempfile
import threading

sys.stdout.reconfigure(encoding='utf-8')

p = argparse.ArgumentParser()
p.add_argument('--ps', required=True)
p.add_argument('--pwsh', default=shutil.which('pwsh'))
args = p.parse_args()
kit = Path(__file__).resolve().parent
if not args.pwsh:
    print('R01.tls-valid NOT RUN PowerShell 7 fixture generator unavailable')
    print('R01.tls-hostname-mismatch NOT RUN PowerShell 7 fixture generator unavailable')
    print('R01.endpoint-unavailable-real NOT RUN PowerShell 7 fixture generator unavailable')
    raise SystemExit(0)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'local TLS fixture')
        self.wfile.flush()
        # Windows curl/Schannel requires a TLS close_notify from this fixture.
        self.connection.unwrap()

    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix='v2-r01-tls-') as d:
    cert, key = Path(d) / 'cert.pem', Path(d) / 'key.pem'
    generate = r'''
$rsa = [Security.Cryptography.RSA]::Create(2048)
$req = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=testhost.example.test', $rsa, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
$san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
$san.AddDnsName('testhost.example.test')
$req.CertificateExtensions.Add($san.Build())
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $false, 0, $true))
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment -bor [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign), $true))
$eku = [Security.Cryptography.OidCollection]::new()
$null = $eku.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1'))
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($eku, $false))
$cert = $req.CreateSelfSigned([datetimeoffset]::UtcNow.AddMinutes(-5), [datetimeoffset]::UtcNow.AddHours(1))
[IO.File]::WriteAllText('__CERT__', $cert.ExportCertificatePem())
[IO.File]::WriteAllText('__KEY__', $rsa.ExportPkcs8PrivateKeyPem())
'''
    generate = generate.replace('__CERT__', str(cert)).replace('__KEY__', str(key))
    made = subprocess.run([args.pwsh, '-NoProfile', '-NonInteractive', '-Command', generate], capture_output=True, text=True)
    if made.returncode:
        raise SystemExit(f'fixture certificate generation failed: {made.stderr}')
    server = HTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def check(name: str, host: str, endpoint: int, expected: str) -> str:
        script = f'''
. '{kit / 'V2-install-common.ps1'}'
$env:COMPUTERNAME='TESTHOST'
function Get-V2TargetDns([string]$HostName) {{ @('127.0.0.1') }}
function Get-V2TargetLocalIps {{ @('127.0.0.1') }}
try {{
  Assert-V2PinnedHttps -HostName '{host}' -Addresses @('127.0.0.1') -Path '/' -Port {endpoint} -CaFile '{cert}' -Expected 200 -TestHost
  exit 0
}} catch {{ Write-Output $_.Exception.Message; exit 1 }}
'''
        run = subprocess.run([args.ps, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25)
        output = run.stdout + run.stderr
        if expected == 'valid':
            status = 'PASS' if run.returncode == 0 and 'pinned to 127.0.0.1' in output and '200' in output else 'FAIL'
        elif expected == 'hostname':
            status = 'PASS' if run.returncode != 0 and ('код 60' in output or 'curl: (60)' in output) else 'FAIL'
        else:
            status = 'PASS' if run.returncode != 0 and ('код 7' in output or 'curl: (7)' in output) else 'FAIL'
        if expected != 'unavailable' and 'SEC_E_NO_CREDENTIALS' in output:
            status = 'NOT RUN'
        print(name, status, f'exit={run.returncode}', output.strip()[-220:])
        return status

    good = check('R01.tls-valid', 'testhost.example.test', port, 'valid')
    bad_name = check('R01.tls-hostname-mismatch', 'testhost.other.test', port, 'hostname')
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        unavailable = s.getsockname()[1]
    bad_endpoint = check('R01.endpoint-unavailable-real', 'testhost.example.test', unavailable, 'unavailable')
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    if 'FAIL' in (good, bad_name, bad_endpoint):
        raise SystemExit(1)
