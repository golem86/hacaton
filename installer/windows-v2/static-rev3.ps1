# Статична перевірка INSTALLATION PLAN REV3: розбір блоків PowerShell плану і спільних функцій; заборонені конструкції.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\static-rev3.ps1 [-Plan <V2_INSTALLATION_FINAL_PLAN.md>]
# Код завершення: 0 — усі PASS; 1 — є FAIL.
param([string] $Plan = (Join-Path $PSScriptRoot 'V2_INSTALLATION_FINAL_PLAN.md'))
$ErrorActionPreference = 'Stop'
$common = Join-Path $PSScriptRoot 'V2-install-common.ps1'
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-3} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
$md = [IO.File]::ReadAllText($Plan)
$blocks = @([regex]::Matches($md, '(?s)```powershell\r?\n(.*?)```') | ForEach-Object { $_.Groups[1].Value })
$errs = @(); $i = 0
foreach ($b in $blocks) { $i++; $t = $null; $e = $null; [void][System.Management.Automation.Language.Parser]::ParseInput($b, [ref]$t, [ref]$e); if ($e.Count) { $errs += "блок ${i}: $($e[0].Message)" } }
Add-Res 'P1' ($errs.Count -eq 0 -and $blocks.Count -ge 10) "блоків PowerShell у плані: $($blocks.Count); помилок розбору: $($errs.Count) $($errs -join '; ')"
$t = $null; $e = $null; $ast = [System.Management.Automation.Language.Parser]::ParseFile($common, [ref]$t, [ref]$e)
$bom = [IO.File]::ReadAllBytes($common)[0..2] -join ','
Add-Res 'P2' ($e.Count -eq 0 -and $bom -eq '239,187,191') "V2-install-common.ps1: помилок розбору $($e.Count); BOM: $($bom -eq '239,187,191')"
$code = (@($t | Where-Object { "$($_.Kind)" -notin 'Comment', 'StringLiteral', 'StringExpandable', 'NewLine' } | ForEach-Object Text) -join ' ')
$cmds = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $_ } | Sort-Object -Unique)
$forbidden = @('Set-Acl', 'Set-Service', 'New-Service', 'Remove-Service', 'Restart-Service', 'Set-ItemProperty', 'New-NetFirewallRule', 'Set-NetFirewallRule', 'Start-Transcript')
$hit = @($cmds | Where-Object { $forbidden -contains $_ })
Add-Res 'P3' ($hit.Count -eq 0) "заборонені команди (Set-Acl, *-Service, Firewall, Start-Transcript): $($hit -join ',')"
$planCode = (($blocks -join "`n") -replace '(?m)\s#\s.*$', '')
$insecure = [regex]::IsMatch($planCode, "'-k'|--insecure|curl(\.exe)?\s+-\S*k") -or [regex]::IsMatch([IO.File]::ReadAllText($common), "'-k'|--insecure")
Add-Res 'P4' (-not $insecure -and -not [regex]::IsMatch($code, 'LocalSystem|LocalService')) 'немає curl -k/--insecure; LocalSystem/LocalService не використовуються в коді'
$src = [IO.File]::ReadAllText($common)
Add-Res 'P5' (([regex]::Matches($src, 'icacls\.exe')).Count -eq 1 -and -not [regex]::IsMatch($src, "sc\.exe['""]?\s*-ArgList\s*@\('(delete|failure|sdset|privs)")) 'icacls — лише в Grant-V2; sc.exe — лише config/start/stop'
[xml]$xb = Get-Content (Join-Path $PSScriptRoot 'integrity-v2-backend.xml.template') -Raw -Encoding UTF8
[xml]$xc = Get-Content (Join-Path $PSScriptRoot 'integrity-v2-caddy.xml.template') -Raw -Encoding UTF8
$okX = $xb.service.startmode -eq 'Manual' -and $xc.service.startmode -eq 'Manual' -and $xb.service.serviceaccount.domain -eq 'NT SERVICE' -and $xb.service.serviceaccount.user -eq 'integrity-v2-backend' -and
       $xc.service.serviceaccount.user -eq 'integrity-v2-caddy' -and -not $xb.service.serviceaccount.SelectSingleNode('password')
