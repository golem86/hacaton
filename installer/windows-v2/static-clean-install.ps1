# static-clean-install.ps1 — статичний доказ меж сценарію CLEAN INSTALL (C1, C7): граф викликів clean-install.ps1 через функції
# V2-install-common.ps1. Код завершення 1 при будь-якому FAIL. Лише читання файлів.
$ErrorActionPreference = 'Stop'
$K = $PSScriptRoot
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-6} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
function Parse([string]$f) { $t = $null; $e = $null; $a = [Management.Automation.Language.Parser]::ParseFile($f, [ref]$t, [ref]$e); if ($e.Count) { throw "parse ${f}: $($e[0].Message)" }; $a }
$common = Parse "$K\V2-install-common.ps1"; $ci = Parse "$K\clean-install.ps1"
$cmds = { param($ast) @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $_ } | Sort-Object -Unique) }
$fn = @{}
foreach ($f in $common.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) { $fn[$f.Name] = @{ Ast = $f; Calls = (& $cmds $f.Body) } }
# граф досяжності від clean-install.ps1
$reach = New-Object 'System.Collections.Generic.HashSet[string]'; $queue = New-Object System.Collections.Generic.Queue[string]
foreach ($c in (& $cmds $ci)) { if ($fn.ContainsKey($c) -and $reach.Add($c)) { $queue.Enqueue($c) } }
$via = @{}
while ($queue.Count) { $cur = $queue.Dequeue(); foreach ($c in $fn[$cur].Calls) { if ($fn.ContainsKey($c)) { if (-not $via.ContainsKey($c)) { $via[$c] = New-Object System.Collections.Generic.List[string] }; $via[$c].Add($cur); if ($reach.Add($c)) { $queue.Enqueue($c) } } } }
$rollback = 'Invoke-V2DbRestore', 'Invoke-V2DbRestoreCore', 'Assert-V2RestorePermitted', 'Assert-V2RestoreItems', 'Assert-V2RestoreReady', 'Import-V2Identities', 'Assert-V2SqliteSidecars'
$jobOnly = 'Get-V2JobReport', 'Start-V2JobHolder', 'Stop-V2JobHolder', 'Invoke-V2JobTool'
$bad = @($rollback | Where-Object { $reach.Contains($_) })
Add-Res 'CI-S1' ($bad.Count -eq 0) "механізми Upgrade/Rollback недосяжні з clean-install.ps1 ($($rollback.Count) функцій): $(if ($bad.Count) { $bad -join ', ' } else { 'жодної' })"
# Job Object — лише через ядро зупинки служби, і лише за $V2Services.Job ≠ $null; clean-install перевіряє Job = $null на старті
$jobCallers = @($jobOnly | Where-Object { $reach.Contains($_) } | ForEach-Object { $via[$_] } | Where-Object { $jobOnly -notcontains $_ } | Sort-Object -Unique)
$core = $fn['Stop-V2ServiceCore'].Ast.Extent.Text
$guarded = $core.Contains('$jobName = $V2Services[$Name].Job') -and ([regex]::Matches($core, 'if \(\$jobName\) \{').Count -ge 2)
$ciText = $ci.Extent.Text
$g0 = $ciText.Contains("if (`$V2Services['integrity-v2-backend'].Job) { Stop-V2") -and $ciText.Contains('if ($V2JobLocalRehearsal -or $V2JobTool.Py -or $V2JobTool.Script)')
$relOnly = @('Stop-V2Service', 'Invoke-V2ServiceStart' | ForEach-Object { @($fn[$_].Calls | Where-Object { $jobOnly -contains $_ }) -join ',' }) -join '|'
Add-Res 'CI-S2' ((($jobCallers -join ',') -eq 'Invoke-V2ServiceStart,Stop-V2Service,Stop-V2ServiceCore') -and $relOnly -eq 'Stop-V2JobHolder|Stop-V2JobHolder' -and $guarded -and $g0) "Job Object: запуск/proof лише в Stop-V2ServiceCore під умовою `$V2Services.Job; обгортки лише звільняють наявну lease ($relOnly); G0 clean-install вимагає Job = `$null"
# Незалежність від V1: жодних шляхів/імен V1 у рядках clean-install.ps1; V1-імена в досяжних функціях — лише в Get-V1Baseline (читання, -AllowAbsent)
$strs = @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.StringConstantExpressionAst] -or $n -is [Management.Automation.Language.ExpandableStringExpressionAst] }, $true) | ForEach-Object { $_.Value })
$v1InCi = @($strs | Where-Object { $_ -match '(?i)HacatonServer|HacatonBackend|C:\\Users\\Public' })
$v1Fns = @($reach | Where-Object { $fn[$_].Ast.Extent.Text -match '(?i)HacatonServer|C:\\Users\\Public' })
$hbFns = @($reach | Where-Object { $fn[$_].Ast.Extent.Text -match 'HacatonBackend' } | Sort-Object)
$baseCalls = @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Get-V1Baseline' }, $true))
$allAbsent = @($baseCalls | Where-Object { $_.Extent.Text -notmatch '-AllowAbsent' }).Count -eq 0
Add-Res 'CI-S3' ($v1InCi.Count -eq 0 -and $v1Fns.Count -eq 0 -and (($hbFns -join ',') -eq 'Assert-V1Unchanged,Get-V1Baseline') -and $baseCalls.Count -ge 1 -and $allAbsent) "без каталогів V1: рядків V1 у clean-install $($v1InCi.Count); шляхів V1 у досяжних функціях $($v1Fns.Count); ім'я HacatonBackend лише в $($hbFns -join ','); Get-V1Baseline лише з -AllowAbsent"
# Інструменти — лише з артефакту V2 із закріпленими SHA256
$copies = @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Copy-Item' }, $true) | ForEach-Object { $_.Extent.Text })
$toolCopies = @($copies | Where-Object { $_ -match 'integrity-v2-(backend|caddy)\.exe|caddy\\bin\\caddy\.exe' })
$okTools = ($toolCopies.Count -eq 3) -and (@($toolCopies | Where-Object { $_ -notmatch '-LiteralPath \$(WinSWSrc|CaddySrc) ' }).Count -eq 0) -and $ciText.Contains('$WinSWSrc = "$V2Root\pkg\tools\winsw\integrity-v2-winsw.exe"; $CaddySrc = "$V2Root\pkg\tools\caddy\caddy.exe"') -and
           $ciText.Contains('Expand-V2Tools -ToolsZip $ToolsZip -Destination "$V2Root\pkg\tools"') -and @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Expand-V2Tools' -and $n.Extent.Text -match 'ExpectedSha256' }, $true)).Count -eq 0
