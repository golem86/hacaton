param([Parameter(Mandatory)][string]$Py)
$ErrorActionPreference = 'Stop'
$source = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'run-all.ps1') -Raw
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'run-all.ps1 parse failed' }
# Реальні функції run-all.ps1 (паралельний режим): Start-Suite + Complete-Suites — саме вони виносять вердикт набору
foreach ($name in 'Start-Suite', 'Complete-Suites') {
  $fn = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
  if (-not $fn) { throw "$name missing" }
  . ([scriptblock]::Create($fn.Extent.Text))
}
$LogDir = Join-Path $env:TEMP ('v2-audit-gate-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $LogDir
$tmp = $LogDir
$sum = New-Object System.Collections.Generic.List[string]
$suites = New-Object System.Collections.Generic.List[object]
try {
  Start-Suite 'required-not-run' $Py @('-c', 'print(''REQ NOT RUN synthetic-required-case'')')   # без подвійних лапок: Windows PowerShell 5.1 прибирає їх у нативних аргументах
  Complete-Suites
  $record = @($sum)[0]
  $ok = $record -match 'exit=0' -and $record -match 'NOT_RUN=1' -and $record -match '→ FAIL$'
  if (-not $ok) { Write-Output "B04.required-not-run FAIL $record"; exit 1 }
  Write-Output "B04.required-not-run PASS $record"
  exit 0
} finally {
  Remove-Item -LiteralPath $LogDir -Recurse -Force
}