Add-Res 'P6' $okX 'XML: обидва Manual; NT SERVICE\integrity-v2-backend / -caddy; без пароля'
# P7 (R2-04): $LASTEXITCODE дозволений лише для перевірки коду прямого інтерактивного дочірнього процесу.
$lec = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.VariableExpressionAst] -and $args[0].VariablePath.UserPath -eq 'LASTEXITCODE' }, $true)).Count
$planLec = [regex]::Matches($planCode, '\$LASTEXITCODE').Count
$planNative = [regex]::Matches($planCode, '(?m)(^|[;{(]\s*|=\s*)&\s*(\$|curl|sc|icacls)').Count
Add-Res 'P7' ($lec -eq 1 -and $planLec -eq 0 -and $planNative -eq 0 -and $src.Contains('& $Exe @ArgList')) "R2-04: `$LASTEXITCODE лише в інтерактивній функції ($lec); у плані $planLec; прямий інтерактивний виклик є=$($src.Contains('& $Exe @ArgList'))"
# P8 (R2-02): у функціях немає SilentlyContinue для Remove-Item/Stop-Process
$silent = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] -and $args[0].GetCommandName() -in 'Remove-Item', 'Stop-Process' -and $args[0].Extent.Text -match 'SilentlyContinue' }, $true)).Count
Add-Res 'P8' ($silent -eq 0) "R2-02: Remove-Item/Stop-Process з SilentlyContinue у функціях: $silent"
# P9 (R2-03, R2-06): у плані служби стартують лише через Invoke-V2ServiceStart; є Assert-V2AclMatrix і Test-V2WinswXml; еталон Caddy
$okP9 = -not [regex]::IsMatch($planCode, 'Start-V2Service|Start-Service|sc\.exe.*start') -and [regex]::Matches($planCode, 'Invoke-V2ServiceStart').Count -ge 2 -and
        $planCode.Contains('Assert-V2AclMatrix') -and [regex]::Matches($planCode, 'Test-V2WinswXml').Count -ge 4 -and $src.Contains("2622e239c79df700b0eb92cbd950d1edee365e155a7859f358f0e55f002df591")