$commonText = $common.Extent.Text
Add-Res 'CI-S4' ($okTools -and $commonText.Contains("`$V2ToolsSha256 = [ordered]@{ 'winsw/integrity-v2-winsw.exe' = `$WinswRefSha256; 'caddy/caddy.exe' = `$CaddyRefSha256 }")) 'WinSW і Caddy копіюються лише з артефакту V2 (Expand-V2Tools, SHA256 = закріплені еталони, без перевизначення)'
# Ініціалізація БД: лише через Initialize/Complete-V2CleanDatabases; старт backend — стандартний PreCheck (Assert-V2DataReady)
$init = $reach.Contains('Initialize-V2CleanDatabases') -and $reach.Contains('Complete-V2CleanDatabases') -and $reach.Contains('Assert-V2DataReady')
$ssText = $fn['Invoke-V2ServiceStart'].Ast.Extent.Text
$noCustomPre = @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Invoke-V2ServiceStart' -and $n.Extent.Text -match '-PreCheck' }, $true)).Count -eq 0
Add-Res 'CI-S5' ($init -and $ssText.Contains('Assert-V2DataReady -DataDir "$V2Root\data"') -and $noCustomPre) 'нові БД — Initialize/Complete-V2CleanDatabases (маркери, строгий auth-schema); старт backend лише зі стандартним PreCheck (Assert-V2DataReady)'
# CI-01: fail-closed після створення кореня — весь ланцюжок 4.0–5 у try; catch лише за $Owned викликає Invoke-V2CleanInstallFailClosed;
# Set-V2ServiceStartMode (сервісна функція SCM) — лише з fail-closed і лише Disabled
$try = @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.TryStatementAst] }, $false) | Where-Object { $_.Body.Extent.Text -match "Stage '4\.0" })
$stagesIn = $false; $catchOk = $false; $ownedOk = $false
if ($try.Count -eq 1) {
  $bt = $try[0].Body.Extent.Text
  $stagesIn = @("Stage '4.0", "Stage '4.1", "Stage '4.5", "Stage '4.6", "Stage '4.7", "Stage '5 smoke" | Where-Object { -not $bt.Contains($_) }).Count -eq 0
  $ct = ($try[0].CatchClauses | ForEach-Object { $_.Extent.Text }) -join "`n"
  $catchOk = $try[0].CatchClauses.Count -eq 1 -and $ct -match '(?s)if \(-not \$Owned\) \{.*?exit 1.*?\}.*Invoke-V2CleanInstallFailClosed -Reason \$why' -and -not $try[0].Finally
  $iOwn = $bt.IndexOf('$Owned = $true'); $iChk = $bt.IndexOf('if (Test-Path -LiteralPath $V2Root) { Stop-V2'); $iNew = $bt.IndexOf('New-V2Root')
  $ownedOk = ([regex]::Matches($ciText, '\$Owned = \$true')).Count -eq 1 -and $iChk -ge 0 -and $iChk -lt $iOwn -and $iOwn -lt $iNew
}
$ssmVia = @(if ($via.ContainsKey('Set-V2ServiceStartMode')) { $via['Set-V2ServiceStartMode'] | Sort-Object -Unique })
$fcText = $fn['Invoke-V2CleanInstallFailClosed'].Ast.Extent.Text
$ssmCalls = @($fn['Invoke-V2CleanInstallFailClosed'].Ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Set-V2ServiceStartMode' }, $true) | ForEach-Object { $_.Extent.Text })
$ssmOk = (($ssmVia -join ',') -eq 'Invoke-V2CleanInstallFailClosed') -and $ssmCalls.Count -ge 1 -and @($ssmCalls | Where-Object { $_ -notmatch '-Mode Disabled$' }).Count -eq 0 -and @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Set-V2ServiceStartMode' }, $true)).Count -eq 0
$noDel = $fcText -notmatch '(?i)Remove-Item|\.Delete\(|DeleteFile'
Add-Res 'CI-S6' ($stagesIn -and $catchOk -and $ownedOk -and $ssmOk -and $noDel) "CI-01 fail-closed: етапи 4.0–5 у try ($stagesIn); catch → лише за `$Owned Invoke-V2CleanInstallFailClosed ($catchOk); `$Owned після перевірки кореня й до New-V2Root ($ownedOk); Set-V2ServiceStartMode лише Disabled з fail-closed ($ssmOk); без видалення ($noDel)"
# C1/C3 (№4): перевірки чистого стану (служби, корінь, порти) — у 4.0, ДО першого запису (Stage 4.1)
$i41 = $ciText.IndexOf("Stage '4.1"); $iSvc = $ciText.IndexOf('уже існує — Clean Install лише на чистому хості'); $iPorts = $ciText.IndexOf('  Assert-V2PortsFree'); $iHost = $ciText.IndexOf('  Assert-V2HostPreflight -ExpectedWindowsBuild')
$iRoot = $ciText.IndexOf('if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує — Clean Install лише на чистому хості')
Add-Res 'CI-S7' ($i41 -gt 0 -and $iSvc -gt 0 -and $iSvc -lt $i41 -and $iRoot -gt 0 -and $iRoot -lt $i41 -and $iPorts -gt 0 -and $iPorts -lt $i41 -and $iHost -gt 0 -and $iHost -lt $i41 -and $reach.Contains('Assert-V2PortsFree') -and $reach.Contains('Assert-V2HostPreflight')) "preflight до першого запису: служби V2 ($($iSvc -lt $i41)), корінь V2 ($($iRoot -lt $i41)), порти ($($iPorts -gt 0 -and $iPorts -lt $i41)), хост ($($iHost -gt 0 -and $iHost -lt $i41)) — перед Stage 4.1"
$res
"--- досяжні з clean-install.ps1 функції common ($($reach.Count)): $((@($reach) | Sort-Object) -join ', ')"
$fail = @($res | Where-Object { $_ -match ' FAIL ' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match ' PASS ' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
