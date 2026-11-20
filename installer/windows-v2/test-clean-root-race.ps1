# Synthetic creator faults only; no SCM, ACL or production path is touched.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
public static class V2AtomicRoot {
  public static string Mode;
  public static void Create(string path, byte[] descriptor) {
    if (Mode == "race") { Directory.CreateDirectory(path); throw new Win32Exception(183, "foreign actor created root"); }
    if (Mode == "fail-before") throw new Win32Exception(5, "create denied");
    if (Directory.Exists(path)) throw new Win32Exception(183, "root exists");
    Directory.CreateDirectory(path);
  }
}
'@
. (Join-Path $PSScriptRoot 'V2-install-common.ps1')
function Assert-V2Ancestors { }
function Assert-V2Root { if ($script:FailVerify) { throw 'root verify failed after create' } }
$base = Join-Path $env:TEMP ('v2-root-race-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $base
$results = New-Object System.Collections.Generic.List[string]
function Record([string]$id, [bool]$ok) { $results.Add("$id $(if ($ok) { 'PASS' } else { 'FAIL' }) synthetic ownership transition") }
try {
  $V2Root = Join-Path $base 'foreign'; $owned = $false; $token = $null; $failClosedCalls = 0
  $foreignService = [pscustomobject]@{ State = 'Running'; StartMode = 'Manual' }; [V2AtomicRoot]::Mode = 'race'
  try { New-V2Root -OnCreated { param($t) $script:owned = $true; $script:token = $t } } catch { }
  if ($owned) { $failClosedCalls++; $foreignService.State = 'Stopped'; $foreignService.StartMode = 'Disabled'; [IO.File]::WriteAllText((Join-Path $V2Root 'CLEAN-INSTALL-FAILED.txt'),'wrong') }
  Record 'R00.race' ((Test-Path $V2Root) -and -not $owned -and -not $token -and $failClosedCalls -eq 0 -and $foreignService.State -eq 'Running' -and $foreignService.StartMode -eq 'Manual' -and -not (Test-Path (Join-Path $V2Root 'CLEAN-INSTALL-FAILED.txt')))
  $V2Root = Join-Path $base 'failed'; $owned = $false; $token = $null; [V2AtomicRoot]::Mode = 'fail-before'
  try { New-V2Root -OnCreated { param($t) $script:owned = $true; $script:token = $t } } catch { }
  Record 'R00.create-fail' (-not (Test-Path $V2Root) -and -not $owned -and -not $token)
  $V2Root = Join-Path $base 'mine'; $owned = $false; $token = $null; $script:FailVerify = $true; [V2AtomicRoot]::Mode = 'success'
  try { New-V2Root -OnCreated { param($t) $script:owned = $true; $script:token = $t } } catch { }
  Record 'R00.post-create-fail' ((Test-Path $V2Root) -and $owned -and $token -match '^[0-9a-f]{32}$')
  $script:FailVerify = $false
  $V2Root = Join-Path $base 'mine'; $owned = $false; $token = $null
  try { New-V2Root -OnCreated { param($t) $script:owned = $true; $script:token = $t } } catch { }
  Record 'R00.existing' ((Test-Path $V2Root) -and -not $owned -and -not $token)
  $results
  if (@($results | Where-Object { $_ -match '\sFAIL\s' }).Count) { exit 1 }
  exit 0
} finally {
  $safe = [IO.Path]::GetFullPath($base)
  if ($safe -notlike "$env:TEMP\v2-root-race-*") { throw 'unsafe test cleanup path' }
  Remove-Item -LiteralPath $safe -Recurse -Force
}