Add-Res 'P9' $okP9 'R2-03/R2-06: старт служб лише через Invoke-V2ServiceStart; Assert-V2AclMatrix; Test-V2WinswXml; еталон SHA256 Caddy у функціях'
# P10 (R2-05): відкат і SQLite — Assert-V2NoProcesses з -DataDir
Add-Res 'P10' ($planCode -match 'Assert-V2NoProcesses -DataDir') 'R2-05: перед відкатом/відновленням SQLite — Assert-V2NoProcesses -DataDir'
# P11 (P2/PID 4): у common процеси зупиняються лише через адаптер (handle); жодного Stop-Process/Kill/GetProcessById/WaitForExit поза ним
$raw = @([regex]::Matches($src, '(?m)^(?!function (Open-V2ProcessHandle|Stop-V2Handle|Wait-V2Handle)).*(\.Kill\(\)|GetProcessById|\.WaitForExit\(|Stop-Process)') | ForEach-Object { $_.Value.Trim() } | Where-Object { -not $_.StartsWith('#') })
Add-Res 'P11' ($raw.Count -eq 0) "P2: прямих Kill/GetProcessById/WaitForExit/Stop-Process поза адаптером: $($raw.Count)"
# P12 (PID 4): тест не містить PID системних процесів і перевіряє ізоляцію (I0) та відсутність реальних викликів (I9)
$tst = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'test-rev3-negative.ps1'))
$pid4 = [regex]::IsMatch($tst, '(?i)(-Id\s+|Known\s*@\([^)]*?)\b[0-9]{1,3}\b|PID\s+4\b')
Add-Res 'P12' (-not $pid4 -and $tst.Contains("Add-Res 'I0'") -and $tst.Contains("Add-Res 'I9'") -and $tst.Contains('REAL-CALL-BLOCKED')) 'PID 4: у тестах немає PID системних процесів; є перевірка ізоляції I0 і лічильник реальних викликів I9'
# P13 (P6): WinSW 2.12.0 закріплено в common; у плані — перевірка джерела і копій
Add-Res 'P13' ($src.Contains("`$WinswRefVersion = '2.12.0'") -and $src.Contains('05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da') -and [regex]::Matches($planCode, 'Assert-V2Winsw').Count -ge 3) 'P6: WinSW 2.12.0 + SHA 05b82d46… у common; Assert-V2Winsw для джерела й копій у плані'
# P14 (P4 + дельта 3): відновлення БД лише через Invoke-V2DbRestore; у ній Assert-V2RestorePermitted і Assert-V2RestoreReady — до першого Rename-Item; ідентичності з файлу
$fr = [regex]::Match($src, '(?s)function Invoke-V2DbRestoreCore \{.*?\n\}').Value   # auditfix2: логіка відкату — у ядрі; обгортка — cleanup
$iP = $fr.IndexOf('Assert-V2RestorePermitted'); $iR = $fr.IndexOf('Assert-V2RestoreReady'); $iN = $fr.IndexOf('Rename-Item')
Add-Res 'P14' ($planCode.Contains('Invoke-V2DbRestore') -and $planCode.Contains('Import-V2Identities') -and $iP -ge 0 -and $iR -gt $iP -and $iN -gt $iR) 'P4/дельта 3: Invoke-V2DbRestore і Import-V2Identities у процедурі відкату; Assert-V2RestorePermitted → Assert-V2RestoreReady → лише потім Rename-Item'
# P15 (дельта 5): у файлах комплекту немає керівних байтів (окрім TAB/LF/CR) — захист від пошкодження regex на кшталт 0x08
$bad = @(foreach ($f in 'V2-install-common.ps1', 'test-rev3-negative.ps1', 'static-rev3.ps1', 'rehearse-rev3.ps1', 'v2_db_tool.py', 'V2_INSTALLATION_FINAL_PLAN.md', 'integrity-v2-backend.xml.template', 'integrity-v2-caddy.xml.template',
                         'v2_job_launcher.py', 'job_child.py', 'test_v2_job.py', 'test_v2_auth_schema.py', 'mutate.py', 'runtime-harness.ps1', 'run-all.ps1', 'integrity-v2-jobtest.TEST-ONLY.xml.template', 'clean-install.ps1', 'static-clean-install.ps1', 'test-audit-gate.ps1') {
  $fp = Join-Path $PSScriptRoot $f; if (-not (Test-Path -LiteralPath $fp)) { continue }
  $n = @([IO.File]::ReadAllBytes($fp) | Where-Object { $_ -lt 32 -and $_ -notin 9, 10, 13 }).Count; if ($n) { "${f}: $n" } })
Add-Res 'P15' ($bad.Count -eq 0) "керівні байти у файлах комплекту: $(if ($bad.Count) { $bad -join '; ' } else { 0 })"
# P16 (B1/B3): відкриття handle нащадка без мовчазного catch { continue }; Invoke-V2DbRestore перевіряє набір БД до мутацій
$fa = [regex]::Match($src, '(?s)function Add-V2TreeIdentities \{.*?\n\}').Value
$silent16 = [regex]::IsMatch($fa, 'Open-V2ProcessHandle[^\n]*catch\s*\{\s*continue\s*\}')
$iItems = $fr.IndexOf('Assert-V2RestoreItems'); $iBlock = $fr.IndexOf('Assert-V2NoRestoreBlock')
Add-Res 'P16' (-not $silent16 -and $fa.Contains('$Unresolved.Add(') -and $iItems -ge 0 -and $iItems -lt $iBlock -and $iItems -lt $iN -and $src.Contains("`$V2DbSet = [ordered]@{ 'integrity_v2.db' = `$V2ReleaseSchema.integrity; 'v2_auth.db' = `$V2ReleaseSchema.auth }")) 'B1: немає мовчазного пропуску помилки handle нащадка; B3: Assert-V2RestoreItems (2 БД: версії поточного релізу) — перша дія Invoke-V2DbRestore'
# P17 (етап 2): експериментальний launcher — атомарно в job (JOB_LIST), CREATE_SUSPENDED, точний HANDLE_LIST, handle job неуспадковуваний,
# ліміти лише KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION (без BREAKAWAY_OK/SILENT_BREAKAWAY_OK), перевірка членства до ResumeThread, ім'я вже існує → STOP
$lau = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'v2_job_launcher.py'))
$sp = [regex]::Match($lau, '(?s)def spawn_in_job\(.*?\n(?=def )').Value
$ok17 = $lau.Contains('REQUIRED_LIMITS = KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION' + "`n") -and $lau.Contains('SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd, False)') -and
        $lau.Contains('if err == ERROR_ALREADY_EXISTS:') -and $sp.Contains('PROC_THREAD_ATTRIBUTE_JOB_LIST') -and $sp.Contains('PROC_THREAD_ATTRIBUTE_HANDLE_LIST') -and
        $sp.Contains('flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT') -and $sp.IndexOf('is_in_job(pi.hProcess, job)') -ge 0 -and
        $sp.IndexOf('is_in_job(pi.hProcess, job)') -lt $sp.IndexOf('api.ResumeThread(') -and -not [regex]::IsMatch($lau, 'LimitFlags\s*[|]?=\s*[^\n]*BREAKAWAY')
