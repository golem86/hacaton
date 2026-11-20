. (Join-Path $PSScriptRoot 'V2-install-common.ps1')
$V2Services['integrity-v2-backend'].Exe = 'C:\synthetic\integrity-v2-backend.exe'
$script:fakeSvc = $null
$script:phase = ''
$script:owned = New-Object 'System.Collections.Generic.HashSet[string]'
function Get-V2Service([string]$Name) { return $script:fakeSvc }
function Assert-V2Winsw { return 'PASS synthetic' }
function Invoke-V2Native {
  if ($script:phase -eq 'created-readback-failed') {
    $script:fakeSvc = [pscustomobject]@{ PathName = 'C:\synthetic\integrity-v2-backend.exe'; StartName = 'NT SERVICE\integrity-v2-backend'; StartMode = 'Manual'; State = 'Stopped' }
    return 'synthetic install success'
  }
  if ($script:phase -eq 'created-then-failed') {
    $script:fakeSvc = [pscustomobject]@{ PathName = 'C:\synthetic\integrity-v2-backend.exe'; StartName = 'NT SERVICE\integrity-v2-backend'; StartMode = 'Manual'; State = 'Stopped' }
    throw 'synthetic install failure'
  }
  if ($script:phase -eq 'foreign-path') {
    $script:fakeSvc = [pscustomobject]@{ PathName = 'C:\foreign\wrapper.exe'; StartName = 'NT SERVICE\integrity-v2-backend'; StartMode = 'Manual'; State = 'Stopped' }
    throw 'synthetic install failure'
  }
  throw 'synthetic no-service failure'
}
function Assert-V2Service { throw 'synthetic read-back failure' }
$cases = @(
  @{ Phase = 'created-then-failed'; Owned = $true },
  @{ Phase = 'created-readback-failed'; Owned = $true },
  @{ Phase = 'foreign-path'; Owned = $false },
  @{ Phase = 'no-service'; Owned = $false }
)
foreach ($case in $cases) {
  $script:fakeSvc = $null; $script:phase = $case.Phase; $script:owned.Clear()
  $failed = $false
  try { Install-V2Service -Name 'integrity-v2-backend' -OnCreated { param($name) $null = $script:owned.Add($name) } }
  catch { $failed = $true }
  if (-not $failed -or $script:owned.Contains('integrity-v2-backend') -ne $case.Owned) { throw "FAIL $($case.Phase)" }
  "PASS $($case.Phase)"
}
