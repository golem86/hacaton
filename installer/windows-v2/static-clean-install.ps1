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
  $iChk = $bt.IndexOf('if (Test-Path -LiteralPath $V2Root) { Stop-V2'); $iNew = $bt.IndexOf('New-V2Root -OnCreated')
  $ownedOk = $iChk -ge 0 -and $iChk -lt $iNew -and ([regex]::Matches($ciText, '\$script:Owned = \$true')).Count -eq 1 -and
    $ciText.Contains('New-V2Root -OnCreated { param($token) $script:OwnedToken = $token; $script:Owned = $true }') -and
    $commonText.Contains('[V2AtomicRoot]::Create($V2Root, $sec.GetSecurityDescriptorBinaryForm())') -and
    $commonText.IndexOf('[V2AtomicRoot]::Create($V2Root') -lt $commonText.IndexOf('& $OnCreated ([guid]::NewGuid()')
}
$ssmVia = @(if ($via.ContainsKey('Set-V2ServiceStartMode')) { $via['Set-V2ServiceStartMode'] | Sort-Object -Unique })
$fcText = $fn['Invoke-V2CleanInstallFailClosed'].Ast.Extent.Text
$ssmCalls = @($fn['Invoke-V2CleanInstallFailClosed'].Ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Set-V2ServiceStartMode' }, $true) | ForEach-Object { $_.Extent.Text })
$ssmOk = (($ssmVia -join ',') -eq 'Invoke-V2CleanInstallFailClosed') -and $ssmCalls.Count -ge 1 -and @($ssmCalls | Where-Object { $_ -notmatch '-Mode Disabled$' }).Count -eq 0 -and @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Set-V2ServiceStartMode' }, $true)).Count -eq 0
$noDel = $fcText -notmatch '(?i)Remove-Item|\.Delete\(|DeleteFile'
Add-Res 'CI-S6' ($stagesIn -and $catchOk -and $ownedOk -and $ssmOk -and $noDel) "CI-01 fail-closed: етапи 4.0–5 у try ($stagesIn); catch → лише за `$Owned Invoke-V2CleanInstallFailClosed ($catchOk); `$Owned після успішного atomic CreateDirectoryW ($ownedOk); Set-V2ServiceStartMode лише Disabled з fail-closed ($ssmOk); без видалення ($noDel)"
$ownedServicesOk = $ciText.Contains("Install-V2Service -Name integrity-v2-backend -OnCreated { param(`$name) `$null = `$OwnedServices.Add(`$name) }") -and $ciText.Contains("Install-V2Service -Name integrity-v2-caddy -OnCreated { param(`$name) `$null = `$OwnedServices.Add(`$name) }") -and
  $ciText.Contains('Invoke-V2CleanInstallFailClosed -Reason $why -OwnedServices @($OwnedServices)') -and $fcText.Contains('if ($OwnedServices -notcontains $n)')
Add-Res 'CI-S8' $ownedServicesOk 'R-00: stop/disable лише для служб, створення яких цей запуск підтвердив'
$pinnedCalls = @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Assert-V2PinnedHttps' }, $true))
$httpsWiringOk = $pinnedCalls.Count -eq 10 -and @($pinnedCalls | Where-Object { $_.Extent.Text -notmatch '@PinnedHttps' }).Count -eq 0 -and
  $ciText.Contains('$PinnedHttps = @{ HostName = $TlsHost; Addresses = $TlsAddresses; TestHost = $TestHost }') -and
  @($ci.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Assert-V2Http' -and $n.Extent.Text -match '\$H/' }, $true)).Count -eq 0 -and
  $reach.Contains('Assert-V2PinnedHttps')
Add-Res 'CI-S9' $httpsWiringOk 'R-01: Caddy start і всі HTTPS smoke звертаються через pinned endpoint; backend localhost лишається окремо'
# C1/C3 (№4): перевірки чистого стану (служби, корінь, порти) — у 4.0, ДО першого запису (Stage 4.1)
$i41 = $ciText.IndexOf("Stage '4.1"); $iSvc = $ciText.IndexOf('уже існує — Clean Install лише на чистому хості'); $iPorts = $ciText.IndexOf('  Assert-V2PortsFree'); $iHost = $ciText.IndexOf('  Assert-V2HostPreflight -ExpectedWindowsBuild')
$iRoot = $ciText.IndexOf('if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує — Clean Install лише на чистому хості')
Add-Res 'CI-S7' ($i41 -gt 0 -and $iSvc -gt 0 -and $iSvc -lt $i41 -and $iRoot -gt 0 -and $iRoot -lt $i41 -and $iPorts -gt 0 -and $iPorts -lt $i41 -and $iHost -gt 0 -and $iHost -lt $i41 -and $reach.Contains('Assert-V2PortsFree') -and $reach.Contains('Assert-V2HostPreflight')) "preflight до першого запису: служби V2 ($($iSvc -lt $i41)), корінь V2 ($($iRoot -lt $i41)), порти ($($iPorts -gt 0 -and $iPorts -lt $i41)), хост ($($iHost -gt 0 -and $iHost -lt $i41)) — перед Stage 4.1"
# --- Поточний реліз (CI-S10…CI-S15) ---------------------------------------------------------------------------------------------
# CI-S10: Automatic (Delayed Start) — лише Set-V2ServiceDelayedAuto, лише в clean-install після останнього smoke (у try → збій = fail-closed);
#         функція не досягає Set-V2ServiceStartMode; -KeepManualStart лишає Manual
$dIdx = $ciText.IndexOf('Set-V2ServiceDelayedAuto -Name $n'); $lastSmoke = $ciText.IndexOf("-Path '/assets/missing.js' -Expected 404")
$daBody = $fn['Set-V2ServiceDelayedAuto'].Ast.Extent.Text
$daCallers = @(if ($via.ContainsKey('Set-V2ServiceDelayedAuto')) { $via['Set-V2ServiceDelayedAuto'] })
$daOk = $dIdx -gt $lastSmoke -and $lastSmoke -gt 0 -and $try.Count -eq 1 -and $try[0].Body.Extent.Text.Contains('Set-V2ServiceDelayedAuto -Name $n') -and $daCallers.Count -eq 0 -and
        $daBody.Contains("'start=', 'delayed-auto'") -and $daBody.Contains('DelayedAutoStart') -and $daBody -notmatch 'Set-V2ServiceStartMode' -and $ciText.Contains('if ($KeepManualStart)')
Add-Res 'CI-S10' $daOk 'служби → Automatic (Delayed Start) лише після останнього smoke (Set-V2ServiceDelayedAuto, read-back Auto/delayed); у try (збій → fail-closed); -KeepManualStart'
# CI-S11: пакет формату оновлення; без dde86e6; перевірка до першого запису; маніфест коду → pkg\<ReleaseId>-BACKEND-SHA256.txt
$iPkg = $ciText.IndexOf('$Pkg0 = Assert-V2CleanPackage'); $iS41 = $ciText.IndexOf("Stage '4.1")
$pkgOk = $ciText -notmatch 'dde86e6|DeployZip|SHA256SUMS\.txt|wheelhouse' -and $iPkg -gt 0 -and $iPkg -lt $iS41 -and
         $ciText.Contains('Copy-V2CleanPackage -Package $Pkg0') -and $ciText.Contains('-PkgManifestPath "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt"') -and
         $ciText.Contains('Install-V2Requirements -Py $Py -Package $Pkg') -and $ciText.Contains('Assert-V2ReleaseSchemaBinding') -and
         $fn['Assert-V2CleanPackage'].Ast.Extent.Text.Contains("'requirements-hashed.txt'") -and $fn['Install-V2Requirements'].Ast.Extent.Text.Contains("'--require-hashes'") -and
         $fn['Expand-V2ReleaseBackend'].Ast.Extent.Text.Contains('if ($rel -match $V2BootstrapRx) { continue }')
Add-Res 'CI-S11' $pkgOk 'пакет: backend-src.zip/BACKEND-SHA256, dist.zip/DIST-SHA256, Caddyfile, requirements-hashed + wheels, APPROVED окремо — перевірка до 4.1; без dde86e6; маніфест → pkg\<ReleaseId>-BACKEND-SHA256.txt; pip --require-hashes; bind-check'
# CI-S12: bootstrap не розгортається; перший адміністратор — одноразово з каталогу інсталятора (-I, --backend)
$bsOk = -not @($copies | Where-Object { $_ -match 'bootstrap' }).Count -and $ciText.Contains("@('-I', '-X', 'utf8', `"`$K\v2_clean_bootstrap_admin.py`", '--backend', `$Backend") -and
        $ciText -notmatch "'-m', 'app\.v2_(clean_)?bootstrap_admin'"
Add-Res 'CI-S12' $bsOk 'модулі bootstrap у app\ не копіюються; v2_clean_bootstrap_admin.py — лише одноразовий виклик із каталогу інсталятора'
# CI-S13: версії БД за замовчуванням = версії коду релізу (migrations.SCHEMA_VERSION / v2_auth.AUTH_SCHEMA_VERSION); mark-synthetic; seed не в release
$repo = Split-Path -Parent (Split-Path -Parent $K)
$codeI = [regex]::Match([IO.File]::ReadAllText("$repo\backend\app\migrations.py"), '(?m)^SCHEMA_VERSION\s*=\s*(\d+)').Groups[1].Value
$codeA = [regex]::Match([IO.File]::ReadAllText("$repo\backend\app\v2_auth.py"), '(?m)^AUTH_SCHEMA_VERSION\s*=\s*(\d+)').Groups[1].Value
$m13 = [regex]::Match($commonText, '\$V2ReleaseSchema = \[ordered\]@\{ integrity = (\d+); auth = (\d+) \}')
$reachText = (@($reach) | ForEach-Object { $fn[$_].Ast.Extent.Text }) -join "`n"
$verOk = $m13.Success -and $m13.Groups[1].Value -eq $codeI -and $m13.Groups[2].Value -eq $codeA -and $reachText -notmatch "'--expect-version', '\d'" -and
         $fn['Complete-V2CleanDatabases'].Ast.Extent.Text.Contains("'mark-synthetic'") -and $fn['Invoke-V2Seed'].Ast.Extent.Text.Contains("APP_ENV = 'development'") -and
         $fn['Initialize-V2CleanDatabases'].Ast.Extent.Text.Contains('Invoke-V2Seed') -and $fn['Initialize-V2CleanDatabases'].Ast.Extent.Text -notmatch "Invoke-V2Py[^\n]*'app\.seed'"
Add-Res 'CI-S13' $verOk "версії БД: `$V2ReleaseSchema $($m13.Groups[1].Value)/$($m13.Groups[2].Value) = код ($codeI/$codeA); жодного закріпленого --expect-version у досяжних функціях; seed — лише development (нова БД); mark-synthetic"
# CI-S14: SMTP — несекретне з параметрів (Gmail: smtp.gmail.com:587 starttls, FROM = USER), пароль — приховано; без dev-mail
$sp = $fn['Get-V2SmtpPlan'].Ast.Extent.Text
$smtpOk = $ciText.Contains("-Prompted @('V2_SMTP_PASSWORD') -Values `$Smtp.Values") -and $sp.Contains("V2_SMTP_HOST = 'smtp.gmail.com'; V2_SMTP_PORT = '587'; V2_SMTP_TLS_MODE = 'starttls'; V2_SMTP_USER = `$User; V2_SMTP_FROM = `$User") -and
           $ciText.Contains('Read-V2GmailAppPassword') -and $ciText -notmatch 'V2_AUTH_DEV_MAIL\s*=' -and $commonText.Contains("foreach (`$n in 'INTEGRITY_DEMO_XROLE', 'V2_AUTH_DEV_MAIL', 'V2_AUTH_SECURE_COOKIE') { if (`$envNames -contains `$n) { Stop-V2")
Add-Res 'CI-S14' $smtpOk 'SMTP: Gmail (smtp.gmail.com:587, starttls, FROM = USER) або Custom; пароль лише SecureString; dev-mail у release заборонено (Test-V2WinswXml)'
# CI-S15: LM — лише після успішного встановлення (поза try), lm\Install-V2LmService.ps1 -Apply; матриця ACL включає lm\
$iCatchEnd = $ciText.IndexOf("Stage '6 локальна LM"); $tryEnd = if ($try.Count) { $try[0].Extent.EndOffset - $ci.Extent.StartOffset } else { -1 }
$lmOk = $iCatchEnd -gt $tryEnd -and $tryEnd -gt 0 -and $ciText.Contains('\lm\Install-V2LmService.ps1", ''-Apply''') -and $fn['Assert-V2AclMatrix'].Ast.Extent.Text.Contains('Assert-V2LmAcl') -and
         $ciText.Contains("if (`$TestHost) { Stop-V2 '-WithLm лише на сервері")
Add-Res 'CI-S15' $lmOk 'LM (-WithLm) — після CLEAN INSTALL PASS, поза fail-closed; lm\Install-V2LmService.ps1 -Apply; Assert-V2AclMatrix перевіряє lm\'
$res
"--- досяжні з clean-install.ps1 функції common ($($reach.Count)): $((@($reach) | Sort-Object) -join ', ')"
$fail = @($res | Where-Object { $_ -match ' FAIL ' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match ' PASS ' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