Add-Res 'P17' $ok17 'етап 2: launcher — JOB_LIST + CREATE_SUSPENDED + HANDLE_LIST; членство до ResumeThread; handle job неуспадковуваний; без breakaway; ім''я вже існує → STOP'
# P18 (етап 2): Job Object НЕ увімкнено в production-конфігурації; production WinSW XML без launcher-а; тестовий XML — лише id integrity-v2-jobtest
$tx = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'integrity-v2-jobtest.TEST-ONLY.xml.template'))
$bx = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'integrity-v2-backend.xml.template'))
Add-Res 'P18' ($src -match "(?m)^\s+Job = \`$null \}" -and -not $bx.Contains('v2_job_launcher') -and $tx.Contains('<id>integrity-v2-jobtest</id>') -and -not $tx.Contains('C:\srv') -and -not $planCode.Contains('v2_job_launcher')) 'етап 2: Job Object вимкнено в production ($V2Services.Job = $null); production XML і план без launcher-а; тестовий XML — окремий id, не C:\srv'
# P19 (етап 1): строга перевірка v2_auth — закріплений release-DDL; у відкаті — для копії ДО мутації і для відновленого файлу ДО RESTORE-OK
$dbt = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'v2_db_tool.py'))
$iA1 = $fr.IndexOf("@('auth-schema', `$it.Backup, '--expect-version', "); $iA2 = $fr.IndexOf("@('auth-schema', `$dst, '--expect-version', "); $iOk = $fr.IndexOf('RESTORE-OK-')
# Hardening (I5): SHA джерела схеми не закріплюється в коді — береться з маніфесту релізу (bind-check --release-manifest)
$okBind = -not $dbt.Contains('RELEASE_AUTH_SOURCE_SHA256') -and $dbt.Contains('def cmd_bind_check(') -and $dbt.Contains('--release-manifest') -and $dbt.Contains('SCHEMA_SPECS = {')
Add-Res 'P19' ($okBind -and $iA1 -ge 0 -and $iA1 -lt $iN -and $iA2 -gt $iN -and $iA2 -lt $iOk) 'етап 1: auth-schema прив''язаний до release через маніфест (bind-check, без закріпленого SHA у коді); копія — до мутації, відновлений файл — до RESTORE-OK'
# P20 (етап 3): відкат лише з доказом рівня job (Completeness = job, JobActive 0, OwnerScanAlive 0)
$fp20 = [regex]::Match($src, '(?s)function Assert-V2RestorePermitted \{.*?\n\}').Value
Add-Res 'P20' ($fp20.Contains("`$pr.Completeness -ne 'job'") -and $fp20.Contains('$pr.JobActive -ne 0') -and $fp20.Contains('$pr.OwnerScanAlive -ne 0')) 'етап 3: Assert-V2RestorePermitted вимагає доказу рівня Job Object (інакше P4 BLOCKED)'
# P21 (auditfix2): жодна функція common не визначена двічі (пізніше визначення мовчки перекриває раніше)
$fnames = @([regex]::Matches($src, '(?m)^function\s+([A-Za-z0-9-]+)') | ForEach-Object { $_.Groups[1].Value })
$dups = @($fnames | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object Name)
Add-Res 'P21' ($dups.Count -eq 0) "дублікати функцій у common: $(if ($dups.Count) { $dups -join ', ' } else { 0 })"
# P22 (auditfix2): локальний режим сканування (baseline) — лише в rehearse; у common = $null, у плані відсутній
$reh = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'rehearse-rev3.ps1'))
$assign = @([regex]::Matches($src, '\$V2JobLocalRehearsal\s*=\s*[^\r\n]*') | ForEach-Object Value)
Add-Res 'P22' ($assign.Count -eq 1 -and $assign[0] -match '^\$V2JobLocalRehearsal = \$null' -and -not $planCode.Contains('V2JobLocalRehearsal') -and $reh.Contains('V2JobLocalRehearsal = @{')) 'локальна адаптація scan (baseline) — лише rehearse; production: --unknown block'
# P23 (auditfix2, B-03): W1 (start type Disabled) → W2 (фінальний scan) → перша мутація; W5 (стан служби, scan, файли, SHA256) → RESTORE-OK; обгортка інвалідує proof і звільняє lease
$iW1 = $fr.IndexOf('Set-V2ServiceStartMode -Name $n -Mode Disabled'); $iW2 = $fr.IndexOf('$fresh = Get-V2JobReport'); $iMut = $fr.IndexOf('[IO.File]::WriteAllText($prog'); $iRen = $fr.IndexOf('Rename-Item -LiteralPath $f')
$iW5 = $fr.IndexOf('$end = Get-V2JobReport'); $iW5h = $fr.IndexOf('W5: $(Split-Path $k -Leaf) змінено'); $iOkM = $fr.IndexOf('"RESTORE-OK-$ts.txt"')
$wr = [regex]::Match($src, '(?s)function Invoke-V2DbRestore \{.*?\n\}').Value
$ss = [regex]::Match($src, '(?s)function Invoke-V2ServiceStart \{.*?\n\}').Value
Add-Res 'P23' ($iW1 -ge 0 -and $iW2 -gt $iW1 -and $iMut -gt $iW2 -and $iRen -gt $iMut -and $iW5 -gt $iRen -and $iW5h -gt $iW5 -and $iOkM -gt $iW5h -and $wr.Contains('$V2StopProof.Remove($n)') -and $wr.Contains('Stop-V2JobHolder -Holder $pf.Lease') -and $wr.Contains('finally') -and $ss.IndexOf('$V2StopProof.Remove($Name)') -ge 0 -and $ss.IndexOf('$V2StopProof.Remove($Name)') -lt $ss.IndexOf('& $PreCheck $Name')) 'B-03: W1 → W2 → мутація; W5 → RESTORE-OK; finally: proof інвалідовано, lease звільнено; старт інвалідує proof до PreCheck'
# P24 (auditfix3): ім'я служби backend у логіці відкату — одна змінна; у common лише 'integrity-v2-backend', змінює тільки runtime-harness; у плані відсутня
$hz = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'runtime-harness.ps1'))
$bn = @([regex]::Matches($src, '\$V2BackendName\s*=\s*[^\r\n]*') | ForEach-Object Value)
Add-Res 'P24' ($bn.Count -eq 1 -and $bn[0] -match "^\`$V2BackendName = 'integrity-v2-backend'" -and -not $planCode.Contains('V2BackendName') -and $hz.Contains('$V2BackendName = $svcName') -and -not $reh.Contains('V2BackendName')) 'ім''я служби відкату: common — integrity-v2-backend; лише runtime-harness підставляє тестову службу'
# P25 (auditfix3, P0): перевірка sidecar-ів SQLite у W5 — після SHA256 і ДО RESTORE-OK; функція перевіряє -journal, -wal, -shm і режим заголовка
$fsc = [regex]::Match($src, '(?s)function Assert-V2SqliteSidecars \{.*?\n\}').Value
$iSc = $fr.IndexOf('Assert-V2SqliteSidecars -DbPath $k')
Add-Res 'P25' ($iSc -gt $iW5h -and $iSc -lt $iOkM -and $fsc.Contains("'-journal', '-wal', '-shm'") -and $fsc.Contains('$hdr[18]') -and $fsc.Contains("-PathType Leaf")) 'W5: sidecar-и SQLite (-journal/-wal/-shm, режим журналу) перевіряються після SHA256 і до RESTORE-OK'
$res
$fail = @($res | Where-Object { $_ -match ' FAIL ' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match ' PASS ' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
