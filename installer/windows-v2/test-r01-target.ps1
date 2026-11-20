param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'V2-install-common.ps1')
$results = New-Object System.Collections.Generic.List[string]
function Add-Case([string]$name, [bool]$ok) { $results.Add("$name $(if ($ok) { 'PASS' } else { 'FAIL' })  synthetic") }
function Stopped([scriptblock]$body) { try { $null = & $body; $false } catch { $_.Exception.Message -like 'STOP:*' } }
$env:COMPUTERNAME = 'TESTHOST'
$script:Answers = @('10.8.0.9')
$script:Calls = 0
$script:NativeCalls = New-Object System.Collections.Generic.List[object]
function Get-V2TargetDns([string]$HostName) { $script:Calls++; $script:Answers }
function Get-V2TargetLocalIps { @('10.8.0.9') }
function Invoke-V2Native { param($Exe, $ArgList, $What) $script:NativeCalls.Add(@($ArgList)); '200' }
$hostName = 'testhost.example.test'
$approved = @('10.8.0.9')

$script:Answers = @('10.8.0.9', '100.64.0.10')
Add-Case 'R01.mixed-production-dns' (Stopped { Assert-V2TargetIdentity -HostName $hostName -Addresses $approved -TestHost })
$script:Answers = @('10.8.0.9', '10.8.0.10')
Add-Case 'R01.extra-dns' (Stopped { Assert-V2TargetIdentity -HostName $hostName -Addresses $approved -TestHost })
$script:Answers = @('10.8.0.10')
Add-Case 'R01.missing-dns' (Stopped { Assert-V2TargetIdentity -HostName $hostName -Addresses $approved -TestHost })
$script:Answers = @('10.8.0.9')
Add-Case 'R01.exact-dns' ((Assert-V2TargetIdentity -HostName $hostName -Addresses $approved -TestHost) -like 'PASS*')

$script:Answers = @('10.8.0.9', 'fd7a:115c:a1e0::10')
Add-Case 'R01.mixed-production-ipv6-dns' (Stopped { Assert-V2TargetIdentity -HostName $hostName -Addresses $approved -TestHost })
$script:Answers = @('10.8.0.9')
Add-Case 'R01.production-ipv6-testhost-reject' (Stopped { Assert-V2TargetIdentity -HostName $hostName -Addresses @('fd7a:115c:a1e0::10') -TestHost })

$env:COMPUTERNAME = 'V2-HOST'
$script:Answers = @('100.64.0.10')
function Get-V2TargetLocalIps { @('100.64.0.10') }
Add-Case 'R01.production-ipv4-only-dns' (-not (Stopped { Assert-V2TargetIdentity -HostName 'v2-host.example.ts.net' -Addresses @('100.64.0.10') }))
$env:COMPUTERNAME = 'TESTHOST'
function Get-V2TargetLocalIps { @('10.8.0.9') }

$script:Answers = @('10.8.0.9')
$null = Assert-V2TargetIdentity -HostName $hostName -Addresses $approved -TestHost
$script:Answers = @('10.8.0.9', '100.64.0.10')
$script:NativeCalls.Clear()
Add-Case 'R01.rebinding' ((Stopped { Assert-V2PinnedHttps -HostName $hostName -Addresses $approved -Path '/api/health' -Expected 200 -TestHost }) -and $script:NativeCalls.Count -eq 0)

$script:Answers = @('10.8.0.9')
$script:NativeCalls.Clear()
$ok = (Assert-V2PinnedHttps -HostName $hostName -Addresses $approved -Path '/api/health' -Expected 200 -TestHost) -like 'PASS*'
$a = @($script:NativeCalls[0])
Add-Case 'R01.pinned-endpoint' ($ok -and $script:NativeCalls.Count -eq 1 -and $a.Contains('--resolve') -and $a.Contains('testhost.example.test:443:10.8.0.9') -and $a.Contains('--noproxy') -and $a.Contains('*') -and $a.Contains('https://testhost.example.test/api/health') -and -not $a.Contains('-k') -and -not $a.Contains('--insecure'))

$script:NativeCalls.Clear()
function Invoke-V2Native { param($Exe, $ArgList, $What) throw 'curl connection failed' }
Add-Case 'R01.endpoint-unavailable' (Stopped { Assert-V2PinnedHttps -HostName $hostName -Addresses $approved -Path '/api/health' -Expected 200 -TestHost })

$results
if (@($results | Where-Object { $_ -match ' FAIL ' }).Count) { exit 1 }
exit 0
