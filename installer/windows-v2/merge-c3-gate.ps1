# Evidence compositor only. Never starts services or modifies the host.
param([Parameter(Mandatory)][string]$LocalSummary,
      [Parameter(Mandatory)][string]$RuntimeLog,
      [Parameter(Mandatory)][string]$MatrixTsv,
      [switch]$V1Absent)
$ErrorActionPreference = 'Stop'
$errors = New-Object System.Collections.Generic.List[string]
foreach ($path in $LocalSummary, $RuntimeLog, $MatrixTsv) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $errors.Add("немає evidence: $path") } }
if ($errors.Count) { $errors; exit 1 }
$local = Get-Content -LiteralPath $LocalSummary
$runtime = Get-Content -LiteralPath $RuntimeLog
$matrix = Get-Content -LiteralPath $MatrixTsv
if (@($local | Where-Object { $_ -match '→ FAIL$' }).Count -or -not @($local | Where-Object { $_ -match '^static-clean-install\s+exit=0.*→ PASS$' }).Count -or
    -not @($local | Where-Object { $_ -match '^test_v2_job\s+exit=0.*→ PASS$' }).Count -or -not @($local | Where-Object { $_ -match 'scope=LOCAL T0 ONLY' }).Count) { $errors.Add('T0 local summary не PASS або не LocalOnly') }
$requiredLocal = 'test_v2_auth_schema','test-clean-bootstrap','test-clean-root-race','test-atomic-compile','test-r03-gate','test-r01-target','test-r01-tls','test_v2_job','test-rev3-negative','test-audit-gate','static-rev3','static-clean-install','rehearse-rev3','runtime-harness-RH0'
foreach ($id in $requiredLocal) {
  if (@($local | Where-Object { $_ -match ('^' + [regex]::Escape($id) + '\s+exit=\d+.*→ PASS$') }).Count -ne 1) { $errors.Add("T0 suite ${id}: PASS відсутній або неоднозначний") }
}
$steps = 'J10.start','J10.stop','J10.disabled-1058','J18.timeout','J18.launcher-crash','J18.installer-held','RH-RB.ok','RH-RB.restart','RH-RB.failed'
foreach ($id in $steps) {
  $matches = @($runtime | Where-Object { $_ -match ('^' + [regex]::Escape($id) + '\s+PASS\s') })
  if ($matches.Count -ne 1) { $errors.Add("host runtime ${id}: PASS відсутній або неоднозначний") }
}
if (@($runtime | Where-Object { $_ -match '^\S+\s+(FAIL|NOT RUN)\s' }).Count) { $errors.Add('host runtime містить FAIL/NOT RUN') }
$ids = @('T0') + @(1..12 | ForEach-Object { "T$_" }) + @('T10a')
if (-not $V1Absent) { $ids += 'T13' } else { $ids += 'V1-absent' }
foreach ($id in $ids) {
  $rows = @($matrix | Where-Object { $_ -match ('^' + [regex]::Escape($id) + "`t") })
  if ($rows.Count -ne 1) { $errors.Add("matrix ${id}: рядок відсутній або неоднозначний"); continue }
  $fields = $rows[0] -split "`t", 4
  if ($fields.Count -ne 4 -or $fields[1] -ne 'PASS' -or -not (Test-Path -LiteralPath $fields[2] -PathType Leaf) -or (Get-FileHash -LiteralPath $fields[2] -Algorithm SHA256).Hash.ToLower() -ne $fields[3].ToLower()) { $errors.Add("matrix ${id}: статус або hash evidence не PASS") }
}
if ($errors.Count) { $errors | ForEach-Object { "C3/C8 FAIL $_" }; exit 1 }
'C3/C8 PASS: local T0, host J10/J18/RH-RB та T0–T12/T10a/T13 evidence hashes підтверджені; потрібен незалежний review №4 і рішення №5'
exit 0
