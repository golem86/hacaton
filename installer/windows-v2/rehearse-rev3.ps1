# Локальна репетиція (позитивний шлях) — кандидат REV3 + P1–P6. Безпечність: процеси зупиняються лише через власні handle (I0 у test-rev3-negative.ps1) на ПК №2 (без прав адміністратора; служби, ACL і Caddy не чіпаються).
param([Parameter(Mandatory)] [string]$Root, [Parameter(Mandatory)] [string]$Py, [Parameter(Mandatory)] [string]$DeployZip)
$T0 = $PSScriptRoot
. "$T0\V2-install-common.ps1"
$results = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $results.Add(('{0,-4} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
function Sd([string]$sddl) { $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($sddl); $x }
function Expect-Stop([scriptblock]$b) { try { & $b; $false } catch { "$($_.Exception.Message)".StartsWith('STOP:') } }

# R1 (I02): оцінка ACL предків і кореня V2 — SDDL у пам'яті
$cDefault = 'O:S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;BU)(A;OICIIO;SDGXGWGR;;;AU)(A;;0x4;;;AU)(A;OICIIO;GA;;;CO)'
$srvInheritedAU = 'O:BAD:AI(A;ID;FA;;;BA)(A;OICIID;FA;;;SY)(A;OICIID;0x1301bf;;;AU)(A;OICIID;0x1200a9;;;BU)'
$srvSafe = 'O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;BU)'
$srvUserOwner = 'O:S-1-5-21-1-2-3-1001D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'
$v2Safe = 'O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'
$v2NotProtected = 'O:BAD:AI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'
$v2Users = 'O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;BU)'
$cases = @(
  @('C:\ за замовчуванням (AU: лише створення папок; IO Modify)', $cDefault, 'ancestor', $false),
  @('C:\srv з успадкованим AU Modify', $srvInheritedAU, 'ancestor', $true),
  @('C:\srv лише адміністратори/SYSTEM, Users RX', $srvSafe, 'ancestor', $false),
  @('C:\srv власник — звичайний користувач', $srvUserOwner, 'ancestor', $true),
  @('корінь V2 захищений', $v2Safe, 'v2root', $false),
  @('корінь V2 без захисту від успадкування', $v2NotProtected, 'v2root', $true),
  @('корінь V2 з читанням Users', $v2Users, 'v2root', $false))
$bad = @(foreach ($c in $cases) { $r = @(Get-V2AclRisk -Acl (Sd $c[1]) -Kind $c[2]); if (($r.Count -gt 0) -ne $c[3]) { "$($c[0]): [$($r -join '; ')]" } })
Add-Res 'R1' ($bad.Count -eq 0) "ACL: сценаріїв $($cases.Count), розбіжностей $($bad.Count) $($bad -join ' | ')"

# R2 (I01): baseline V1 на ПК №2 відсутній → функція має дати STOP (fail-closed)
Add-Res 'R2' (Expect-Stop { Get-V1Baseline }) 'baseline без HacatonBackend/Caddy V1 → STOP'

# R3 (I05): HTTP-перевірка автоматична — неправильний очікуваний статус → STOP
Add-Res 'R3' (Expect-Stop { Assert-V2Http -Url 'http://127.0.0.1:9/' -Expected 200 }) 'Assert-V2Http: немає з''єднання/інший статус → STOP'

# R4: етап 2 — пакет (як у плані)
New-Item -ItemType Directory -Path $Root, "$Root\pkg", "$Root\app", "$Root\app\frontend", "$Root\data", "$Root\backups" | Out-Null
$Zip = $DeployZip
if ((Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne '62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559') { throw 'STOP: невірний SHA256 deployment ZIP' }
if ((Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower() -ne '62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559') { throw 'STOP: транспортний ZIP' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($Zip, "$Root\pkg")
foreach ($l in Get-Content "$Root\pkg\SHA256SUMS.txt") { $h, $n = $l -split '\s+', 2; if ((Get-FileHash "$Root\pkg\$n" -Algorithm SHA256).Hash.ToLower() -ne $h) { throw "STOP: $n" } }
[IO.Compression.ZipFile]::ExtractToDirectory("$Root\pkg\integrity-v2-dde86e6-backend-src.zip", "$Root\app")
$Backend = "$Root\app\integrity-v2-dde86e6\backend"; $DbTool = "$T0\v2_db_tool.py"
Add-Res 'R4' (@(Get-ChildItem $Backend -Recurse -File).Count -eq 52) 'пакет: суми, 52 файли коду'

# R5 (I05): репетиція 5а — try/finally, автоматичні HTTP-критерії, відбиток
$envBefore = @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(APP_ENV|INTEGRITY_|V2_|FRONTEND_|TRUSTED_)' } | ForEach-Object { "$($_.Name)=$($_.Value)" })
$reh = @(Invoke-V2Rehearsal -Py $Py -Backend $Backend -DbTool $DbTool -Port 8199)
$fp5a = (($reh | Where-Object { $_.StartsWith('FINGERPRINT ') }) -replace '^FINGERPRINT ', '')
$envAfter = @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(APP_ENV|INTEGRITY_|V2_|FRONTEND_|TRUSTED_)' } | ForEach-Object { "$($_.Name)=$($_.Value)" })
$tmpLeft = @(Get-ChildItem $env:TEMP -Directory -Filter 'v2-rehearsal-*' -ErrorAction SilentlyContinue).Count
$port = @(Get-NetTCPConnection -State Listen -LocalPort 8199 -ErrorAction SilentlyContinue).Count
$pyLeft = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match '8199' }).Count
Add-Res 'R5' ($fp5a -match '^[0-9a-f]{64}$' -and @($reh | Where-Object { $_.StartsWith('PASS') }).Count -eq 11 -and -not @(Compare-Object $envBefore $envAfter).Count -and $tmpLeft -eq 0 -and $port -eq 0 -and $pyLeft -eq 0) "репетиція 5а: $(@($reh | Where-Object { $_.StartsWith('PASS') }).Count) PASS; env відновлено; temp $tmpLeft; порт 8199 $port; процесів $pyLeft; відбиток $($fp5a.Substring(0,16))…"
$reh | ForEach-Object { "   $_" } | ForEach-Object { $results.Add($_) }

# R6 (I04, I06): ініціалізація нових БД — backup ДО --confirm-verified-backup; схема; маркер; відбиток = 5а; DEMO-умова
$D = "$Root\data"
$out6 = Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$D\integrity_v2.db"; V2_AUTH_DB = "$D\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
  if (@(Get-ChildItem -LiteralPath $D -Force).Count) { Stop-V2 'data\ не порожній' }
  Set-Content -LiteralPath "$D\CREATED-BY-V2-INSTALL.txt" -Value "created $(Get-Date -Format s) by app.seed (package dde86e6)" -Encoding UTF8
  $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.seed') -What 'seed'
  $v = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('verify', "$D\integrity_v2.db", '--expect-version', '2')
  $fp = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('fingerprint', "$D\integrity_v2.db"); if ($fp -ne $fp5a) { Stop-V2 'відбиток ≠ 5а' }
  $b1 = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$D\integrity_v2.db", "$Root\backups\integrity_v2-pre-migration.db", '--expect-version', '2')
  $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.migrations', '--apply', '--confirm-verified-backup') -What 'migrations'
  $sc = @(Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.migrations import check_schema; from app.database import engine; check_schema(engine); from app.v2_auth import check_auth_schema; check_auth_schema(); print(''SCHEMA OK'')') -What 'schema')[-1]
  $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.v2_auth import create_user; create_user(''Rehearsal Admin'', ''admin@example.test'', ''Rehearsal-Pass-123'', role=''admin''); print(''ADMIN'')') -What 'admin (репетиція замість getpass)'
  $syn = Assert-V2SyntheticDb -Py $Py -DbTool $DbTool -DataDir $D -ReferenceFingerprint $fp5a
  $b2 = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$D\v2_auth.db", "$Root\backups\v2_auth-final.db", '--expect-version', '1')
  $b3 = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$D\integrity_v2.db", "$Root\backups\integrity_v2-final.db", '--expect-version', '2')
  @($v, $b1, $sc, $syn, $b2, $b3)
}
$ok6 = ($out6[0] -like 'VERIFY OK*') -and ($out6[1] -like 'BACKUP OK*restore-test=ok*') -and ($out6[2] -eq 'SCHEMA OK') -and ($out6[3] -like 'PASS*') -and ($out6[4] -like 'BACKUP OK*') -and ($out6[5] -like 'BACKUP OK*')
Add-Res 'R6' $ok6 'нові БД: seed → verify v2 → відбиток = 5а → backup + тест відновлення → migrations --confirm-verified-backup → схема → DEMO-умова → фінальні копії'
$out6 | ForEach-Object { "   $_" } | ForEach-Object { $results.Add($_) }

# R7 (I06): DEMO заборонено для невідомої БД (інший відбиток) і без маркера
Add-Res 'R7a' (Expect-Stop { Assert-V2SyntheticDb -Py $Py -DbTool $DbTool -DataDir $D -ReferenceFingerprint ('0' * 64) }) 'відбиток ≠ еталону → STOP'
Remove-Item "$D\CREATED-BY-V2-INSTALL.txt"
Add-Res 'R7b' (Expect-Stop { Assert-V2SyntheticDb -Py $Py -DbTool $DbTool -DataDir $D -ReferenceFingerprint $fp5a }) 'без маркера свіжої БД → STOP'

# R8 (I03): секрети — підстановка без виводу, ZeroFreeBSTR у finally, жодних плейсхолдерів, XML валідний
$x = "$Root\backend-test.xml"; Copy-Item "$T0\integrity-v2-backend.xml.template" $x
$o8 = @(Set-V2Secrets -XmlPath $x -Rehearsal -SecretReader { param($n) ConvertTo-SecureString "rehearsal-$n<&>" -AsPlainText -Force })
[xml]$xx = Get-Content $x -Raw -Encoding UTF8
$envs = @{}; foreach ($e in $xx.service.env) { $envs[$e.name] = $e.value }
Add-Res 'R8' ($o8[-1] -like 'PASS*' -and -not (Select-String $x -Pattern '__V2_' -Quiet) -and $envs['V2_SMTP_PASSWORD'] -eq 'rehearsal-V2_SMTP_PASSWORD<&>' -and $envs['V2_SECRET_KEY'].Length -ge 64 -and $xx.service.startmode -eq 'Manual' -and $xx.service.serviceaccount.domain -eq 'NT SERVICE') 'секрети: XML валідний, спецсимволи екрановано, плейсхолдерів 0; Manual; NT SERVICE'
Add-Res 'R8b' (Expect-Stop { Set-V2Secrets -XmlPath $x -Rehearsal -SecretReader { param($n) New-Object Security.SecureString } }) 'порожній секрет → STOP'
Add-Res 'R8c' (Expect-Stop { Set-V2Secrets -XmlPath $x -SecretReader { param($n) ConvertTo-SecureString 'x' -AsPlainText -Force } }) 'XML поза C:\srv\integrity-v2\services → STOP'
Remove-Item $x

# R9 (B3 + етап 3): відновлення на синтетичних SQLite з R6 зі СПРАВЖНЬОЮ перевіркою схеми backend (check_schema / check_auth_schema)
# і строгим checker-ом v2_auth (A01–A13). Доказ зупинки — СПРАВЖНІЙ Job Object (експериментальний v2_job_launcher.py, Local\-ім'я,
# власник — поточний користувач, локальний режим сканування baseline); служби не створюються.
$savedRoot9 = $V2Root; $V2Root = $Root
$savedJob9 = $V2Services['integrity-v2-backend'].Job
$o9 = New-Object System.Collections.Generic.List[string]
$holder9 = $null
try {
  $base9py = @(Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', 'import sys; print(sys._base_executable)') -Utf8 -What 'base python')[-1]
  $V2JobTool.Py = $base9py; $V2JobTool.Script = "$T0\v2_job_launcher.py"
  $me9 = @(Invoke-V2JobTool -ArgList @('whoami'))[-1]
  # auditfix2: proof одноразовий (відкат інвалідує його і звільняє lease) → для кожного відкату — свіжий справжній job-proof із lease.
  # Локальна адаптація (лише тут, P22): scan у режимі baseline + виключення процесу утримання (без прав адміністратора).
  function New-R9Proof {
    $job = 'Local\v2-rehearsal-' + [guid]::NewGuid().ToString('N')
    $snap = "$Root\job-baseline-$([guid]::NewGuid().ToString('N').Substring(0, 8)).json"; $null = Invoke-V2JobTool -ArgList @('snapshot', '--out', $snap)
    $psi = New-Object Diagnostics.ProcessStartInfo $base9py
    $psi.Arguments = "-I -E -s `"$T0\v2_job_launcher.py`" run --job `"$job`" -- `"$Py`" -I -c `"import time; time.sleep(120)`""
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $l = [Diagnostics.Process]::Start($psi); $null = $l.Handle
    $pre = $null; foreach ($i in 1..50) { Start-Sleep -Milliseconds 200; $pre = Get-V2JobReport -JobName $job -OwnerSid $me9; if ($pre.found -and @($pre.pids).Count -ge 1) { break } }
    if (-not ($pre.found -and $pre.sd_ok -and $pre.limits_ok -and @($pre.pids).Count -ge 1)) { Stop-V2 "R9: job launcher-а не підтверджено: $(@($pre.problems) -join '; ')" }
    $tree = New-V2Tree -RootProcess $l
    $script:holder9 = Start-V2JobHolder -JobName $job
    Stop-V2Handle $l; if (-not (Wait-V2Handle $l 10000)) { Stop-V2 'R9: launcher не завершився' }   # «аварія» launcher-а: handle утримує installer
    $mid = Get-V2JobReport -JobName $job -OwnerSid $me9
    $null = Invoke-V2JobTool -ArgList @('terminate', '--job', $job, '--expect-owner', $me9)
    $script:V2JobLocalRehearsal = @{ Baseline = $snap; ExcludePid = @($script:holder9.Id); OwnerSid = $me9; ScopeRoot = @($PID) }   # лише процеси дерева репетиції
    $post = Get-V2JobReport -JobName $job -OwnerSid $me9 -Scan
    if ($post.verdict -ne 'PASS') { Stop-V2 "R9: доказ Job Object не отримано: $(@($post.problems) -join '; ')" }
    $null = Assert-V2TreeExited -Tree $tree
    $V2Services['integrity-v2-backend'].Job = $job
    $V2StopProof['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; Tree = $tree; Unresolved = 0; VerifiedUtc = [datetime]::UtcNow
                                                             Completeness = 'job'; JobVerified = $true; JobName = $job; JobActive = [int]$post.active; OwnerScanAlive = 0; Lease = $script:holder9 }
    [pscustomobject]@{ Job = $job; Mid = [int]$mid.active; Post = $post; Tree = $tree.Count }
  }
  function Get-R9LeaseClosed { -not $V2StopProof.ContainsKey('integrity-v2-backend') -and $script:holder9.HasExited }
  $pr9 = New-R9Proof
  Add-Res 'R9j' ($pr9.Mid -ge 1 -and [int]$pr9.Post.active -eq 0 -and @($pr9.Post.pids).Count -eq 0 -and $pr9.Post.verdict -eq 'PASS') "справжній Job Object: після аварії launcher-а процеси job живі ($($pr9.Mid)), бо handle утримує installer → terminate лише цього job → ActiveProcesses 0, PID-list порожній, сканування 0 → доказ рівня job із lease"
  $o9.Add("доказ: Job Object $($pr9.Job) (ActiveProcesses до terminate $($pr9.Mid), після 0); дерево launcher-а ($($pr9.Tree)) завершено; lease — процес утримання")
  $bk9 = @{ 'integrity_v2.db' = "$Root\backups\integrity_v2-final.db"; 'v2_auth.db' = "$Root\backups\v2_auth-final.db" }
  function New-R9Items { @(@{ Db = 'integrity_v2.db'; Backup = $bk9['integrity_v2.db']; Sha256 = (Get-FileHash -LiteralPath $bk9['integrity_v2.db'] -Algorithm SHA256).Hash.ToLower(); Version = 2 },
                           @{ Db = 'v2_auth.db'; Backup = $bk9['v2_auth.db']; Sha256 = (Get-FileHash -LiteralPath $bk9['v2_auth.db'] -Algorithm SHA256).Hash.ToLower(); Version = 1 }) }
  function New-R9Data([string]$Name) { $t9 = Join-Path $Root $Name; $null = New-Item -ItemType Directory -Path $t9; foreach ($f in 'integrity_v2.db', 'v2_auth.db') { Copy-Item -LiteralPath (Join-Path $D $f) -Destination $t9 }; Set-Content -LiteralPath (Join-Path $t9 'integrity_v2.db-wal') 'stale-wal'; $t9 }   # не $d: імена змінних PowerShell нечутливі до регістру ($D — data\)
  function Get-R9State([string]$s9) { (@(Get-ChildItem -LiteralPath $s9 -File | ForEach-Object Name | Sort-Object) -join ',') }
  # R9a: успіх — обидві БД відновлено, справжня перевірка схеми, .broken-* збережено, RESTORE-OK
  $d9a = New-R9Data 'data-r9a'
  $ra = @(Invoke-V2DbRestore -DataDir $d9a -Known @() -Py $Py -DbTool $DbTool -Items (New-R9Items))
  Add-Res 'R9w' ((@($ra | Where-Object { $_ -like 'PASS  W5:*' }).Count -eq 1) -and (@($ra | Where-Object { $_ -like 'PASS  W2/W3:*' }).Count -eq 1) -and (Get-R9LeaseClosed)) 'auditfix2: справжні W2/W3 і W5 (scan, FileShare.None, SHA256 відновлених БД) PASS; після відкату proof інвалідовано, процес утримання lease завершено'
  $sa = Get-R9State $d9a
  Add-Res 'R9a' ($ra -contains 'SCHEMA OK' -and $ra[-1] -like 'PASS*відновлення завершено*' -and $sa -match 'RESTORE-OK-' -and $sa -match 'integrity_v2\.db\.broken-' -and $sa -match 'integrity_v2\.db-wal\.broken-' -and $sa -match 'v2_auth\.db\.broken-' -and (@(Assert-V2NoRestoreBlock -DataDir $d9a))[-1] -like 'PASS*') 'B3: справжнє відновлення 2 БД → SCHEMA OK (check_schema + check_auth_schema для відновлених файлів) → RESTORE-OK; .broken-* збережено'
  $o9.Add("R9a: $($ra -join ' | ')")
  # R9b: примусова часткова помилка — копія integrity_v2 валідна для SQLite і v2_db_tool (integrity ok, user_version 2, таблиці
  #      seed є), але без решти таблиць V2 → обидві БД уже замінено, СПРАВЖНЯ check_schema падає → RESTORE-FAILED
  $bad9 = "$Root\backups\integrity_v2-noschema.db"
  $ddl9 = (('answers', 'components', 'cycles', 'objective_indicators', 'questions', 'recommendations', 'response_sets', 'units') | ForEach-Object { "c.execute('create table $_(x)'); " }) -join ''
  $null = Invoke-V2Native -Exe $Py -ArgList @('-c', "import sqlite3; c=sqlite3.connect(r'$bad9'); $ddl9 c.execute('pragma user_version=2'); c.commit(); c.close()") -What 'R9b: копія без повної схеми'
  $bk9['integrity_v2.db'] = $bad9
  $d9b = New-R9Data 'data-r9b'; $null = New-R9Proof
  $mb = $null; try { $null = Invoke-V2DbRestore -DataDir $d9b -Known @() -Py $Py -DbTool $DbTool -Items (New-R9Items) } catch { $mb = $_.Exception.Message }
  Add-Res 'R9l' (Get-R9LeaseClosed) 'auditfix2: невдалий відкат (R9b) → proof інвалідовано, процес утримання lease завершено'
  $sb = Get-R9State $d9b; $nb = $sb -split ','
  Add-Res 'R9b' ($mb -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*integrity_v2.db ←*v2_auth.db ←*' -and $sb -match 'RESTORE-FAILED-' -and $sb -notmatch 'RESTORE-(OK|IN-PROGRESS)' -and $sb -match 'integrity_v2\.db\.broken-' -and $sb -match 'v2_auth\.db\.broken-' -and $nb -contains 'integrity_v2.db' -and $nb -contains 'v2_auth.db' -and (Expect-Stop { Assert-V2NoRestoreBlock -DataDir $d9b }) -and (Expect-Stop { Invoke-V2DbRestore -DataDir $d9b -Known @() -Py $Py -DbTool $DbTool -Items (New-R9Items) })) 'B3: примусова часткова помилка — обидві БД замінено, справжня check_schema (немає таблиць V2) падає → RESTORE-FAILED; .broken-* збережено; старт і повторне відновлення заборонено'
  $o9.Add("R9b: $mb")
  # R9c: примусовий збій посередині — integrity_v2 відновлено, копіювання v2_auth падає (dst-файл уже існує як каталог)
  $bk9['integrity_v2.db'] = "$Root\backups\integrity_v2-final.db"
  $d9c = New-R9Data 'data-r9c'; $null = New-R9Proof
  $origTool9 = (Get-Item function:Invoke-V2DbTool).ScriptBlock
  Set-Item function:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) if ($ArgList[0] -eq 'backup' -and $ArgList[2] -like '*\v2_auth.db') { $null = New-Item -ItemType Directory -Path $ArgList[2] }; & $origTool9 -Py $Py -DbTool $DbTool -ArgList $ArgList }
  $mc = $null; try { $null = Invoke-V2DbRestore -DataDir $d9c -Known @() -Py $Py -DbTool $DbTool -Items (New-R9Items) } catch { $mc = $_.Exception.Message } finally { Set-Item function:Invoke-V2DbTool $origTool9 }
  $sc9 = Get-R9State $d9c
  Add-Res 'R9c' ($mc -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*v2_db_tool backup*' -and $mc -notlike '*v2_auth.db ←*' -and $sc9 -match 'RESTORE-FAILED-' -and $sc9 -match 'v2_auth\.db\.broken-' -and $sc9 -match 'integrity_v2\.db\.broken-' -and (Expect-Stop { Assert-V2NoRestoreBlock -DataDir $d9c })) 'B3: справжній збій копіювання другої БД після відновлення першої (частковий стан) → RESTORE-FAILED; .broken-* збережено; старт заборонено'
  $o9.Add("R9c: $mc")
  # R9d: неповна копія v2_auth.db, яку check_auth_schema backend пропустив би (лише user_version) → строгий checker STOP до мутації
  $bad9a = "$Root\backups\v2_auth-incomplete.db"
  $null = Invoke-V2Native -Exe $Py -ArgList @('-c', "import sqlite3; c=sqlite3.connect(r'$bad9a'); c.execute('create table t(x)'); c.execute('pragma user_version=1'); c.commit(); c.close()") -What 'R9d: неповна auth-копія'
  $bk9['v2_auth.db'] = $bad9a
  $d9d = New-R9Data 'data-r9d'; $s9d = Get-R9State $d9d; $null = New-R9Proof
  $md = $null; try { $null = Invoke-V2DbRestore -DataDir $d9d -Known @() -Py $Py -DbTool $DbTool -Items (New-R9Items) } catch { $md = $_.Exception.Message }
  Add-Res 'R9d' ($md -like 'STOP:*auth-schema: FAIL A05*' -and (Get-R9State $d9d) -eq $s9d) 'етап 1: неповна копія v2_auth.db (v1 без таблиць V2) → строгий checker STOP ДО мутації; RESTORE-OK неможливий'
  $o9.Add("R9d: $md")
  $bk9['v2_auth.db'] = "$Root\backups\v2_auth-final.db"
  # Спостереження (не тест кандидата; backend не змінюється): check_auth_schema перевіряє лише user_version v2_auth.db
  $t9a = "$Root\auth-probe.db"
  $null = Invoke-V2Native -Exe $Py -ArgList @('-c', "import sqlite3; c=sqlite3.connect(r'$t9a'); c.execute('create table t(x)'); c.execute('pragma user_version=1'); c.commit(); c.close()") -What 'R9 probe'
  $pa = @(Use-V2Env -Vars @{ V2_AUTH_DB = $t9a } -Body { Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.v2_auth import check_auth_schema; check_auth_schema(); print(''AUTH SCHEMA OK'')') -What 'R9 probe auth' })[-1]
  $o9.Add("СПОСТЕРЕЖЕННЯ: v2_auth.db без жодної таблиці V2, user_version=1 → check_auth_schema: $pa (перевіряється лише версія)")
} finally { if ($script:holder9 -and -not $script:holder9.HasExited) { try { Stop-V2JobHolder -Holder $script:holder9 } catch { } }; $V2Root = $savedRoot9; $V2StopProof.Clear(); $V2JobTool.Py = $null; $V2JobTool.Script = $null; $script:V2JobLocalRehearsal = $null; $V2Services['integrity-v2-backend'].Job = $savedJob9 }
$o9 | ForEach-Object { "   " + ($_ -replace "\r?\n", " | ") } | ForEach-Object { $results.Add($_) }

# R10 (CLEAN INSTALL): ініціалізація НОВИХ БД справжнім backend — Initialize-V2CleanDatabases → адміністратор → Complete-V2CleanDatabases
$o10 = New-Object System.Collections.Generic.List[string]
function New-R10Admin([string]$dd) {
  $null = Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$dd\integrity_v2.db"; V2_AUTH_DB = "$dd\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
    $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.v2_auth import create_user; create_user(''Rehearsal Admin'', ''admin@example.test'', ''Rehearsal-Pass-123'', role=''admin''); print(''ADMIN'')') -What 'admin (репетиція замість getpass)'
  }
}
$d10 = "$Root\ci-data"; $b10 = "$Root\ci-backups"; $null = New-Item -ItemType Directory -Path $d10, $b10
$ri = @(Initialize-V2CleanDatabases -Py $Py -Backend $Backend -DbTool $DbTool -DataDir $d10 -BackupDir $b10 -ReferenceFingerprint $fp5a)
New-R10Admin $d10
$rc = @(Complete-V2CleanDatabases -Py $Py -DbTool $DbTool -DataDir $d10 -BackupDir $b10 -ReferenceFingerprint $fp5a)
$st10 = @(Get-ChildItem -LiteralPath $d10 -File | ForEach-Object Name)
Add-Res 'R10a' (@($ri | Where-Object { $_ -like 'PASS  нова v2_auth.db: AUTH SCHEMA OK*' }).Count -eq 1 -and @($rc | Where-Object { $_ -like '*admin=1*фінальна копія: AUTH SCHEMA OK*' }).Count -eq 1 -and @($st10 | Where-Object { $_ -like 'CLEAN-INIT-OK-*' }).Count -eq 1 -and (Assert-V2DataReady -DataDir $d10) -like 'PASS*' -and @(Get-ChildItem $b10 -Filter '*-initial-*.db').Count -eq 2) 'Clean Install: справжні seed + migrations → строгий auth-schema нової і ФІНАЛЬНОЇ копії v2_auth → CLEAN-INIT-OK; старт дозволено'
$o10.Add("R10a: $(($ri + $rc) -join ' | ')")
$d10b = "$Root\ci-data-b"; $b10b = "$Root\ci-backups-b"; $null = New-Item -ItemType Directory -Path $d10b, $b10b
$null = Initialize-V2CleanDatabases -Py $Py -Backend $Backend -DbTool $DbTool -DataDir $d10b -BackupDir $b10b -ReferenceFingerprint $fp5a
New-R10Admin $d10b
$null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(''drop index idx_v2_attempts_user''); c.commit(); c.close()', "$d10b\v2_auth.db") -What 'R10b: пошкодження auth'
$mb10 = $null; try { $null = Complete-V2CleanDatabases -Py $Py -DbTool $DbTool -DataDir $d10b -BackupDir $b10b -ReferenceFingerprint $fp5a } catch { $mb10 = $_.Exception.Message }
Add-Res 'R10b' ($mb10 -like 'STOP:*CLEAN INIT НЕВДАЛИЙ*' -and @(Get-ChildItem $d10b -Filter 'CLEAN-INIT-FAILED-*').Count -eq 1 -and (Expect-Stop { Assert-V2DataReady -DataDir $d10b })) 'Clean Install: пошкоджена v2_auth після bootstrap → CLEAN-INIT-FAILED; старт backend заборонено; пошкоджена БД не використовується'
$o10.Add("R10b: $mb10")
$mc10 = $null; try { $null = Initialize-V2CleanDatabases -Py $Py -Backend $Backend -DbTool $DbTool -DataDir $d10 -BackupDir $b10 } catch { $mc10 = $_.Exception.Message }
Add-Res 'R10c' ($mc10 -like 'STOP:*лише на порожньому data*') 'Clean Install поверх наявних БД → STOP (наявні БД не використовуються)'
$o10 | ForEach-Object { "   " + ($_ -replace "\r?\n", " | ") } | ForEach-Object { $results.Add($_) }

$results
$fail = @($results | Where-Object { $_ -match '^\S+\s+FAIL ' }).Count
"Підсумок: $(@($results | Where-Object { $_ -match '^\S+\s+PASS ' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
