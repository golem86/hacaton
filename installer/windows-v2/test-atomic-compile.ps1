$ErrorActionPreference = 'Stop'
$source = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'V2-install-common.ps1') -Raw
$match = [regex]::Match($source, "(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@")
if (-not $match.Success) { 'R00.native-compile FAIL C# source missing'; exit 1 }
try {
  Add-Type -TypeDefinition $match.Groups[1].Value -ErrorAction Stop
  $method = [V2AtomicRoot].GetMethod('Create')
  if (-not $method -or $method.GetParameters().Count -ne 2) { throw 'Create signature missing' }
  'R00.native-compile PASS Win32 CreateDirectoryW P/Invoke compiled; no directory created'
  exit 0
} catch { "R00.native-compile FAIL $($_.Exception.Message)"; exit 1 }
