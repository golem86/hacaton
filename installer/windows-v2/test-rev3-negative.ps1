# Ізольовані негативні й контрольні тести адресних виправлень P1–P6 (+P7 native), дельти 1–5 і B1/B3 (19.11) — Windows PowerShell 5.1, ПК №2.
# H* — B1 (помилка handle нащадка); K* — B3 (валідація набору БД для відновлення).
# S* — етап 3: Stop-V2Service + Job Object (фейковий job); R*.* — етап 3: відкат (доказ рівня job, строга схема auth, часткові збої).
# R*.* тут — новий checklist R01–R14 наказу №5; не плутати з rehearse R1–R9 і R-04 deployment gate.
# W*/L* — auditfix2: виключення конкурентних writer (W1–W5) і життєвий цикл lease/proof (SQLITE_WRITER_EXCLUSION_DESIGN.md).
# SC* — auditfix3: sidecar-и SQLite (-journal/-wal/-shm) перед RESTORE-OK; OH* — власний процес утримання lease не є «процесом V2».
# CI* — CLEAN INSTALL: V1 не обов'язкова, артефакт інструментів, маркери ініціалізації БД, переривання; CI.late-* — CI-01 (пізній збій після CLEAN-INIT-OK).
# Позначення: P*/D* — частина A (усе фейкове); Q* — частина Q (лише власні дочірні процеси python і тимчасові файли).
# Q* — ЛОКАЛЬНІ тести цього скрипта; це НЕ B1-QA (прогін suite у Windows Sandbox), B1-QA — NOT RUN.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-rev3-negative.ps1 -Py <python.exe>
# Код завершення: 0 — усі PASS; 1 — є FAIL або зафіксовано спробу реального виклику.
#
# ІЗОЛЯЦІЯ (обов'язкова, перевіряється першою — I0):
#  * Частина A: усі OS-адаптери common (CIM, owner, слухачі, handle, Kill/Wait, env, ACL, служби, native) підмінено фейковою
#    таблицею процесів. Cmdlet-и Stop-Process, Get-Process, Get-CimInstance, Invoke-CimMethod, Get-NetTCPConnection,
#    Get-NetUDPEndpoint, Start-Process, Get-Service, Stop-Service, Start-Service, Restart-Service, Set-Acl перекрито функціями-
#    запобіжниками: будь-який реальний виклик кидає REAL-CALL-BLOCKED і рахується (I9 вимагає 0).
#  * Частина Q: повертається лише справжній Invoke-V2Native + Stop-V2Handle/Wait-V2Handle для ВЛАСНИХ дочірніх процесів
#    python, створених самим Invoke-V2Native (handle із Start). CIM/слухачі/служби лишаються фейковими.
#  * Жодного PID системних чи сторонніх процесів у тестах немає; kill можливий лише через handle, отриманий від Start.
param([Parameter(Mandatory)] [string] $Py)
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
. (Join-Path $PSScriptRoot 'V2-install-common.ps1')
$ErrorActionPreference = 'Stop'

$results = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $results.Add(('{0,-5} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
function Add-NotRun([string]$id, [string]$d) { $results.Add(('{0,-5} NOT RUN {1}' -f $id, $d)) }
function Get-StopMessage([scriptblock]$b) { try { $null = & $b; return $null } catch { return "$($_.Exception.Message)" } }
function Test-Stop([scriptblock]$b, [string]$like = '*') { $m = Get-StopMessage $b; return ($null -ne $m -and $m.StartsWith('STOP:') -and $m -like $like) }

# ---------------------------------------------------------------- запобіжники реальних викликів
$global:V2TestRealCalls = New-Object System.Collections.Generic.List[string]
$guarded = 'Stop-Process', 'Get-Process', 'Get-CimInstance', 'Invoke-CimMethod', 'Get-NetTCPConnection', 'Get-NetUDPEndpoint',
           'Start-Process', 'Get-Service', 'Stop-Service', 'Start-Service', 'Restart-Service', 'Set-Acl'
foreach ($n in $guarded) { Set-Item -Path "function:global:$n" -Value ([scriptblock]::Create("`$global:V2TestRealCalls.Add('$n'); throw 'REAL-CALL-BLOCKED: $n'")) }

# ---------------------------------------------------------------- фейкова таблиця процесів, служб, слухачів, ACL, env
$T0 = [datetime]::new(2026, 11, 19, 8, 0, 0, [DateTimeKind]::Utc)
function Reset-Fake {
  $global:Fake = @{ Procs = @{}; Kills = (New-Object System.Collections.Generic.List[int]); Listeners = @(); Services = @{}; Native = (New-Object System.Collections.Generic.List[string])
                    Acls = @{}; Env = @{}; EnvFail = @(); Http = 0; NativeHook = $null; Job = $null; JobCalls = (New-Object System.Collections.Generic.List[string]); Seq = (New-Object System.Collections.Generic.List[string]); StartModeFail = $null; Udp = @(); Host = $null }
}
function New-FakeProc([int]$P, [int]$Parent, [int]$SecondsAfter, [string]$Exe = 'C:\py\python.exe', [string]$Owner = 'PC\tester', [int]$Rc = 0, [string]$Cmd = '') {
  $o = [pscustomobject]@{ ProcessId = $P; ParentProcessId = $Parent; CreationDate = $T0.AddSeconds($SecondsAfter); ExecutablePath = $Exe; CommandLine = $Cmd
                          Name = [IO.Path]::GetFileName($Exe); Owner = $Owner; OwnerRc = $Rc; Exited = $false; KillThrows = $false; IgnoreKill = $false; OpenThrows = $false }
  $global:Fake.Procs[$P] = $o; $o
}
function New-FakeHandle([int]$P) { $o = $global:Fake.Procs[$P]; [pscustomobject]@{ Id = $P; FakeStart = $o.CreationDate; Proc = $o } }
function Add-FakeListener([int]$Port, [int]$Owner, [string]$Addr = '127.0.0.1') { $global:Fake.Listeners += , ([pscustomobject]@{ LocalAddress = $Addr; LocalPort = $Port; OwningProcess = $Owner }) }

$orig = @{}
$adapters = 'Get-V2CimProcess', 'Get-V2CimProcessList', 'Get-V2CimOwner', 'Get-V2Listeners', 'Open-V2ProcessHandle', 'Get-V2HandleStartTicks',
            'Test-V2HandleExited', 'Stop-V2Handle', 'Wait-V2Handle', 'Get-V2EnvVar', 'Set-V2EnvVar', 'Get-V2Acl', 'Get-V2Service', 'Invoke-V2Native', 'Get-V2HttpStatus',
            'Invoke-V2JobTool', 'Start-V2JobHolder', 'Stop-V2JobHolder', 'Set-V2ServiceStartMode', 'Get-V2ServiceList', 'Get-V2UdpEndpoints', 'Get-V2HostInfo'
foreach ($n in $adapters) { $orig[$n] = (Get-Item "function:$n").ScriptBlock }

function Get-V2CimProcess([int]$Id) { $p = $global:Fake.Procs[$Id]; if ($p -and -not $p.Exited) { $p } else { $null } }
function Get-V2CimProcessList { @($global:Fake.Procs.Values | Where-Object { -not $_.Exited }) }
function Get-V2CimOwner($c) { $d, $u = $c.Owner -split '\\', 2; [pscustomobject]@{ ReturnValue = $c.OwnerRc; Domain = $d; User = $u } }
function Get-V2Listeners([int[]]$Ports) { @($global:Fake.Listeners | Where-Object { $Ports -contains $_.LocalPort }) }
function Get-V2UdpEndpoints([int[]]$Ports) { @($global:Fake.Udp | Where-Object { $Ports -contains $_.LocalPort }) }
function Get-V2HostInfo { if (-not $global:Fake.Host) { throw 'немає фейкового хоста' }; $global:Fake.Host }
function Open-V2ProcessHandle([int]$Id) { $p = $global:Fake.Procs[$Id]; if (-not $p -or $p.Exited) { throw [ArgumentException]'process gone' }; if ($p.OpenThrows) { throw 'Access is denied (тест)' }; New-FakeHandle $Id }
function Get-V2HandleStartTicks($h) { ([datetime]$h.FakeStart).ToUniversalTime().Ticks }
function Test-V2HandleExited($h) { [bool]$h.Proc.Exited }
function Stop-V2Handle($h) { $global:Fake.Kills.Add([int]$h.Id); if ($h.Proc.KillThrows) { throw 'Access is denied' }; if (-not $h.Proc.IgnoreKill) { $h.Proc.Exited = $true } }
function Wait-V2Handle($h, [int]$Ms) { [bool]$h.Proc.Exited }
function Get-V2EnvVar([string]$Name) { if ($global:Fake.Env.ContainsKey($Name)) { $global:Fake.Env[$Name] } else { $null } }
function Set-V2EnvVar([string]$Name, $Value) { if ($global:Fake.EnvFail -contains $Name -and $null -eq $Value) { throw "env $Name read-only" }; if ($null -eq $Value -or "$Value" -eq '') { $global:Fake.Env.Remove($Name) } else { $global:Fake.Env[$Name] = "$Value" } }
function Get-V2Acl([string]$Path) { $s = $global:Fake.Acls[$Path]; if (-not $s) { throw "немає фейкового ACL для $Path" }; $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($s); $x }
function Get-V2Service([string]$Name) { $global:Fake.Services[$Name] }
function Get-V2ServiceList { @($global:Fake.Services.Values) }
function Invoke-V2Native { param([string]$Exe, [string[]]$ArgList = @(), [string]$What = '', [int[]]$OkCodes = @(0), [string]$WorkingDirectory, [switch]$Utf8, [int]$TimeoutSec = 900)
  $global:Fake.Native.Add("$([IO.Path]::GetFileName($Exe)) $($ArgList -join ' ')"); if ($global:Fake.NativeHook) { & $global:Fake.NativeHook $Exe $ArgList } }
function Get-V2HttpStatus { param([string]$Url, [hashtable]$Headers = @{}, [string]$Method = 'GET') $global:Fake.Http++; 200 }
function Invoke-V2JobTool {
  param([string[]]$ArgList)
  $global:Fake.JobCalls.Add(($ArgList -join ' ')); $global:Fake.Seq.Add('job ' + ($ArgList -join ' ')); $J = $global:Fake.Job
  if (-not $J) { throw 'немає фейкового job' }
  if ($ArgList[0] -eq 'terminate') { if ($J.TerminateWorks) { foreach ($q in $J.Pids) { if ($global:Fake.Procs[[int]$q]) { $global:Fake.Procs[[int]$q].Exited = $true } }; $J.Active = 0; $J.Pids = @() }; return 'TERMINATE OK' }
  $pr = New-Object System.Collections.Generic.List[string]
  if (-not $J.Found) { $pr.Add('job не знайдено') } else {
    if (-not $J.SdOk) { $pr.Add('DACL job ≠ очікуваному') }; if (-not $J.LimitsOk) { $pr.Add('ліміти job 0x2C00 ≠ 0x2400') }
    if ($J.Active -or @($J.Pids).Count) { $pr.Add("у job живі процеси: ActiveProcesses=$($J.Active), PID $(@($J.Pids) -join ',')") } }
  $scan = $ArgList -contains '--scan-sid'
  if ($scan -and $null -ne $J['AliveFor']) { if ($J.AliveFor -gt 0) { $J.AliveFor--; if (-not @($J.Alive).Count) { $J.Alive = $J.AliveSaved } } else { if (@($J.Alive).Count) { $J.AliveSaved = $J.Alive }; $J.Alive = @() } }
  if ($scan) { if (@($J.Alive).Count) { $pr.Add("живі процеси власника: $(@($J.Alive | ForEach-Object { $_.pid }) -join ',')") }; if (@($J.Unknown).Count) { $pr.Add("процеси з невизначеним власником: $(@($J.Unknown | ForEach-Object { $_.pid }) -join ',')") } }
  else { $pr.Add("сканування за власником не виконано (--scan-sid обов'язковий для доказу)") }
  ConvertTo-Json -Compress -Depth 4 -InputObject ([ordered]@{ job = $ArgList[2]; found = [bool]$J.Found; sd_ok = [bool]($J.Found -and $J.SdOk); limits_ok = [bool]($J.Found -and $J.LimitsOk)
    limits = '0x2400'; active = [int]$J.Active; pids = @($J.Pids); problems = @($pr); verdict = $(if ($pr.Count) { 'BLOCKED' } else { 'PASS' }); scan = @{ alive = @($J.Alive); unknown = @($J.Unknown) } })
}
function Start-V2JobHolder { param([string]$JobName) $global:Fake.JobCalls.Add("hold $JobName"); $global:Fake.Seq.Add('hold'); if ($global:Fake.Job -and $global:Fake.Job.HoldFails) { Stop-V2 "Job Object: утримання handle '$JobName' неможливе (тест)" }; 'HOLDER' }
function Stop-V2JobHolder { param($Holder) $global:Fake.JobCalls.Add('release'); $global:Fake.Seq.Add('release') }
function Set-V2ServiceStartMode { param([string]$Name, [string]$Mode) $global:Fake.Seq.Add("startmode $Mode")
  if ($global:Fake.StartModeFail -eq $Mode) { Stop-V2 "start type $Name не підтверджено (тест)" }
  $sv = $global:Fake.Services[$Name]; if (-not $sv) { Stop-V2 "служби $Name немає (тест)" }; $sv.StartMode = $Mode }
Reset-Fake

$tmp = Join-Path $env:TEMP ('v2-p1p6-tests-' + [guid]::NewGuid().ToString('N')); $null = New-Item -ItemType Directory $tmp
$me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$tiSid = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
try {
  # ================================================================ I0: перевірка ізоляції ДО будь-яких тестів
  $badGuard = @($guarded | Where-Object { $null -eq (Get-Command $_ -CommandType Function -ErrorAction SilentlyContinue) })
  $notMocked = @($adapters | Where-Object { (Get-Item "function:$_").ScriptBlock.File -ne $PSCommandPath })
  $gt = $false; try { Stop-Process -Id 2147483646 } catch { $gt = "$($_.Exception.Message)" -like 'REAL-CALL-BLOCKED*' }
  $global:V2TestRealCalls.Clear()
  $commonSrc = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'V2-install-common.ps1'))
  $rawOutside = @([regex]::Matches($commonSrc, '(?m)^(?!function (Open-V2ProcessHandle|Stop-V2Handle|Wait-V2Handle)).*(\.Kill\(\)|GetProcessById|\.WaitForExit\(|Stop-Process)') | ForEach-Object { $_.Value.Trim() } | Where-Object { -not $_.StartsWith('#') })
  Add-Res 'I0' ($badGuard.Count -eq 0 -and $notMocked.Count -eq 0 -and $gt -and $rawOutside.Count -eq 0) "ізоляція: запобіжників $($guarded.Count) (не перекрито: $($badGuard -join ',')); адаптерів підмінено $($adapters.Count - $notMocked.Count)/$($adapters.Count); виклик запобіжника → REAL-CALL-BLOCKED; прямих Kill/GetProcessById/WaitForExit/Stop-Process у common поза адаптером: $($rawOutside.Count)"
  if ($badGuard.Count -or $notMocked.Count -or -not $gt -or $rawOutside.Count) { throw 'ІЗОЛЯЦІЯ НЕ ПІДТВЕРДЖЕНА — тести не виконуються' }

  # ================================================================ P1 — ідентичність і слухач
  Reset-Fake
  $null = New-FakeProc 100 1 0; $null = New-FakeProc 101 100 1; Add-FakeListener 8199 101
  $tr = New-V2Tree (New-FakeHandle 100); $r = @(Wait-V2Listener -Port 8199 -Tree $tr -Addresses '127.0.0.1')
  Add-Res 'P1a' ($r[-1] -like 'PASS*' -and (@($tr | ForEach-Object Pid) -join ',') -eq '100,101' -and $tr[1].Owner -eq 'PC\tester' -and $tr[1].StartUtcTicks -eq $T0.AddSeconds(1).Ticks) 'власне дерево (launcher → дочірній python) слухає порт → PASS; запис: Pid, StartUtcTicks, Exe, Owner'
  Reset-Fake; $null = New-FakeProc 100 1 0; $null = New-FakeProc 900 1 0 'C:\other\svc.exe' 'PC\someone'; Add-FakeListener 8199 900
  $tr = New-V2Tree (New-FakeHandle 100)
  Add-Res 'P1b' (Test-Stop { Wait-V2Listener -Port 8199 -Tree $tr -Seconds 1 } '*чужий listener*') 'чужий listener → STOP до HTTP'
  Reset-Fake; $null = New-FakeProc 100 1 0; $null = New-FakeProc 101 100 1; Add-FakeListener 8199 101
  $tr = New-V2Tree (New-FakeHandle 100); $global:Fake.Procs[101].Exited = $true; $null = New-FakeProc 101 1 30 'C:\other\x.exe' 'PC\someone'
  Add-Res 'P1c' (Test-Stop { Assert-V2ListenerInTree -Port 8199 -Tree $tr } '*PID 101*') 'PID reuse: слухач із тим самим PID, але іншим процесом → STOP'
  Reset-Fake; $null = New-FakeProc 100 1 0; $null = New-FakeProc 101 100 1; Add-FakeListener 8199 101
  $tr = New-V2Tree (New-FakeHandle 100); $global:Fake.Procs[101].ExecutablePath = 'C:\evil\python.exe'
  Add-Res 'P1d' (Test-Stop { Assert-V2ListenerInTree -Port 8199 -Tree $tr } '*ідентичність змінилась*') 'зміна identity (exe) → STOP'
  Reset-Fake; $null = New-FakeProc 100 1 0; $null = New-FakeProc 101 100 1 'C:\py\python.exe' 'PC\tester' 2
  Add-Res 'P1e' (Test-Stop { $null = New-V2Tree (New-FakeHandle 100) } '*GetOwner*ReturnValue 2*') 'GetOwner.ReturnValue ≠ 0 у нащадка → STOP (невідома ідентичність)'
  Reset-Fake; $null = New-FakeProc 100 1 10; $null = New-FakeProc 101 100 2; Add-FakeListener 8199 101
  $tr = New-V2Tree (New-FakeHandle 100)
  Add-Res 'P1f' ($tr.Count -eq 1 -and (Test-Stop { Assert-V2ListenerInTree -Port 8199 -Tree $tr } '*чужий*')) '«нащадок», старший за батька (PID reuse батька), не приймається; його слухач → STOP'
  Reset-Fake; $null = New-FakeProc 100 1 0; $h = New-FakeHandle 100; $h.FakeStart = $T0.AddSeconds(-5)
  Add-Res 'P1g' (Test-Stop { $null = New-V2Identity -Process $h } '*handle ≠ CIM*') 'час створення handle ≠ CIM → STOP (збіг лише PID не приймається)'
  Reset-Fake; $null = New-FakeProc 100 1 0; $h = New-FakeHandle 100; $global:Fake.Procs.Remove(100)
  Add-Res 'P1h' (Test-Stop { $null = New-V2Identity -Process $h } '*невідома*') 'процесу немає в CIM → STOP'
  $reh = (Get-Item function:Invoke-V2Rehearsal).ScriptBlock.ToString()
  $iL = $reh.IndexOf('Wait-V2Listener -Port'); $iH = $reh.IndexOf('Wait-V2Http')
  Add-Res 'P1i' ($iL -gt 0 -and $iH -gt $iL) 'Invoke-V2Rehearsal: перевірка слухача (Wait-V2Listener) стоїть ДО першого Wait-V2Http'
  Reset-Fake; $null = New-FakeProc 100 1 0; $null = New-FakeProc 900 1 0 'C:\other\svc.exe' 'PC\someone'
  $m = Get-StopMessage { Invoke-V2Rehearsal -Py $Py -Backend $tmp -DbTool 'x' -PreSteps { } -Launcher { param($list) $list.Add((New-FakeHandle 100)); Add-FakeListener 8199 900 } }
  Add-Res 'P1j' ($m -like 'STOP:*чужий listener*' -and $global:Fake.Http -eq 0 -and (@($global:Fake.Kills) -join ',') -eq '100' -and -not $global:Fake.Procs[900].Exited) 'репетиція: чужий слухач → STOP; HTTP-запитів 0; зупинено лише власний PID 100 через handle; чужий процес не зачеплено'

  # ================================================================ P2 — зупинка й очищення
  Reset-Fake; $null = New-FakeProc 100 1 0; $null = New-FakeProc 101 100 1
  $tr = New-V2Tree (New-FakeHandle 100); $pr = @(Stop-V2ProcessTree -Tree $tr)
  Add-Res 'P2a' ($pr.Count -eq 0 -and (@($global:Fake.Kills) -join ',') -eq '101,100') 'зупинка дерева: спершу нащадок, потім корінь; лише через handle; проблем 0'
  Reset-Fake; $null = New-FakeProc 100 1 0; $tr = New-V2Tree (New-FakeHandle 100); $global:Fake.Procs[100].Exited = $true; $null = New-FakeProc 100 1 50 'C:\other\x.exe' 'PC\someone'
  $pr = @(Stop-V2ProcessTree -Tree $tr)
  Add-Res 'P2b' ($pr.Count -eq 0 -and $global:Fake.Kills.Count -eq 0 -and -not $global:Fake.Procs[100].Exited) 'PID reuse: власний процес завершився сам, PID зайняв чужий → Kill не викликається, чужий процес живий'
  Reset-Fake; $null = New-FakeProc 100 1 0; $tr = New-V2Tree (New-FakeHandle 100); $global:Fake.Procs[100].KillThrows = $true
  $pr = @(Stop-V2ProcessTree -Tree $tr)
  Add-Res 'P2c' ($pr.Count -ge 1 -and ($pr -join ';') -match 'Kill: Access is denied') 'помилка Kill при живому процесі → проблема повертається'
  Reset-Fake; $null = New-FakeProc 100 1 0; $tr = New-V2Tree (New-FakeHandle 100); $global:Fake.Procs[100].IgnoreKill = $true
  $pr = @(Stop-V2ProcessTree -Tree $tr)
  Add-Res 'P2d' (($pr -join ';') -match 'не завершився') 'процес не завершився після Kill → проблема'
  $td = Join-Path $tmp 'keep'; $null = New-Item -ItemType Directory $td; Set-Content (Join-Path $td 'x.db') 'db'
  Reset-Fake; $null = New-FakeProc 100 1 0; $tr = New-V2Tree (New-FakeHandle 100); $global:Fake.Procs[100].IgnoreKill = $true
  $cl = @(Invoke-V2Cleanup -Tree $tr -TempDir $td -Port 8199)
  Add-Res 'P2e' (($cl -join ';') -match 'ЗБЕРЕЖЕНО' -and (Test-Path (Join-Path $td 'x.db'))) 'вихід дерева не доведено → тимчасовий каталог із БД зберігається, проблема повертається'
  Reset-Fake; $lockDir = Join-Path $tmp 'locked'; $null = New-Item -ItemType Directory $lockDir; $lf = [IO.File]::Open((Join-Path $lockDir 'x'), 'Create', 'ReadWrite', 'None')
  try { $cl = @(Invoke-V2Cleanup -TempDir $lockDir -Port 8199) } finally { $lf.Dispose() }
  Add-Res 'P2f' (($cl -join ';') -match 'тимчасовий каталог') 'заблокований тимчасовий каталог → проблема (не приховується)'
  Reset-Fake; Add-FakeListener 8199 777; $cl = @(Invoke-V2Cleanup -TempDir (Join-Path $tmp 'none') -Port 8199)
  Add-Res 'P2g' (($cl -join ';') -match 'досі слухається') 'порт досі слухається → проблема'
  Reset-Fake; $global:Fake.Env['APP_ENV'] = 'dev'; $global:Fake.EnvFail = @('V2_TEST_RO')
  $m = Get-StopMessage { Use-V2Env -Vars @{ APP_ENV = 'release'; V2_TEST_RO = 'x' } -Body { 'ok' } }
  Add-Res 'P2h' ($m -like 'STOP:*відновлення env*V2_TEST_RO*' -and $global:Fake.Env['APP_ENV'] -eq 'dev') 'помилка відновлення env → STOP; інші змінні відновлено'
  Reset-Fake; $global:Fake.EnvFail = @('V2_TEST_RO')
  $m = Get-StopMessage { Use-V2Env -Vars @{ V2_TEST_RO = 'x' } -Body { Stop-V2 'помилка тіла' } }
  Add-Res 'P2i' ($m -like 'STOP:*помилка тіла*ВІДНОВЛЕННЯ ENV*') 'помилка тіла + помилка відновлення env → обидві в STOP'
  Reset-Fake; $null = New-FakeProc 100 1 0
  $m = Get-StopMessage { Invoke-V2Rehearsal -Py $Py -Backend $tmp -DbTool 'x' -PreSteps { } -Launcher { param($list) $list.Add((New-FakeHandle 100)); throw 'збій одразу після Start' } }
  Add-Res 'P2j' ($m -like '*збій одразу після Start*' -and (@($global:Fake.Kills) -join ',') -eq '100' -and $global:Fake.Procs[100].Exited) 'виняток одразу після Start (у REV3 — до присвоєння $proc) → власний процес зупинено через збережений handle'
  Reset-Fake; $null = New-FakeProc 100 1 0; $global:Fake.Procs[100].IgnoreKill = $true
  $before = @(Get-ChildItem $env:TEMP -Directory -Filter 'v2-rehearsal-*').Count
  $m = Get-StopMessage { Invoke-V2Rehearsal -Py $Py -Backend $tmp -DbTool 'x' -PreSteps { } -Launcher { param($list) $list.Add((New-FakeHandle 100)); throw 'збій' } }
  $kept = @(Get-ChildItem $env:TEMP -Directory -Filter 'v2-rehearsal-*')
  Add-Res 'P2k' ($m -like '*ОЧИЩЕННЯ*ЗБЕРЕЖЕНО*' -and $kept.Count -eq $before + 1) 'процес не завершився → STOP з ОЧИЩЕННЯ; тимчасовий каталог репетиції збережено (не PASS)'
  foreach ($k in $kept) { if ($k.CreationTime -gt (Get-Date).AddMinutes(-5)) { Remove-Item -LiteralPath $k.FullName -Recurse -Force } }
  Reset-Fake; $null = New-FakeProc 100 1 0; $h = New-FakeHandle 100; $h.FakeStart = $T0.AddSeconds(-9)
  $m = Get-StopMessage { Invoke-V2Rehearsal -Py $Py -Backend $tmp -DbTool 'x' -PreSteps { } -Launcher { param($list) $list.Add($h) } }
  Add-Res 'P2l' ($m -like 'STOP:*handle ≠ CIM*' -and (@($global:Fake.Kills) -join ',') -eq '100') 'невідома ідентичність запущеного процесу → STOP; зупинка лише через його handle'

  # ================================================================ P3 — служби: власники, автозупинка, stop-and-verify
  $svcN = 'integrity-v2-backend'; $acct = 'NT SERVICE\integrity-v2-backend'; $svcExe = $V2Services[$svcN].Exe
  function Set-FakeSvc([string]$State, [int]$ProcId) { $global:Fake.Services[$svcN] = [pscustomobject]@{ Name = $svcN; State = $State; StartMode = 'Manual'; StartName = $acct; PathName = "`"$svcExe`""; ProcessId = $ProcId } }
  $idDir = Join-Path $tmp 'ids'
  Reset-Fake; Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe 'NT SERVICE\other'
  Add-Res 'P3a' (Test-Stop { Assert-V2ServiceRunning -Name $svcN -Addresses '127.0.0.1' -IdentityDir $idDir } '*власник NT SERVICE\other*') 'власник wrapper ≠ акаунту служби → STOP'
  Reset-Fake; Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' 'NT AUTHORITY\SYSTEM'; Add-FakeListener 8100 501
  Add-Res 'P3b' (Test-Stop { Assert-V2ServiceRunning -Name $svcN -Addresses '127.0.0.1' -IdentityDir $idDir } '*PID 501*SYSTEM*') 'власник нащадка (python) ≠ акаунту служби → STOP'
  Reset-Fake; Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct 8
  Add-Res 'P3c' (Test-Stop { Assert-V2ServiceRunning -Name $svcN -Addresses '127.0.0.1' -IdentityDir $idDir } '*ReturnValue 8*') 'GetOwner.ReturnValue ≠ 0 у нащадка → STOP'
  Reset-Fake; $V2Identity.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct; Add-FakeListener 8100 501
  $r = @(Assert-V2ServiceRunning -Name $svcN -Addresses '127.0.0.1' -IdentityDir $idDir)
  Add-Res 'P3d' ($r[-1] -like 'PASS*' -and $V2Identity[$svcN].Count -eq 2 -and (Test-Path (Join-Path $idDir "$svcN.json"))) 'wrapper і нащадок — акаунт служби, слухач у дереві → PASS; ідентичності збережено (пам''ять + файл)'
  $script:stopped = 0; $script:started = 0
  $m = Get-StopMessage { Invoke-V2ServiceStart -Name $svcN -PreCheck { param($n) } -Starter { param($n) $script:started++; Set-FakeSvc Running 500; throw 'sc start: частковий старт' } -Stopper { param($n) $script:stopped++; 'stopped' } -Checks { 'PASS' } }
  Add-Res 'P3e' ($m -like 'STOP:*частковий старт*автоматично зупинено*' -and $script:stopped -eq 1) 'Starter частково запустив службу й кинув виняток → stop-and-verify викликано'
  $script:stopped = 0; $script:started = 0
  $m = Get-StopMessage { Invoke-V2ServiceStart -Name $svcN -PreCheck { param($n) Stop-V2 'StartName = LocalSystem' } -Starter { param($n) $script:started++ } -Stopper { param($n) $script:stopped++ } -Checks { 'PASS' } }
  Add-Res 'P3f' ($m -like 'STOP:*LocalSystem*' -and $script:started -eq 0 -and $script:stopped -eq 0) 'відмова до старту → Starter і Stopper не викликаються'
  $m = Get-StopMessage { Invoke-V2ServiceStart -Name $svcN -PreCheck { param($n) } -Starter { param($n) } -Stopper { param($n) Stop-V2 'CRITICAL BLOCKED — дочірній живий' } -Checks { Stop-V2 'власник' } }
  Add-Res 'P3g' ($m -like 'STOP:*АВТОЗУПИНКА*НЕ ПІДТВЕРДЖЕНА*CRITICAL BLOCKED*') 'автозупинка не підтверджена → явний STOP із CRITICAL BLOCKED'
  Reset-Fake; $V2Identity.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $V2Identity[$svcN] = New-V2Tree (New-FakeHandle 500)
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true } }
  $m = Get-StopMessage { Stop-V2Service -Name $svcN }
  Add-Res 'P3h' ($m -like 'STOP:*CRITICAL BLOCKED*501*досі працює*' -and $global:Fake.Kills.Count -eq 0) 'після sc stop нащадок живий → CRITICAL BLOCKED; нічого не вбивається «про всяк випадок»'
  Reset-Fake; $V2Identity.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $V2Identity[$svcN] = New-V2Tree (New-FakeHandle 500)
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; Add-FakeListener 8100 600 } }
  Add-Res 'P3i' (Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*порт 8100*') 'після зупинки порт 8100 досі слухається → CRITICAL BLOCKED'
  Reset-Fake; $V2Identity.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct; $V2Identity[$svcN] = New-V2Tree (New-FakeHandle 500)
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true } }
  $r = @(Stop-V2Service -Name $svcN)
  Add-Res 'P3j' ($r[-1] -like 'PASS*дерево (2) завершилось*' -and ($global:Fake.Native -join ';') -eq 'sc.exe stop integrity-v2-backend') 'усі збережені процеси завершились, порт вільний → PASS; виконано лише sc stop цієї V2-служби'


  # ================================================================ ДЕЛЬТА 2 — Stop-V2Service: актуальне дерево до і після sc stop (фейкові процеси)
  $svcN = 'integrity-v2-backend'; $acct = 'NT SERVICE\integrity-v2-backend'; $svcExe = $V2Services[$svcN].Exe
  function Set-FakeSvc([string]$State, [int]$ProcId) { $global:Fake.Services[$svcN] = [pscustomobject]@{ Name = $svcN; State = $State; StartMode = 'Manual'; StartName = $acct; PathName = "`"$svcExe`""; ProcessId = $ProcId } }
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $V2Identity[$svcN] = New-V2Tree (New-FakeHandle 500)
  $null = New-FakeProc 502 501 5 'C:\py\python.exe' $acct                         # пізній нащадок: з'явився після старту
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true; $global:Fake.Procs[502].Exited = $true } }
  $r = @(Stop-V2Service -Name $svcN)
  Add-Res 'D2a' ($r[-1] -like 'PASS*дерево (3) завершилось*' -and $V2StopProof[$svcN].Tree.Count -eq 3) 'нащадок, що з''явився після старту, включається в актуальне дерево перед sc stop (контроль: завершився → PASS)'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $V2Identity[$svcN] = New-V2Tree (New-FakeHandle 500)
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true; $null = New-FakeProc 503 501 9 'C:\py\python.exe' $acct } }
  $m = Get-StopMessage { Stop-V2Service -Name $svcN }
  Add-Res 'D2b' ($m -like 'STOP:*CRITICAL BLOCKED*пізні нащадки живі: 503*' -and -not $V2StopProof.ContainsKey($svcN)) 'осиротілий пізній нащадок (батько вже завершився) живий після stop → CRITICAL BLOCKED; доказу зупинки немає'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' 'NT AUTHORITY\SYSTEM'
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true } }
  $m = Get-StopMessage { Stop-V2Service -Name $svcN }
  Add-Res 'D2c' ($m -like 'STOP:*CRITICAL BLOCKED*PID 501*SYSTEM*' -and ($global:Fake.Native -join ';') -eq 'sc.exe stop integrity-v2-backend') 'власник нащадка ≠ акаунту (перед stop) → BLOCKED, а не PASS; sc stop лише цієї V2-служби все одно виконано'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $V2Identity[$svcN] = New-V2Tree (New-FakeHandle 500)
  $global:Fake.Procs[500].Exited = $true; $null = New-FakeProc 510 1 20 $svcExe $acct; Set-FakeSvc Running 510
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[510].Exited = $true } }
  Add-Res 'D2d' (Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*корінь служби змінився*') 'корінь служби змінився з моменту старту → BLOCKED'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 520
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0 } }
  Add-Res 'D2e' (Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*актуальне дерево не встановлено*') 'handle кореня служби не відкривається (процесу немає) → BLOCKED'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct 5
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true } }
  Add-Res 'D2f' (Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*') 'GetOwner.ReturnValue ≠ 0 у нащадка під час встановлення актуального дерева → BLOCKED'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true } }
  $r = @(Stop-V2Service -Name $svcN)
  Add-Res 'D2g' ($r[-1] -like 'PASS*дерево (2) завершилось, пізніх нащадків 0*' -and $V2StopProof.ContainsKey($svcN) -and $V2StopProof[$svcN].Tree.Count -eq 2) 'усе дерево завершилось, пізніх нащадків немає → PASS і доказ зупинки ($V2StopProof)'

  # ================================================================ B1 — помилка відкриття handle НАЩАДКА (не кореня): нерозв'язаний нащадок
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $global:Fake.Procs[501].OpenThrows = $true
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true } }
  $m = Get-StopMessage { Stop-V2Service -Name $svcN }
  Add-Res 'H1' ($m -like "STOP:*CRITICAL BLOCKED*нерозв'язаний нащадок PID 501 (батько 500)*handle не відкрито*Access is denied*" -and -not $V2StopProof.ContainsKey($svcN) -and ($global:Fake.Native -join ';') -eq 'sc.exe stop integrity-v2-backend') 'handle нащадка не відкрито (процес живий у CIM) → нерозв''язаний (PID, батько, причина) → BLOCKED навіть якщо після stop він зник; доказу немає; sc stop виконано'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $global:Fake.Procs[501].OpenThrows = $true
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true } }
  $m = Get-StopMessage { Stop-V2Service -Name $svcN }
  Add-Res 'H2' ($m -like "STOP:*CRITICAL BLOCKED*нерозв'язаний нащадок PID 501 (батько 500)*досі живий*" -and -not $V2StopProof.ContainsKey($svcN) -and -not $global:Fake.Kills.Contains(501)) 'нерозв''язаний нащадок живий після stop → BLOCKED «досі живий»; за PID нічого не вбивається'
  Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $global:Fake.Procs[501].OpenThrows = $true
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; $global:Fake.Procs[500].Exited = $true; $global:Fake.Procs[501].Exited = $true; $null = New-FakeProc 502 501 9 'C:\py\python.exe' $acct } }
  $m = Get-StopMessage { Stop-V2Service -Name $svcN }
  Add-Res 'H3' ($m -like '*пізні нащадки живі: 502*') 'нащадок нерозв''язаного процесу, живий після stop, також виявляється як пізній нащадок'
  Reset-Fake; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct; $global:Fake.Procs[501].OpenThrows = $true
  Add-Res 'H4' (Test-Stop { New-V2Tree -RootProcess (New-FakeHandle 500) } "*нерозв'язаний нащадок PID 501 (батько 500)*Access is denied*не підтверджено*") 'шлях старту/репетиції (без списку): помилка handle нащадка → STOP з PID, батьком і причиною (раніше — мовчазний continue)'
  $u = New-Object System.Collections.Generic.List[object]
  $t = New-V2Tree -RootProcess (New-FakeHandle 500) -Unresolved $u
  Add-Res 'H5' ($t.Count -eq 1 -and $u.Count -eq 1 -and $u[0].Pid -eq 501 -and $u[0].ParentPid -eq 500 -and $u[0].StartUtcTicks -eq $T0.AddSeconds(1).Ticks -and $u[0].Reason -like 'handle не відкрито*') 'зі списком: запис нерозв''язаного нащадка містить PID, PID батька, час створення, причину; у дерево не додається'
  $r = @(Stop-V2ProcessTree -Tree (New-V2Tree -RootProcess (New-FakeHandle 500) -Unresolved (New-Object System.Collections.Generic.List[object])))
  Add-Res 'H6' (@($r | Where-Object { $_ -like "*нерозв'язаний нащадок PID 501*" }).Count -eq 1) 'очищення (Stop-V2ProcessTree) фіксує нерозв''язаного нащадка як проблему, а не пропускає'
  # контроль: handle не відкрито, бо процес справді завершився між знімком і відкриттям (CIM доводить вихід) → не проблема
  Reset-Fake; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  $origOpen = (Get-Item function:Open-V2ProcessHandle).ScriptBlock
  Set-Item function:Open-V2ProcessHandle { param([int]$Id) if ($Id -eq 501) { $global:Fake.Procs[501].Exited = $true; throw 'process gone (тест)' }; & $origOpen $Id }
  try { $u = New-Object System.Collections.Generic.List[object]; $t = New-V2Tree -RootProcess (New-FakeHandle 500) -Unresolved $u } finally { Set-Item function:Open-V2ProcessHandle $origOpen }
  Add-Res 'H7' ($t.Count -eq 1 -and $u.Count -eq 0) 'контроль: нащадок завершився до відкриття handle, CIM підтверджує відсутність → не нерозв''язаний'
  # PID reuse: після помилки CIM показує інший процес із тим самим PID (інший час створення) → оригінал завершився
  Reset-Fake; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct
  Set-Item function:Open-V2ProcessHandle { param([int]$Id) if ($Id -eq 501) { $null = New-FakeProc 501 1 30 'C:\other.exe' 'PC\other'; throw 'process gone (тест)' }; & $origOpen $Id }
  try { $u = New-Object System.Collections.Generic.List[object]; $t = New-V2Tree -RootProcess (New-FakeHandle 500) -Unresolved $u } finally { Set-Item function:Open-V2ProcessHandle $origOpen }
  Add-Res 'H8' ($t.Count -eq 1 -and $u.Count -eq 0 -and -not $global:Fake.Kills.Count) 'контроль: після помилки PID зайнятий іншим процесом (інший час створення) → оригінал завершився; чужий не чіпається'
  Reset-Fake; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 501 500 1 'C:\py\python.exe' $acct; $global:Fake.Procs[501].OpenThrows = $true
  $origCim = (Get-Item function:Get-V2CimProcess).ScriptBlock
  Set-Item function:Get-V2CimProcess { param([int]$Id) if ($Id -eq 501) { throw 'RPC unavailable (тест)' }; & $origCim $Id }
  try { $u = New-Object System.Collections.Generic.List[object]; $t = New-V2Tree -RootProcess (New-FakeHandle 500) -Unresolved $u } finally { Set-Item function:Get-V2CimProcess $origCim }
  Add-Res 'H9' ($u.Count -eq 1 -and $u[0].Reason -like '*CIM: RPC unavailable*') 'помилка handle + помилка повторної перевірки CIM → нерозв''язаний (вихід не доведено)'


  # ================================================================ S01–S11 — Stop-V2Service + Job Object (етап 3; усе фейкове: процеси, служба, job)
  $jobN = 'Global\integrity-v2-backend-job'; $svcSidB = Get-V2ServiceSid 'integrity-v2-backend'
  function New-JobTree {
    Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); Set-FakeSvc Running 500
    $null = New-FakeProc 500 1 0 $svcExe $acct
    $null = New-FakeProc 501 500 1 'C:\py313\python.exe' $acct 0 'python.exe -I -E -s C:\srv\integrity-v2\app\launcher\v2_job_launcher.py run --job Global\integrity-v2-backend-job -- …'
    $null = New-FakeProc 502 501 2 'C:\srv\integrity-v2\venv\Scripts\python.exe' $acct
    $null = New-FakeProc 503 502 3 'C:\py313\python.exe' $acct
    $global:Fake.Job = @{ Found = $true; SdOk = $true; LimitsOk = $true; Active = 2; Pids = @(502, 503); Alive = @(); Unknown = @(); TerminateWorks = $true; HoldFails = $false }
    $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; foreach ($q in 500, 501) { $global:Fake.Procs[$q].Exited = $true } } }
  }
  $V2Services['integrity-v2-backend'].Job = $jobN
  try {
    New-JobTree
    $r = @(Stop-V2Service -Name $svcN); $pf = $V2StopProof[$svcN]; $calls = $global:Fake.JobCalls -join ' | '
    Add-Res 'S00.control' ($r[-1] -like 'PASS*повнота: Job Object*' -and $pf.Completeness -eq 'job' -and $pf.JobVerified -and $pf.JobActive -eq 0 -and $pf.OwnerScanAlive -eq 0 -and $calls -like "hold $jobN*terminate --job $jobN --expect-owner $svcSidB*" -and $pf.Lease -eq 'HOLDER') 'контроль: job до stop коректний; після stop живі процеси job → terminate ЛИШЕ цього job → ActiveProcesses 0 → доказ Completeness=job; handle утримання зберігається в proof lease'
    Add-Res 'S08.sid' ($calls -like "*--scan-sid $svcSidB --unknown block*" -and $svcSidB -like 'S-1-5-80-*') "сканування за власником — SID служби $svcSidB, політика невизначених — block (production)"
    Add-Res 'S01' ($pf.Tree.Count -eq 4 -and (@($pf.Tree | ForEach-Object Pid) -join ',') -eq '500,501,502,503' -and -not $global:Fake.Kills.Count) 'усі PID/ідентичності дерева WinSW → launcher → venv → python відповідають очікуваним; за PID нічого не вбивається'
    New-JobTree; $global:Fake.Job.LimitsOk = $false
    $m = Get-StopMessage { Stop-V2Service -Name $svcN }
    Add-Res 'S06.limits' ($m -like 'STOP:*CRITICAL BLOCKED*ліміти Job Object*' -and -not $V2StopProof.ContainsKey($svcN) -and -not @($global:Fake.JobCalls | Where-Object { $_ -like 'terminate*' }).Count) 'ліміти job ≠ очікуваним, PID живі → terminate не викликано, доказу немає'
    New-JobTree; $global:Fake.Job.SdOk = $false
    Add-Res 'S06.sd' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*SD Job Object*') -and -not $V2StopProof.ContainsKey($svcN) -and -not @($global:Fake.JobCalls | Where-Object { $_ -like 'terminate*' }).Count) 'SD job (власник/DACL) ≠ очікуваному, PID живі → terminate не викликано'
    New-JobTree; $global:Fake.Job.Pids = @(502)
    Add-Res 'S06.membership' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*PID 503 (нащадок launcher-а) поза Job Object*') -and -not $V2StopProof.ContainsKey($svcN)) 'нащадок launcher-а поза job до stop → BLOCKED'
    New-JobTree; $global:Fake.Job.Found = $false
    Add-Res 'S06.notfound' ((Test-Stop { Stop-V2Service -Name $svcN } "*CRITICAL BLOCKED*Job Object '$jobN' не знайдено*") -and -not $V2StopProof.ContainsKey($svcN)) 'job не знайдено → BLOCKED'
    New-JobTree; $global:Fake.Job.HoldFails = $true
    Add-Res 'S06.hold' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*утримання handle*') -and -not $V2StopProof.ContainsKey($svcN)) 'handle job утримати неможливо → BLOCKED'
    New-JobTree; $global:Fake.Job.TerminateWorks = $false
    $m = Get-StopMessage { Stop-V2Service -Name $svcN }
    Add-Res 'S07' ($m -like 'STOP:*CRITICAL BLOCKED*Job Object після stop*живі процеси*' -and -not $V2StopProof.ContainsKey($svcN)) 'job не спорожнів після stop і terminate → BLOCKED'
    New-JobTree; $global:Fake.Job.Alive = @(@{ pid = 777; name = 'python.exe' })
    Add-Res 'S08' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*живі процеси власника*777*') -and -not $V2StopProof.ContainsKey($svcN)) 'процес акаунта служби поза job (напр. WMI) живий → BLOCKED'
    New-JobTree; $global:Fake.Job.Unknown = @(@{ pid = 778; name = 'x.exe' })
    Add-Res 'S08.unknown' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*невизначеним власником*778*') -and -not $V2StopProof.ContainsKey($svcN)) 'процес із невизначеним власником → BLOCKED'
    New-JobTree; $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; foreach ($q in 500, 501, 502, 503) { $global:Fake.Procs[$q].Exited = $true }; Add-FakeListener 8100 900 } }
    Add-Res 'S09' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*порт 8100 досі слухає PID 900*') -and -not $V2StopProof.ContainsKey($svcN)) 'порт backend слухається після stop → BLOCKED'
    New-JobTree; $null = New-FakeProc 502 501 2 'C:\srv\integrity-v2\venv\Scripts\python.exe' $acct; $global:Fake.Procs[502].OpenThrows = $true
    Add-Res 'S03' ((Test-Stop { Stop-V2Service -Name $svcN } "*CRITICAL BLOCKED*нерозв'язаний нащадок PID 502 (батько 501)*") -and -not $V2StopProof.ContainsKey($svcN)) 'помилка handle нащадка (у моделі з job) → BLOCKED (B1 зберігається)'
    New-JobTree; $global:Fake.Procs[503].Owner = 'PC\other'
    Add-Res 'S04' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*PID 503*PC\other*') -and -not $V2StopProof.ContainsKey($svcN)) 'невідомий власник процесу дерева → BLOCKED'
    New-JobTree; $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; foreach ($q in 500, 501, 502, 503) { $global:Fake.Procs[$q].Exited = $true }; $null = New-FakeProc 510 503 9 'C:\py313\python.exe' $acct } }
    Add-Res 'S05' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*пізні нащадки живі: 510*') -and -not $V2StopProof.ContainsKey($svcN)) 'пізній осиротілий нащадок після stop → BLOCKED навіть за порожнього job'
    New-JobTree; $global:Fake.Procs[503].Exited = $true; $null = New-FakeProc 503 1 30 'C:\other.exe' 'PC\other'; $global:Fake.Job.Pids = @(502)
    $r = @(Stop-V2Service -Name $svcN)
    Add-Res 'S02' ($r[-1] -like 'PASS*' -and -not $global:Fake.Kills.Count -and -not $global:Fake.Procs[503].Exited) 'PID 503 зайнятий чужим процесом (інший час створення, батько) → не включається в дерево і не завершується'
    # S10 — файли БД утримуються іншим процесом після stop (справжній файл, FileShare.None)
    $sr = Join-Path $tmp 'srv-s10'; $null = New-Item -ItemType Directory (Join-Path $sr 'data'); [IO.File]::WriteAllText((Join-Path $sr 'data\integrity_v2.db-wal'), 'x')
    $savedRootS = $V2Root; $V2Root = $sr
    $fs = [IO.File]::Open((Join-Path $sr 'data\integrity_v2.db-wal'), 'Open', 'ReadWrite', 'None')
    try { New-JobTree; Add-Res 'S10' ((Test-Stop { Stop-V2Service -Name $svcN } '*CRITICAL BLOCKED*файл БД відкритий іншим процесом: integrity_v2.db-wal*') -and -not $V2StopProof.ContainsKey($svcN)) 'DB/WAL/SHM утримується процесом після stop → BLOCKED' }
    finally { $fs.Dispose(); $V2Root = $savedRootS }
  } finally { $V2Services['integrity-v2-backend'].Job = $null; $V2StopProof.Clear() }
  New-JobTree; $global:Fake.Job = $null
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { Set-FakeSvc Stopped 0; foreach ($q in 500, 501, 502, 503) { $global:Fake.Procs[$q].Exited = $true } } }
  $r = @(Stop-V2Service -Name $svcN)
  Add-Res 'S00.treeonly' ($r[-1] -like 'PASS*повнота: лише дерево*' -and $V2StopProof[$svcN].Completeness -eq 'tree-only' -and -not $V2StopProof[$svcN].JobVerified -and -not $global:Fake.JobCalls.Count) 'Job Object не налаштовано (production сьогодні) → доказ лише «tree-only» (для відкату недостатній — R05)'
  $V2StopProof.Clear()

  Reset-Fake; $V2StopProof[$svcN] = [pscustomobject]@{ Lease = 'HOLDER'; Name = $svcN }
  $absent = @(Stop-V2Service -Name $svcN)
  Add-Res 'B02.absent' ($absent[-1] -like 'INFO*доказ зупинки відсутній*' -and -not $V2StopProof.ContainsKey($svcN) -and @($global:Fake.JobCalls | Where-Object { $_ -eq 'release' }).Count -eq 1) 'відсутня служба → історичний proof вилучено, lease закрито'
  Add-Res 'B02.restore' (Test-Stop { Assert-V2RestorePermitted -Known @() } '*немає доказу зупинки backend*') 'restore зі stale proof заборонено'


  # auditfix2: повтор proof лише для BLOCKED через scan (короткоживучі процеси, напр. conhost.exe); стійкий процес / непорожній job → BLOCKED
  foreach ($rc in @(@('J.retry-transient', 2, 0, 'PASS', 3), @('J.retry-persistent', 99, 0, 'BLOCKED', 5), @('J.retry-jobnotempty', 99, 1, 'BLOCKED', 1))) {
    Reset-Fake; $global:Fake.Job = @{ Found = $true; SdOk = $true; LimitsOk = $true; Active = $rc[2]; Pids = $(if ($rc[2]) { @(777) } else { @() }); Alive = @(@{ pid = 950; name = 'conhost.exe' }); Unknown = @(); TerminateWorks = $true; HoldFails = $false; AliveFor = $rc[1]; AliveSaved = $null }
    $rep = Get-V2JobReport -JobName $jobN -OwnerSid (Get-V2ServiceSid 'integrity-v2-backend') -Scan
    $calls = @($global:Fake.JobCalls | Where-Object { $_ -like 'proof*--scan-sid*' }).Count
    Add-Res $rc[0] ($rep.verdict -eq $rc[3] -and $calls -eq $rc[4]) "$($rc[0]): вердикт $($rep.verdict), спостережень $calls (очікувано $($rc[3]) / $($rc[4]))"
  }

  # auditfix3: власний процес утримання lease (командний рядок під коренем V2) не є «процесом V2»; чужий процес з тим самим PID — є
  Reset-Fake; $V2OwnHelpers.Clear()
  $hp = New-FakeProc 960 1 3 'C:\py313\python.exe' 'PC\admin' 0 "python.exe -I -E -s `"$V2Root\app\launcher\v2_job_launcher.py`" hold --job `"Global\integrity-v2-backend-job`""
  $V2OwnHelpers[960] = $T0.AddSeconds(3).Ticks
  Add-Res 'OH.excluded' (-not @(Get-V2SuspectProcesses | Where-Object { [int]$_.ProcessId -eq 960 }).Count) 'зареєстрований процес утримання (PID + час створення) не вважається процесом V2'
  $V2OwnHelpers[960] = $T0.AddSeconds(99).Ticks
  Add-Res 'OH.pid-reuse' (@(Get-V2SuspectProcesses | Where-Object { [int]$_.ProcessId -eq 960 }).Count -eq 1) 'той самий PID, інший час створення (PID reuse) → процес V2 (виключення не діє)'
  $V2OwnHelpers.Clear()
  Add-Res 'OH.unregistered' (@(Get-V2SuspectProcesses | Where-Object { [int]$_.ProcessId -eq 960 }).Count -eq 1) 'незареєстрований процес із шляхом V2 → процес V2 (евристика без змін)'
  # auditfix2: Stop-V2Service — holder звільняється на будь-якій відмові; stop → start інвалідує proof і lease ДО старту
  $V2Services['integrity-v2-backend'].Job = $jobN
  try {
    New-JobTree; $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { throw 'sc stop failed (тест)' } }
    $m = Get-StopMessage { Stop-V2Service -Name $svcN }
    Add-Res 'L.stop-throw' ($m -like '*sc stop failed (тест)*' -and @($global:Fake.JobCalls | Where-Object { $_ -eq 'release' }).Count -eq 1 -and -not $V2StopProof.ContainsKey($svcN)) 'виняток після старту holder (sc stop) → holder звільнено, доказу немає'
    New-JobTree; $global:Fake.Job.HoldFails = $false
    $null = @(Stop-V2Service -Name $svcN)
    $hadLease = $V2StopProof.ContainsKey($svcN) -and $V2StopProof[$svcN].Lease -eq 'HOLDER'
    $global:Fake.Seq.Clear()
    $r = @(Invoke-V2ServiceStart -Name $svcN -PreCheck { param($n) $global:Fake.Seq.Add('precheck') } -Starter { param($n) $global:Fake.Seq.Add('starter') } -Stopper { param($n) } -Checks { 'PASS  checks' })
    $q = @($global:Fake.Seq)
    Add-Res 'L.start-invalidates' ($hadLease -and $q[0] -eq 'release' -and [array]::IndexOf($q, 'starter') -gt 0 -and -not $V2StopProof.ContainsKey($svcN)) "stop → start без відкату: lease звільнено й proof видалено ДО старту (послідовність: $($q -join ', '))"
    Add-Res 'L.start-norestore' (Test-Stop { Assert-V2RestorePermitted -Known @() } '*немає доказу зупинки backend*') 'після старту stale proof для відкату недоступний'
  } finally { $V2Services['integrity-v2-backend'].Job = $null; $V2StopProof.Clear() }

  # ================================================================ ДЕЛЬТА 4 — захищений каталог: production без overrides; ядро з перевірками ДО створення
  $prodParams = @((Get-Command New-V2ProtectedDirectory).Parameters.Keys | Where-Object { $_ -notin [System.Management.Automation.PSCmdlet]::CommonParameters })
  Add-Res 'D4a' ((($prodParams | Sort-Object) -join ',') -eq 'DecisionRef,Path') 'production New-V2ProtectedDirectory має лише -Path і -DecisionRef (немає -Sddl / -TrustedSids)'
  foreach ($bp in 'C:\srv2', 'c:\srv', 'C:\srv\', 'C:\SRV', 'C:\srv\..\srv') {
    Add-Res 'D4b' ((Test-Stop { New-V2ProtectedDirectory -Path $bp -DecisionRef 'X' } '*лише точний затверджений шлях*') -and -not (Test-Path -LiteralPath 'C:\srv2')) "production: шлях '$bp' ≠ C:\srv → STOP до будь-якої дії"
  }
  Set-Item function:Get-V2Acl $orig['Get-V2Acl']
  try {
    $allowed = @($me, 'S-1-5-18', 'S-1-5-32-544')
    $okSddl = "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)"
    foreach ($case in @(@('сторонній SID (Authenticated Users)', "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)(A;OICI;FA;;;AU)", '*сторонній або надмірний запис S-1-5-11*'),
                        @('надмірний ACL (Users RX)', "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)(A;OICI;0x1200a9;;;BU)", '*сторонній або надмірний запис S-1-5-32-545*'),
                        @('неправильний власник (SYSTEM)', "O:SYD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)", '*власник S-1-5-18*'),
                        @('права не FullControl', "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;$me)", '*≠ FullControl*'),
                        @('успадковувані записи ≠ записам об''єкта', "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;FA;;;$me)", '*успадковувані записи*'),
                        @('без захисту від успадкування', "O:${me}D:AI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)", '*D:P*'),
                        @('немає обов''язкового SYSTEM', "O:${me}D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)", '*обов''язкового запису S-1-5-18*'))) {
      $dir = Join-Path $tmp ('pd-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
      $msg = Get-StopMessage { New-V2ProtectedDirectoryCore -Path $dir -Sddl $case[1] -DecisionRef 'TEST' -ExpectedOwnerSid $me -AllowedSids $allowed -TrustedSids $me }
      Add-Res 'D4c' ($msg -like "STOP:$($case[2])" -and -not (Test-Path -LiteralPath $dir)) "ядро: $($case[0]) → STOP, каталог НЕ створено"
    }
    $parentRiskD4 = @(Get-V2AclRisk -Acl (Get-V2Acl $tmp) -Kind ancestor -TrustedSids $me)
    if ($parentRiskD4.Count) {
      Add-NotRun 'D4d' "батьківський тестовий каталог має небезпечні ACL: $($parentRiskD4 -join '; ')"
      Add-NotRun 'D4e' 'потребує успішного створення каталогу в D4d'
    } else {
      $dir = Join-Path $tmp 'pd-ok'
      $r = @(New-V2ProtectedDirectoryCore -Path $dir -Sddl $okSddl -DecisionRef 'TEST' -ExpectedOwnerSid $me -AllowedSids $allowed -TrustedSids $me)
      Add-Res 'D4d' ($r[-1] -like 'PASS*атомарно*' -and (Get-V2Acl $dir).AreAccessRulesProtected) 'ядро: затверджений SDDL → атомарне створення, read-back PASS (контроль)'
      Add-Res 'D4e' (Test-Stop { New-V2ProtectedDirectoryCore -Path $dir -Sddl $okSddl -DecisionRef 'TEST' -ExpectedOwnerSid $me -AllowedSids $allowed -TrustedSids $me } '*уже існує*') 'ядро: каталог уже існує → STOP'
    }
  } finally { Set-Item function:Get-V2Acl { param([string]$Path) $s = $global:Fake.Acls[$Path]; if (-not $s) { throw "немає фейкового ACL для $Path" }; $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($s); $x } }

  # ================================================================ P4 — безпека відкату SQLite
  Reset-Fake; $null = New-FakeProc 500 1 0 $svcExe $acct
  $known = @([pscustomobject]@{ Pid = 500; StartUtcTicks = $T0.Ticks; Exe = $svcExe; CommandLine = ''; ParentPid = 1; ParentStartUtcTicks = 0; Owner = $acct; Handle = $null })
  Add-Res 'P4a' (Test-Stop { Assert-V2TreeExited -Tree $known } '*досі працює*') 'збережений процес (з файлу, без handle) живий із тим самим часом створення → STOP'
  Reset-Fake; $null = New-FakeProc 500 1 99 'C:\other\x.exe' 'PC\someone'
  $r = @(Assert-V2TreeExited -Tree $known)
  Add-Res 'P4b' ($r[-1] -like 'PASS*' -and $global:Fake.Kills.Count -eq 0 -and -not $global:Fake.Procs[500].Exited) 'PID зайнятий іншим процесом (інший час створення) → оригінал завершився; чужий не вважається V2 і не чіпається'
  $dd = Join-Path $tmp 'data'; $null = New-Item -ItemType Directory $dd; Set-Content (Join-Path $dd 'integrity_v2.db') 'x'
  Reset-Fake; $null = New-FakeProc 500 1 0 $svcExe $acct
  $m = Get-StopMessage { Assert-V2RestoreReady -DataDir $dd -Known $known -Py $Py -DbTool 'x' -Backup 'C:\немає.db' -BackupSha256 ('0' * 64) -ExpectVersion 2 }
  Add-Res 'P4c' ($m -like 'STOP:*досі працює*' -and $global:Fake.Native.Count -eq 0) 'живий збережений процес → STOP ДО перевірки копії й будь-яких дій із БД'
  Reset-Fake; $lf = [IO.File]::Open((Join-Path $dd 'integrity_v2.db'), 'Open', 'ReadWrite', 'None')
  try { $ok = Test-Stop { Assert-V2NoProcesses -DataDir $dd -Known $known } '*відкритий іншим процесом*' } finally { $lf.Dispose() }
  Add-Res 'P4d' $ok 'файл БД заблоковано (FileShare.None не відкривається) → STOP'
  Reset-Fake; Set-Content (Join-Path $dd 'integrity_v2.db-wal') 'w'; $lf = [IO.File]::Open((Join-Path $dd 'integrity_v2.db-wal'), 'Open', 'ReadWrite', 'None')
  try { $ok = Test-Stop { Assert-V2NoProcesses -DataDir $dd -Known $known } '*db-wal*' } finally { $lf.Dispose() }
  Add-Res 'P4e' $ok 'заблокований WAL-файл → STOP'
  Reset-Fake; $null = New-FakeProc 777 1 0 'C:\py\python.exe' 'PC\x' 0 '-m uvicorn app.main:app --port 8100'
  Add-Res 'P4f' (Test-Stop { Assert-V2NoProcesses -DataDir $dd -Known $known } '*працюють процеси V2*') 'евристика: процес із --port 8100 → STOP (додатковий gate)'
  Reset-Fake
  Add-Res 'P4g' (Test-Stop { Assert-V2RestoreReady -DataDir $dd -Known @() -Py $Py -DbTool 'x' -Backup 'x' -BackupSha256 'x' -ExpectVersion 2 } '*немає збережених ідентичностей*') 'немає збережених ідентичностей → відновлення заборонено'
  $ip = Save-V2Identities -Name 't' -Tree $known -Dir $idDir; $back = @(Import-V2Identities -Path $ip)
  Add-Res 'P4h' ($back.Count -eq 1 -and $back[0].Pid -eq 500 -and $back[0].StartUtcTicks -eq $T0.Ticks -and $null -eq $back[0].Handle) 'ідентичності зберігаються у файл і відновлюються (для відкату в новій сесії)'

  # ================================================================ P5 — ACL і шляхи
  $root = Join-Path $tmp 'srv\integrity-v2'; $null = New-Item -ItemType Directory $root
  $savedRoot = $V2Root; $V2Root = $root
  try {
    Reset-Fake
    Add-Res 'P5a' (Test-Stop { Assert-V2InRoot "$root\data\..\..\x" } '*..*') 'шлях із .. → STOP'
    Add-Res 'P5b' (Test-Stop { Assert-V2InRoot "$root-evil\data" } '*поза*') 'префікс-обхід (integrity-v2-evil) → STOP'
    Add-Res 'P5c' (Test-Stop { Assert-V2InRoot "$root\DATA~1" } '*8.3*') 'коротке ім''я 8.3 → STOP'
    $real = Join-Path $tmp 'realdir'; $null = New-Item -ItemType Directory $real; $null = New-Item -ItemType Junction -Path "$root\jn" -Target $real
    Add-Res 'P5d' (Test-Stop { Assert-V2InRoot "$root\jn\x" } '*reparse*') 'reparse point (junction) у компоненті шляху → STOP'
    $m = Get-StopMessage { Grant-V2 -Path "$root\..\outside" -Account 'NT SERVICE\integrity-v2-backend' -Rights 'RX' }
    Add-Res 'P5e' ($m -like 'STOP:*' -and $global:Fake.Native.Count -eq 0) 'Grant-V2 з .. → STOP ДО icacls (викликів icacls 0)'
    $m = Get-StopMessage { Grant-V2 -Path "$root\jn" -Account 'NT SERVICE\integrity-v2-backend' -Rights 'RX' }
    Add-Res 'P5f' ($m -like 'STOP:*reparse*' -and $global:Fake.Native.Count -eq 0) 'Grant-V2 на junction → STOP ДО icacls'
    Add-Res 'P5g' (Test-Stop { Grant-V2 -Path "$root\data" -Account 'BUILTIN\Users' -Rights '(OI)(CI)M' } '*лише для акаунтів служб*') 'Grant-V2 для не-службового акаунта → STOP'
  } finally { $V2Root = $savedRoot }
  $base = "O:${tiSid}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)(A;OICIIO;GA;;;CO)"
  foreach ($c in @(@('GenericWrite', '(A;;GW;;;AU)'), @('WriteEA', '(A;;0x10;;;AU)'), @('WriteAttributes', '(A;;0x100;;;AU)'), @('успадкований Delete', '(A;ID;0x10000;;;AU)'))) {
    $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($base + $c[1])
    Add-Res 'P5h' (@(Get-V2AclRisk -Acl $x -Kind ancestor).Count -gt 0) "предок: $($c[0]) для Authenticated Users → ризик (STOP)"
  }
  $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($base + '(A;;0x4;;;AU)(A;OICIIO;0xE0010000;;;AU)')
  Add-Res 'P5i' (@(Get-V2AclRisk -Acl $x -Kind ancestor).Count -eq 0 -and @(Get-V2AclRisk -Acl $x -Kind ancestor -IncludeInheritable).Count -gt 0) 'C:\ як на сервері (AU CreateDirectories + InheritOnly GR/GW/GX/Delete): сам предок без ризику; для незахищеного дочірнього — ризик'
  $svcSid = 'S-1-5-80-1111111111-2222222222-3333333333-4044444444-1555555555'
  $good = "O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1301bf;;;$svcSid)"
  $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($good)
  Add-Res 'P5j' ((@(Assert-V2AclExact -Acl $x -ServiceSid $svcSid -ServiceRights M -IsContainer -Label t))[-1] -like 'PASS*') 'каталог data: об''єкт + майбутні файли/каталоги = матриця → PASS'
  $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($good + '(A;OICIIO;0x1301bf;;;BU)')
  Add-Res 'P5k' (Test-Stop { Assert-V2AclExact -Acl $x -ServiceSid $svcSid -ServiceRights M -IsContainer -Label t } '*ChildObject: зайвий S-1-5-32-545*') 'InheritOnly-запис Users для майбутніх файлів → STOP (у REV3 ігнорувався)'
  $tree0 = Join-Path $tmp 'acltree'; $savedRoot = $V2Root; $V2Root = $tree0
  try {
    $null = New-Item -ItemType Directory "$tree0\code\sub" -Force; Set-Content "$tree0\code\a.py" 'a'; Set-Content "$tree0\code\sub\b.py" 'b'
    $dirOk = "O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;$svcSid)"; $fileOk = "O:BAD:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1200a9;;;$svcSid)"
    Reset-Fake; $global:Fake.Acls = @{ "$tree0\code" = $dirOk; "$tree0\code\sub" = $dirOk; "$tree0\code\a.py" = $fileOk; "$tree0\code\sub\b.py" = $fileOk }
    $r = @(Assert-V2AclTree -Path "$tree0\code" -ServiceSid $svcSid -ServiceRights RX -Role code)
    Add-Res 'P5l' ($r[-1] -like 'PASS*4 об''єктів*') 'рекурсивне зчитування: 4 об''єкти коду = матриця → PASS'
    $global:Fake.Acls["$tree0\code\sub\b.py"] = "O:BAD:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1200a9;;;$svcSid)(A;;0x1301bf;;;AU)"
    Add-Res 'P5m' (Test-Stop { Assert-V2AclTree -Path "$tree0\code" -ServiceSid $svcSid -ServiceRights RX -Role code } '*b.py*зайвий S-1-5-11*') 'глибокий нащадок із зайвим записом → STOP'
    $global:Fake.Acls["$tree0\code\sub\b.py"] = "O:${svcSid}D:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1200a9;;;$svcSid)"
    Add-Res 'P5n' (Test-Stop { Assert-V2AclTree -Path "$tree0\code" -ServiceSid $svcSid -ServiceRights RX -Role code } '*власник*') 'код: файл, власником якого є служба → STOP'
    $dirM = "O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1301bf;;;$svcSid)"; $fileM = "O:${svcSid}D:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1301bf;;;$svcSid)"
    $global:Fake.Acls = @{ "$tree0\code" = $dirM; "$tree0\code\sub" = $dirM; "$tree0\code\a.py" = $fileM; "$tree0\code\sub\b.py" = $fileM }
    Add-Res 'P5o' ((@(Assert-V2AclTree -Path "$tree0\code" -ServiceSid $svcSid -ServiceRights M -Role data))[-1] -like 'PASS*') 'дані: файл, створений службою (власник — служба), Modify → PASS'
  } finally { $V2Root = $savedRoot }
  # захищений предок (варіант C:\srv — лише за рішенням №5): атомарне створення у тимчасовому каталозі, власник — поточний користувач
  Reset-Fake; Set-Item function:Get-V2Acl $orig['Get-V2Acl']
  try {
    $pd = Join-Path $tmp 'protected-srv'
    Add-Res 'P5p' (Test-Stop { New-V2ProtectedDirectoryCore -Path $pd -Sddl "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)" -DecisionRef ' ' -ExpectedOwnerSid $me -AllowedSids @($me, 'S-1-5-18', 'S-1-5-32-544') } '*рішення №5*') 'без посилання на рішення №5 → STOP'
    $parentRisk = @(Get-V2AclRisk -Acl (Get-V2Acl $tmp) -Kind ancestor -TrustedSids $me)
    if ($parentRisk.Count) {
      Add-NotRun 'P5q' "батьківський тестовий каталог має небезпечні ACL: $($parentRisk -join '; ')"
      Add-NotRun 'P5r' 'потребує успішного створення каталогу в P5q'
    } else {
      $r = @(New-V2ProtectedDirectoryCore -Path $pd -Sddl "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)" -DecisionRef 'TEST-LOCAL' -ExpectedOwnerSid $me -AllowedSids @($me, 'S-1-5-18', 'S-1-5-32-544') -TrustedSids $me)
      Add-Res 'P5q' ($r[-1] -like 'PASS*атомарно*' -and (Get-V2Acl $pd).AreAccessRulesProtected) 'атомарне створення із захищеним ACL + read-back усіх областей → PASS'
      Add-Res 'P5r' (Test-Stop { New-V2ProtectedDirectoryCore -Path $pd -Sddl "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)" -DecisionRef 'TEST-LOCAL' -ExpectedOwnerSid $me -AllowedSids @($me, 'S-1-5-18', 'S-1-5-32-544') -TrustedSids $me } '*уже існує*') 'каталог уже існує → STOP (повторне використання заборонено)'
    }
    Add-Res 'P5s' (Test-Stop { New-V2ProtectedDirectoryCore -Path (Join-Path $tmp 'x2') -Sddl "O:${me}D:AI(A;OICI;FA;;;$me)" -DecisionRef 'TEST-LOCAL' -ExpectedOwnerSid $me -AllowedSids @($me) -TrustedSids $me } '*D:P*') 'SDDL без захисту від успадкування → STOP'
    Add-Res 'P5t' (Test-Stop { New-V2ProtectedDirectoryCore -Path (Join-Path $tmp 'no-parent\x') -Sddl "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)" -DecisionRef 'TEST-LOCAL' -ExpectedOwnerSid $me -AllowedSids @($me, 'S-1-5-18', 'S-1-5-32-544') -TrustedSids $me } '*немає батьківського*') 'немає батьківського каталогу → STOP'
    Add-Res 'P5u' (Test-Stop { New-V2ProtectedDirectoryCore -Path (Join-Path $tmp 'x3') -Sddl "O:${me}D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;$me)" -DecisionRef 'TEST-LOCAL' -ExpectedOwnerSid $me -AllowedSids @($me, 'S-1-5-18', 'S-1-5-32-544') } '*небезпечні права*') 'батьківський каталог із правами стороннього (без довіри) → STOP'
  } finally { Set-Item function:Get-V2Acl { param([string]$Path) $s = $global:Fake.Acls[$Path]; if (-not $s) { throw "немає фейкового ACL для $Path" }; $x = New-Object System.Security.AccessControl.DirectorySecurity; $x.SetSecurityDescriptorSddlForm($s); $x } }

  # ================================================================ P6 — WinSW 2.12.0
  $fake = Join-Path $tmp 'winsw.exe'; [IO.File]::WriteAllBytes($fake, [byte[]](1, 2, 3))
  Add-Res 'P6a' (Test-Stop { Assert-V2Winsw -Path $fake -Label w } '*≠ еталону 05b82d46*') 'SHA256 ≠ еталону WinSW 2.12.0 (05b82d46…) → STOP'
  $pyHash = (Get-FileHash -LiteralPath $Py -Algorithm SHA256).Hash.ToLower(); $pyVer = ConvertTo-V2Version ([string](Get-Item -LiteralPath $Py).VersionInfo.FileVersion)
  Add-Res 'P6b' (Test-Stop { Assert-V2Winsw -Path $Py -Label w -Sha256 $pyHash } '*FileVersion*≠ 2.12.0*') 'правильна сума, але версія ≠ 2.12.0 → STOP'
  Add-Res 'P6c' ($pyVer -ne '' -and (@(Assert-V2Winsw -Path $Py -Label w -Sha256 $pyHash -Version $pyVer))[-1] -like 'PASS*') 'контроль механізму: сума й версія збігаються → PASS'
  Add-Res 'P6d' ((ConvertTo-V2Version '2.12.0.0') -eq '2.12.0' -and (ConvertTo-V2Version '2.12.0+eef5bade') -eq '2.12.0') 'нормалізація FileVersion 2.12.0.0 / ProductVersion 2.12.0+… → 2.12.0'
  $xml = Join-Path $tmp 'b.xml'; Copy-Item (Join-Path $PSScriptRoot 'integrity-v2-backend.xml.template') $xml
  Add-Res 'P6e' ((@(Test-V2WinswXml -XmlPath $xml -Name integrity-v2-backend -WinswVersion '2.12.0' -AllowPlaceholders))[-1] -like 'PASS*') 'шаблон backend: схема WinSW 2.12 → PASS'
  Add-Res 'P6f' (Test-Stop { Test-V2WinswXml -XmlPath $xml -Name integrity-v2-backend -WinswVersion '3.0.0' -AllowPlaceholders } '*лише 2.12.0*') 'версія 3.x → STOP (підтримки v3 немає)'
  Add-Res 'P6g' (Test-Stop { Test-V2WinswXml -XmlPath $xml -Name integrity-v2-backend -WinswVersion '2.12.0.0' -AllowPlaceholders } '*лише 2.12.0*') 'ненормалізована версія 2.12.0.0 → STOP'
  foreach ($mut in @(@('<domain>NT SERVICE</domain>', '<username>NT SERVICE\integrity-v2-backend</username>', 'username (схема v3)'),
                     @('<user>integrity-v2-backend</user>', '<user>integrity-v2-backend</user><password>x</password>', 'password'),
                     @('<startmode>Manual</startmode>', '<startmode>Automatic</startmode>', 'Automatic'),
                     @('<domain>NT SERVICE</domain>', '<domain>NT AUTHORITY</domain>', 'NT AUTHORITY'))) {
    $t = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'integrity-v2-backend.xml.template'))
    if (-not $t.Contains($mut[0])) { Add-Res 'P6h' $false "мутація $($mut[2]): шаблон не містить фрагмент"; continue }
    [IO.File]::WriteAllText($xml, $t.Replace($mut[0], $mut[1]), (New-Object Text.UTF8Encoding $false))
    Add-Res 'P6h' (Test-Stop { Test-V2WinswXml -XmlPath $xml -Name integrity-v2-backend -WinswVersion '2.12.0' -AllowPlaceholders } '*XML*') "XML мутація ($($mut[2])) → STOP"
  }
  Copy-Item (Join-Path $PSScriptRoot 'integrity-v2-caddy.xml.template') $xml -Force
  Add-Res 'P6i' ((@(Test-V2WinswXml -XmlPath $xml -Name integrity-v2-caddy -WinswVersion '2.12.0'))[-1] -like 'PASS*') 'шаблон caddy: схема WinSW 2.12 → PASS'
  $V2Services['integrity-v2-backend'].Exe = $fake
  try { Reset-Fake; Add-Res 'P6j' ((Test-Stop { Install-V2Service -Name 'integrity-v2-backend' } '*SHA256*') -and $global:Fake.Native.Count -eq 0) 'Install-V2Service: копія WinSW ≠ еталону → STOP ДО install (викликів 0)' }
  finally { $V2Services['integrity-v2-backend'].Exe = 'C:\srv\integrity-v2\services\backend\integrity-v2-backend.exe' }

  # ================================================================ Частина Q — справжній Invoke-V2Native, лише власні дочірні процеси python (НЕ B1-QA)
  foreach ($n in 'Invoke-V2Native', 'Stop-V2Handle', 'Wait-V2Handle') { Set-Item "function:$n" $orig[$n] }
  $global:LASTEXITCODE = 0
  Add-Res 'Q1' (Test-Stop { Invoke-V2Native -Exe 'C:\немає\такого.exe' -What 'missing' } '*не знайдено*') 'неіснуючий exe (застарілий $LASTEXITCODE=0) → STOP'
  Add-Res 'Q2' (Test-Stop { Invoke-V2Native -Exe 'python.exe' -What 'relative' } '*не абсолютний*') 'відносний шлях → STOP'
  $m = Get-StopMessage { Invoke-V2Native -Exe $Py -ArgList @('-c', 'import sys; sys.stderr.write(''err-marker''); sys.exit(3)') -What 'exit3' }
  Add-Res 'Q3' ($m -like 'STOP:*код 3*err-marker*') 'код 3 → STOP; stderr включено в повідомлення'
  $global:LASTEXITCODE = 7
  $ok = @(Invoke-V2Native -Exe $Py -ArgList @('-c', 'print(0)') -What 'exit0')
  Add-Res 'Q4' ($ok[-1] -eq '0') 'код 0 при застарілому $LASTEXITCODE=7 → PASS (свіжий код процесу)'
  $tricky = @('a b', 'q"uote', 'trail\', 'C:\x y\', '', 'NT SERVICE\integrity-v2-backend')
  $echo = @(Invoke-V2Native -Exe $Py -ArgList (@('-c', 'import sys,json; print(json.dumps(sys.argv[1:]))') + $tricky) -Utf8 -What 'argv')
  Add-Res 'Q5' ((($echo[-1] | ConvertFrom-Json) -join '|') -eq ($tricky -join '|')) 'аргументи з пробілами, лапками, \ і порожні — точно'
  $m = Get-StopMessage { Invoke-V2Native -Exe $Py -ArgList @('-c', 'import time; time.sleep(30)') -What 'timeout' -TimeoutSec 1 }
  Add-Res 'Q6' ($m -like 'STOP:*тайм-аут*зупинено й завершення підтверджено*') 'тайм-аут → Kill власного handle, завершення підтверджено → STOP'
  Set-Item function:Stop-V2Handle { param($h) throw 'Kill denied (тест)' }
  Set-Item function:Wait-V2Handle { param($h, $ms) if ($ms -eq 1000 -or $ms -eq 15000) { $false } else { [bool]$h.WaitForExit($ms) } }
  $m = Get-StopMessage { Invoke-V2Native -Exe $Py -ArgList @('-c', 'import time; time.sleep(3)') -What 'timeout-killfail' -TimeoutSec 1 }
  Set-Item function:Stop-V2Handle $orig['Stop-V2Handle']; Set-Item function:Wait-V2Handle $orig['Wait-V2Handle']
  Add-Res 'Q7' ($m -like 'STOP:*НЕ завершено*Kill denied*CRITICAL*') 'тайм-аут + помилка Kill + вихід не підтверджено → CRITICAL STOP (помилка Kill не приховується)'
  Start-Sleep 4                                                                   # власний дочірній процес із B7 завершується сам (sleep 3)
  $dbTool = Join-Path $PSScriptRoot 'v2_db_tool.py'; $bdir = Join-Path $tmp 'bk'; $null = New-Item -ItemType Directory $bdir
  $bk = Join-Path $bdir 'v2_auth-initial.db'
  $null = Invoke-V2Native -Exe $Py -ArgList @('-c', "import sqlite3; c=sqlite3.connect(r'$bk'); c.execute('create table v2_users(id integer, role text)'); c.execute('pragma user_version=1'); c.commit(); c.close()") -What 'mkdb'
  $bkSha = (Get-FileHash -LiteralPath $bk -Algorithm SHA256).Hash.ToLower()
  $dd2 = Join-Path $tmp 'data2'; $null = New-Item -ItemType Directory $dd2
  Reset-Fake; $known2 = @([pscustomobject]@{ Pid = 500; StartUtcTicks = $T0.Ticks; Exe = $svcExe; CommandLine = ''; ParentPid = 1; ParentStartUtcTicks = 0; Owner = $acct; Handle = $null })
  $r = @(Assert-V2RestoreReady -DataDir $dd2 -Known $known2 -Py $Py -DbTool $dbTool -Backup $bk -BackupSha256 $bkSha -ExpectVersion 1)
  Add-Res 'Q8' ($r[-1] -like 'PASS*відновлення дозволено*') 'процеси завершились, файли вільні, SHA і verify копії → відновлення дозволено'
  Add-Res 'Q9' (Test-Stop { Assert-V2RestoreReady -DataDir $dd2 -Known $known2 -Py $Py -DbTool $dbTool -Backup $bk -BackupSha256 ('0' * 64) -ExpectVersion 1 } '*SHA256*') 'SHA256 копії ≠ записаному → STOP до відновлення'
  $bad = Join-Path $bdir 'corrupt.db'; [IO.File]::WriteAllBytes($bad, [Text.Encoding]::ASCII.GetBytes('not a sqlite database at all'))
  $badSha = (Get-FileHash -LiteralPath $bad -Algorithm SHA256).Hash.ToLower()
  Add-Res 'Q10' (Test-Stop { Assert-V2RestoreReady -DataDir $dd2 -Known $known2 -Py $Py -DbTool $dbTool -Backup $bad -BackupSha256 $badSha -ExpectVersion 1 } '*v2_db_tool verify*') 'пошкоджена копія (SHA збігається, але не SQLite) → STOP на verify'
  Add-Res 'Q11' (Test-Stop { Assert-V2RestoreReady -DataDir $dd2 -Known $known2 -Py $Py -DbTool $dbTool -Backup $bk -BackupSha256 $bkSha -ExpectVersion 2 } '*user_version*') 'неправильна версія схеми копії → STOP'

  # ---------------- ДЕЛЬТА 1 — перший Wait-V2Handle кидає виняток (власний дочірній python)
  $script:w = 0
  Set-Item function:Wait-V2Handle { param($h, $ms) $script:w++; if ($script:w -eq 1) { throw 'wait failed (тест)' }; [bool]$h.WaitForExit($ms) }
  $m = Get-StopMessage { Invoke-V2Native -Exe $Py -ArgList @('-c', 'import time; time.sleep(30)') -What 'wait-throws' -TimeoutSec 20 }
  Set-Item function:Wait-V2Handle $orig['Wait-V2Handle']
  Add-Res 'Q12' ($m -like 'STOP:*помилка очікування (wait failed (тест))*зупинено й завершення підтверджено*') 'перший wait кидає виняток → контрольована зупинка через handle, завершення підтверджено → STOP (не PASS)'
  $script:w = 0
  Set-Item function:Wait-V2Handle { param($h, $ms) $script:w++; if ($script:w -le 2) { throw "wait failed #$($script:w)" }; [bool]$h.WaitForExit($ms) }
  Set-Item function:Stop-V2Handle { param($h) throw 'Kill denied (тест)' }
  $m = Get-StopMessage { Invoke-V2Native -Exe $Py -ArgList @('-c', 'import time; time.sleep(3)') -What 'wait-kill-wait-throw' -TimeoutSec 20 }
  Set-Item function:Wait-V2Handle $orig['Wait-V2Handle']; Set-Item function:Stop-V2Handle $orig['Stop-V2Handle']
  Add-Res 'Q13' ($m -like 'STOP:*помилка очікування*НЕВІДОМИЙ*Kill: Kill denied*очікування після Kill: wait failed #2*CRITICAL*') 'wait-виняток + Kill-помилка + виняток другого wait → стан НЕВІДОМИЙ → CRITICAL STOP з усіма помилками'
  Start-Sleep 4
  $script:w = 0
  Set-Item function:Wait-V2Handle { param($h, $ms) $script:w++; if ($script:w -eq 1) { throw 'wait failed' }; if ($script:w -eq 2) { return $false }; [bool]$h.WaitForExit($ms) }
  $m = Get-StopMessage { Invoke-V2Native -Exe $Py -ArgList @('-c', 'import time; time.sleep(30)') -What 'wait-throw-notexited' -TimeoutSec 20 }
  Set-Item function:Wait-V2Handle $orig['Wait-V2Handle']
  Add-Res 'Q14' ($m -like 'STOP:*НЕВІДОМИЙ або не завершено*CRITICAL*') 'wait-виняток, Kill виконано, але завершення не підтверджено → CRITICAL STOP'

  # ---------------- ДЕЛЬТА 3 + B3 — fail-fast відновлення SQLite (справжні файли й v2_db_tool; синтетичні БД: integrity_v2 v2 з порожніми таблицями seed, v2_auth v1; процеси фейкові)
  $Vi = $V2DbSet['integrity_v2.db']; $Va = $V2DbSet['v2_auth.db']          # версії поточного релізу ($V2ReleaseSchema)
  $r3 = Join-Path $tmp 'srv3\integrity-v2'; $d3 = Join-Path $r3 'data'; $null = New-Item -ItemType Directory $d3
  $seedT = 'answers', 'components', 'cycles', 'objective_indicators', 'questions', 'recommendations', 'response_sets', 'units'
  $ddlF = Join-Path $tmp 'auth-ddl.sql'; [IO.File]::WriteAllText($ddlF, ((Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-I', $dbTool, 'ddl', '--kind', 'auth', '--expect-version', "$Va") -Utf8 -What 'auth ddl') -join "`n"))
  $mkA = { param($path) $null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.executescript(open(sys.argv[2],encoding=''utf-8'').read()); c.execute(''pragma user_version='' + sys.argv[3]); c.commit(); c.close()', $path, $ddlF, "$Va") -What 'mkdb auth (release DDL)' }
  $mk = { param($path, $ver) $ddl = if ($ver -ge 3) { ($seedT | ForEach-Object { "c.execute('create table if not exists $_(x)'); " }) -join '' } else { '' }
          $null = Invoke-V2Native -Exe $Py -ArgList @('-c', "import sqlite3; c=sqlite3.connect(r'$path'); c.execute('create table if not exists t(x)'); $ddl c.execute('pragma user_version=$ver'); c.commit(); c.close()") -What 'mkdb' }
  function New-DataSet([string]$dir) { & $mk (Join-Path $dir 'integrity_v2.db') $Vi; Set-Content (Join-Path $dir 'integrity_v2.db-wal') 'wal'; Set-Content (Join-Path $dir 'integrity_v2.db-shm') 'shm'; & $mkA (Join-Path $dir 'v2_auth.db') }
  New-DataSet $d3
  $bkd = Join-Path $tmp 'backups3'; $null = New-Item -ItemType Directory $bkd
  $srcI = Join-Path $tmp 'srcI.db'; & $mk $srcI $Vi; $srcA = Join-Path $tmp 'srcA.db'; & $mkA $srcA
  $bkI = Join-Path $bkd 'integrity_v2.db'; $null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-I', $dbTool, 'backup', $srcI, $bkI, '--expect-version', "$Vi") -What 'mkbackup I'
  $bkA = Join-Path $bkd 'v2_auth.db'; $null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-I', $dbTool, 'backup', $srcA, $bkA, '--expect-version', "$Va") -What 'mkbackup A'
  $shaI = (Get-FileHash -LiteralPath $bkI -Algorithm SHA256).Hash.ToLower(); $shaA = (Get-FileHash -LiteralPath $bkA -Algorithm SHA256).Hash.ToLower()
  function New-Items { @(@{ Db = 'integrity_v2.db'; Backup = $bkI; Sha256 = $shaI; Version = $Vi }, @{ Db = 'v2_auth.db'; Backup = $bkA; Sha256 = $shaA; Version = $Va }) }
  $items = New-Items
  function Get-State([string]$dir) { (@(Get-ChildItem -LiteralPath $dir -File | ForEach-Object Name | Sort-Object) -join ',') }
  function Set-Proof($tree, [int]$unres = 0) { $global:Fake.Job = @{ Found = $true; SdOk = $true; LimitsOk = $true; Active = 0; Pids = @(); Alive = @(); Unknown = @(); TerminateWorks = $true; HoldFails = $false }; $V2StopProof['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; Tree = $tree; Unresolved = $unres; VerifiedUtc = [datetime]::UtcNow
                                                Completeness = 'job'; JobVerified = $true; JobName = 'Global\integrity-v2-backend-job'; JobActive = 0; OwnerScanAlive = 0; Lease = 'HOLDER' } }
  $before3 = Get-State $d3
  $V2Services['integrity-v2-backend'].Job = 'Global\integrity-v2-backend-job'
  $savedRoot = $V2Root; $V2Root = $r3; $V2AppRelease = 'integrity-v2-sim'          # каталог релізу: Invoke-V2Py тут підмінено
  $known3 = @([pscustomobject]@{ Pid = 500; StartUtcTicks = $T0.Ticks; Exe = $svcExe; CommandLine = ''; ParentPid = 1; ParentStartUtcTicks = 0; Owner = $acct; Handle = $null })
  try {
    Reset-Fake; $V2StopProof.Clear()
    $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known $known3 -Py $Py -DbTool $dbTool -Items $items }
    Add-Res 'D3a' ($m -like 'STOP:*немає доказу зупинки backend*' -and (Get-State $d3) -eq $before3) 'B3: без доказу Stop-V2Service відкат заборонено, навіть якщо збережені ідентичності завершились; файли не змінено'
    Set-Proof $null; $null = New-FakeProc 500 1 0 $svcExe $acct
    $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known $known3 -Py $Py -DbTool $dbTool -Items $items }
    Add-Res 'D3b' ($m -like 'STOP:*досі працює*' -and (Get-State $d3) -eq $before3) 'доказ без дерева + збережений процес backend живий → STOP; файли не змінено'
    Reset-Fake; Set-Proof $null; $null = New-FakeProc 500 1 0 $svcExe $acct; $null = New-FakeProc 530 500 5 'C:\py\python.exe' $acct; $global:Fake.Procs[500].Exited = $true
    $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known $known3 -Py $Py -DbTool $dbTool -Items $items }
    Add-Res 'D3c' ($m -like 'STOP:*пізні нащадки 530*' -and (Get-State $d3) -eq $before3) 'корінь завершився, але живий пізній нащадок → STOP (дозвіл лише після завершення ПОВНОГО дерева)'
    Reset-Fake; Set-Proof $null
    $bad = New-Items; $bad[1].Sha256 = ('0' * 64)
    $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known $known3 -Py $Py -DbTool $dbTool -Items $bad }
    Add-Res 'D3d' ($m -like 'STOP:*SHA256*' -and (Get-State $d3) -eq $before3) 'SHA256 другої копії ≠ записаному → STOP до змін (перевіряються ВСІ копії); маркерів немає'
    Reset-Fake; Set-Proof $known3
    $global:Fake.Job.Alive = @(@{ pid = 777; name = 'late-service-process' })
    $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }
    Add-Res 'B03.late-sid' ($m -like 'STOP:*свіжий service-SID scan*' -and (Get-State $d3) -eq $before3 -and -not @(Get-ChildItem -LiteralPath $d3 -Filter 'RESTORE-*').Count) 'новий процес відповідного service SID після stop proof → жодної DB mutation'
    # ---- B3: валідація набору до будь-якої мутації (стан data\ і маркери не змінюються)
    $kc = @(
      @('K1', 'одна БД замість двох', { , @((New-Items)[0]) }, '*рівно 2 БД*'),
      @('K2', 'три елементи', { $x = New-Items; @($x[0], $x[1], $x[1]) }, '*рівно 2 БД*'),
      @('K3', 'дубль БД integrity_v2.db', { $x = New-Items; $x[1].Db = 'integrity_v2.db'; $x[1].Version = $Vi; $x }, '*integrity_v2.db указано двічі*'),
      @('K4', 'дубль БД з іншим регістром', { $x = New-Items; $x[1].Db = 'INTEGRITY_V2.db'; $x[1].Version = $Vi; $x }, '*указано двічі*'),
      @('K5', 'integrity_v2.db з user_version 1', { $x = New-Items; $x[0].Version = 1; $x }, "*integrity_v2.db — user_version 1, потрібно $Vi*"),
      @('K6', "v2_auth.db з user_version $($Va + 1)", { $x = New-Items; $x[1].Version = $Va + 1; $x }, "*v2_auth.db — user_version $($Va + 1), потрібно $Va*"),
      @('K7', 'версія рядком', { $x = New-Items; $x[0].Version = "$Vi"; $x }, "*user_version $Vi, потрібно $Vi*"),
      @('K8', 'один шлях копії для обох БД', { $x = New-Items; $x[1].Backup = $bkI; $x }, '*указано для двох БД*'),
      @('K9', 'той самий шлях в іншому записі (регістр, ..)', { $x = New-Items; $x[1].Backup = (Join-Path $bkd '..\backups3\INTEGRITY_V2.DB'); $x }, '*указано для двох БД*'),
      @('K10', 'невідома БД', { $x = New-Items; $x[1].Db = 'other.db'; $x }, '*невідома БД*'),
      @('K11', 'копія всередині data\', { $x = New-Items; $x[1].Backup = (Join-Path $d3 'v2_auth.db'); $x }, '*лежить у data*'),
      @('K12', 'відносний шлях копії', { $x = New-Items; $x[1].Backup = 'v2_auth.db'; $x }, '*не абсолютний*'),
      @('K13', 'SHA256 не 64 hex', { $x = New-Items; $x[0].Sha256 = 'abc'; $x }, '*не 64 hex*'),
      @('K14', 'копії не існує', { $x = New-Items; $x[1].Backup = (Join-Path $bkd 'missing.db'); $x }, '*копії*немає*'))
    foreach ($c in $kc) {
      Reset-Fake; Set-Proof $known3
      $set = & $c[2]
      $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known @() -Py $Py -DbTool $dbTool -Items $set }
      Add-Res $c[0] ($m -like "STOP:$($c[3])" -and (Get-State $d3) -eq $before3) "B3 набір: $($c[1]) → STOP до будь-якої мутації; data\ без змін, маркерів немає"
    }
    Reset-Fake; Set-Proof $known3 1
    Add-Res 'K15' ((Test-Stop { Invoke-V2DbRestore -DataDir $d3 -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } '*доказ зупинки backend невалідний*') -and (Get-State $d3) -eq $before3) 'B3: доказ із нерозв''язаними нащадками → невалідний → STOP'
    Reset-Fake; Set-Proof $known3
    $global:Fake.Services['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; State = 'Running'; StartMode = 'Manual'; StartName = $acct; PathName = "`"$svcExe`""; ProcessId = 777 }
    Add-Res 'K16' ((Test-Stop { Invoke-V2DbRestore -DataDir $d3 -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } '*integrity-v2-backend зараз Running*') -and (Get-State $d3) -eq $before3) 'B3: служба backend знову Running після доказу → STOP'
    # ---- частковий провал: integrity_v2.db уже відновлено, копіювання v2_auth.db падає → .broken-* збережено, маркер FAILED, старт заборонено
    Reset-Fake; Set-Proof $known3
    $origDbTool = (Get-Item function:Invoke-V2DbTool).ScriptBlock
    Set-Item function:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) if ($ArgList[0] -eq 'backup' -and $ArgList[2] -like '*v2_auth.db') { Stop-V2 'v2_db_tool backup → код 1 (тест: збій копіювання v2_auth)' }; & $origDbTool -Py $Py -DbTool $DbTool -ArgList $ArgList }
    try { $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } } finally { Set-Item function:Invoke-V2DbTool $origDbTool }
    $st = Get-State $d3; $names = $st -split ','
    Add-Res 'D3e' ($m -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*збій копіювання v2_auth*integrity_v2.db ←*' -and $st -match 'integrity_v2\.db\.broken-' -and $st -match 'db-wal\.broken-' -and $st -match 'db-shm\.broken-' -and $st -match 'v2_auth\.db\.broken-' -and $names -contains 'integrity_v2.db' -and $names -notcontains 'v2_auth.db' -and $st -match 'RESTORE-FAILED-' -and $st -notmatch 'RESTORE-IN-PROGRESS') 'частковий збій (перша БД відновлена, друга — ні) → STOP; усі *.broken-<ts> збережено; маркер RESTORE-FAILED із переліком виконаного'
    Add-Res 'D3f' (Test-Stop { Assert-V2NoRestoreBlock -DataDir $d3 } '*старт backend заборонено*') 'після невдалого відновлення старт backend заборонено'
    $global:Fake.Services['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; State = 'Stopped'; StartMode = 'Manual'; StartName = $acct; PathName = "`"$svcExe`""; ProcessId = 0 }
    $script:startCalls = 0
    $m = Get-StopMessage { Invoke-V2ServiceStart -Name 'integrity-v2-backend' -Starter { param($n) $script:startCalls++ } -Stopper { param($n) } -Checks { 'PASS' } }
    Add-Res 'D3g' ($m -like 'STOP:*старт backend заборонено*' -and $script:startCalls -eq 0) 'Invoke-V2ServiceStart (стандартний PreCheck) для backend → STOP; sc start не викликається'
    $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3 -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }
    Add-Res 'D3h' ($m -like 'STOP:*старт backend заборонено*відновлення БД не завершено або невдале*') 'повторне відновлення поверх невдалого → STOP (лише рішенням №5)'
    # ---- успіх (перевірка схеми тут підмінена; справжня — у rehearse-rev3.ps1 R9)
    $d3b = Join-Path $r3 'data-ok'; $null = New-Item -ItemType Directory $d3b; New-DataSet $d3b
    Reset-Fake; Set-Proof $known3
    $origPy = (Get-Item function:Invoke-V2Py).ScriptBlock
    $global:SchemaEnv = $null
    Set-Item function:Invoke-V2Py { param([string]$Py, [string]$Backend, [string[]]$ArgList, [string]$What) $global:SchemaEnv = "$(Get-V2EnvVar 'INTEGRITY_DB')|$(Get-V2EnvVar 'V2_AUTH_DB')"; 'SCHEMA OK' }
    try { $r = @(Invoke-V2DbRestore -DataDir $d3b -Known @() -Py $Py -DbTool $dbTool -Items (New-Items)) } finally { Set-Item function:Invoke-V2Py $origPy }
    $st = Get-State $d3b
    $verI = Invoke-V2DbTool -Py $Py -DbTool $dbTool -ArgList @('verify', (Join-Path $d3b 'integrity_v2.db'), '--expect-version', "$Vi")
    $verA = Invoke-V2DbTool -Py $Py -DbTool $dbTool -ArgList @('verify', (Join-Path $d3b 'v2_auth.db'), '--expect-version', "$Va")
    Add-Res 'D3i' ($r[0] -like 'PASS*набір відновлення*' -and $r[-1] -like 'PASS*відновлення завершено*' -and $st -match 'RESTORE-OK-' -and $st -notmatch 'RESTORE-(IN-PROGRESS|FAILED)' -and $st -match 'db-wal\.broken-' -and $st -match 'v2_auth\.db\.broken-' -and $verI -like 'VERIFY OK*' -and $verA -like 'VERIFY OK*' -and (@(Assert-V2NoRestoreBlock -DataDir $d3b))[-1] -like 'PASS*') 'успіх (доказ з деревом з 1 процесу): обидві БД verify OK, .broken-* збережено, RESTORE-OK, старт не заблоковано'
    Add-Res 'D3k' ($global:SchemaEnv -eq "$(Join-Path $d3b 'integrity_v2.db')|$(Join-Path $d3b 'v2_auth.db')" -and $null -eq (Get-V2EnvVar 'INTEGRITY_DB') -and $null -eq (Get-V2EnvVar 'V2_AUTH_DB')) 'B3: перевірка схеми запускається з INTEGRITY_DB/V2_AUTH_DB = відновлені файли data\ (а не БД за замовчуванням); env після неї відновлено'
    $d3c = Join-Path $r3 'data-schema'; $null = New-Item -ItemType Directory $d3c; New-DataSet $d3c
    Set-Proof $known3
    Set-Item function:Invoke-V2Py { param([string]$Py, [string]$Backend, [string[]]$ArgList, [string]$What) Stop-V2 'schema check → код 1 (тест)' }
    try { $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $d3c -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } } finally { Set-Item function:Invoke-V2Py $origPy }
    Add-Res 'D3j' ($m -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*schema*' -and (Get-State $d3c) -match 'RESTORE-FAILED-' -and (Test-Stop { Assert-V2NoRestoreBlock -DataDir $d3c } '*заборонено*')) 'перевірка схеми після копіювання не пройшла → FAILED, старт заборонено'
    # ================================================================ R01–R14 (етап 3) — відкат: доказ рівня job, строга схема auth, часткові збої
    $noMut = { param($d, $b) (Get-State $d) -eq $b -and -not @(Get-ChildItem -LiteralPath $d -Filter 'RESTORE-*').Count }
    Reset-Fake; $V2StopProof.Clear(); Set-Proof $known3; $V2StopProof['integrity-v2-backend'].Completeness = 'tree-only'; $V2StopProof['integrity-v2-backend'].JobVerified = $false
    $dR = Join-Path $r3 'data-r05'; $null = New-Item -ItemType Directory $dR; New-DataSet $dR; $bR = Get-State $dR
    Add-Res 'R05.treeonly' ((Test-Stop { Invoke-V2DbRestore -DataDir $dR -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } '*без моделі повноти*P4 BLOCKED*') -and (& $noMut $dR $bR)) 'доказ лише «tree-only» (без Job Object) → відкат BLOCKED до мутації'
    Set-Proof $known3; $V2StopProof['integrity-v2-backend'].JobActive = 1
    Add-Res 'R05.jobactive' ((Test-Stop { Invoke-V2DbRestore -DataDir $dR -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } '*без моделі повноти*') -and (& $noMut $dR $bR)) 'доказ із JobActive ≠ 0 → BLOCKED'
    Set-Proof $known3; $V2StopProof['integrity-v2-backend'].OwnerScanAlive = 2
    Add-Res 'R05.ownerscan' ((Test-Stop { Invoke-V2DbRestore -DataDir $dR -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } '*без моделі повноти*') -and (& $noMut $dR $bR)) 'доказ із живими процесами акаунта → BLOCKED'
    # R06 — одна з копій пошкоджена / неповна → STOP до мутації
    $bad06 = Join-Path $tmp 'auth-incomplete.db'; & $mk $bad06 $Va                                     # версія auth релізу, але без таблиць V2
    $x = New-Items; $x[1].Backup = $bad06; $x[1].Sha256 = (Get-FileHash -LiteralPath $bad06 -Algorithm SHA256).Hash.ToLower()
    Set-Proof $known3
    Add-Res 'R06.auth-incomplete' ((Test-Stop { Invoke-V2DbRestore -DataDir $dR -Known @() -Py $Py -DbTool $dbTool -Items $x } '*auth-schema: FAIL A05*') -and (& $noMut $dR $bR)) 'неповна копія v2_auth.db (user_version релізу, без таблиць) → строгий checker STOP до мутації; RESTORE-OK неможливий'
    $bad06b = Join-Path $tmp 'integrity-corrupt.db'; Copy-Item -LiteralPath $bkI -Destination $bad06b
    $bytes = [IO.File]::ReadAllBytes($bad06b); for ($q = 0; $q -lt 16; $q++) { $bytes[$q] = 0x41 }; [IO.File]::WriteAllBytes($bad06b, $bytes)
    $x = New-Items; $x[0].Backup = $bad06b; $x[0].Sha256 = (Get-FileHash -LiteralPath $bad06b -Algorithm SHA256).Hash.ToLower()
    Add-Res 'R06.integrity-corrupt' ((Test-Stop { Invoke-V2DbRestore -DataDir $dR -Known @() -Py $Py -DbTool $dbTool -Items $x }) -and (& $noMut $dR $bR)) 'пошкоджена копія integrity_v2.db (SHA збігається із записаним) → verify STOP до мутації'
    # R07/R08 — збої першої/другої операції перейменування чи копіювання → FAILED, .broken-* збережено
    function Invoke-R78([string]$tag, [scriptblock]$inject, [scriptblock]$undo) {
      $dd = Join-Path $r3 "data-$tag"; $null = New-Item -ItemType Directory $dd; New-DataSet $dd
      Reset-Fake; Set-Proof $known3
      & $inject
      try { $mm = Get-StopMessage { Invoke-V2DbRestore -DataDir $dd -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } } finally { & $undo }
      @{ M = $mm; S = (Get-State $dd); D = $dd }
    }
    # Rename-Item: одна обгортка на весь блок R (лише тест); збій вмикається $global:RenameFail = { param($path) … } і скидається після сценарію
    $global:RenameFail = $null; $script:rn = 0
    Set-Item function:script:Rename-Item { [CmdletBinding()] param([string]$LiteralPath, [string]$NewName) if ($global:RenameFail -and (& $global:RenameFail $LiteralPath)) { throw "rename denied (тест: $LiteralPath)" }; Microsoft.PowerShell.Management\Rename-Item -LiteralPath $LiteralPath -NewName $NewName -ErrorAction Stop }
    $undoRn = { $global:RenameFail = $null }
    $r = Invoke-R78 'r07a' { $script:rn = 0; $global:RenameFail = { param($x) if ($x -match '\.db(-wal|-shm|-journal)?$') { $script:rn++; $script:rn -eq 1 } else { $false } } } $undoRn
    Add-Res 'R07.rename1' ($r.M -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*rename denied*' -and $r.S -match 'RESTORE-FAILED-' -and $r.S -notmatch 'RESTORE-OK' -and $r.S -match '(^|,)integrity_v2\.db(,|$)') 'збій ПЕРШОГО перейменування → FAILED; файли на місці; старт заблоковано маркером'
    $origDbTool7 = (Get-Item function:Invoke-V2DbTool).ScriptBlock
    $undoTool = { Set-Item function:script:Invoke-V2DbTool $origDbTool7 }
    $r = Invoke-R78 'r07b' { Set-Item function:script:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) if ($ArgList[0] -eq 'backup' -and $ArgList[2] -like '*integrity_v2.db') { Stop-V2 'v2_db_tool backup → код 1 (тест: збій першого копіювання)' }; & $origDbTool7 -Py $Py -DbTool $DbTool -ArgList $ArgList } } $undoTool
    Add-Res 'R07.copy1' ($r.M -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*першого копіювання*' -and $r.S -match 'integrity_v2\.db\.broken-' -and $r.S -match 'RESTORE-FAILED-' -and $r.S -notmatch '(^|,)integrity_v2\.db(,|$)') 'збій ПЕРШОГО копіювання → FAILED; integrity_v2.db.broken-* збережено'
    $r = Invoke-R78 'r08a' { $global:RenameFail = { param($x) $x -match 'v2_auth\.db$' } } $undoRn
    Add-Res 'R08.rename2' ($r.M -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*rename denied (тест:*v2_auth.db)*integrity_v2.db ←*' -and $r.S -match 'integrity_v2\.db\.broken-' -and $r.S -match 'RESTORE-FAILED-' -and (Test-Stop { Assert-V2NoRestoreBlock -DataDir $r.D })) 'збій перейменування ДРУГОЇ БД після відновлення першої → FAILED; .broken-* збережено; старт заборонено'
    # R09 — неправильна відновлена схема auth (checker на відновленому файлі) → FAILED
    $r = Invoke-R78 'r09' { Set-Item function:script:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) if ($ArgList[0] -eq 'auth-schema' -and $ArgList[1] -notlike '*backups3*') { Stop-V2 'v2_db_tool auth-schema → код 1: STOP: auth-schema: FAIL A06 (тест)' }; & $origDbTool7 -Py $Py -DbTool $DbTool -ArgList $ArgList } } $undoTool
    Add-Res 'R09.auth' ($r.M -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*auth-schema: FAIL A06*' -and $r.S -match 'RESTORE-FAILED-' -and $r.S -notmatch 'RESTORE-OK') 'відновлена v2_auth.db не пройшла строгу перевірку схеми → FAILED (не OK)'
    Remove-Item function:script:Rename-Item; $global:RenameFail = $null
    # ================================================================ auditfix2: W1–W5 (SQLITE_WRITER_EXCLUSION_DESIGN.md) і життєвий цикл lease/proof у відкаті
    function Set-FakeBackendSvc([string]$Mode = 'Manual', [string]$State = 'Stopped') { $global:Fake.Services['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; State = $State; StartMode = $Mode; StartName = $acct; PathName = "`"$svcExe`""; ProcessId = $(if ($State -eq 'Running') { 4242 } else { 0 }) } }
    function New-WData([string]$tag) { $dd = Join-Path $r3 "data-$tag"; $null = New-Item -ItemType Directory $dd; New-DataSet $dd; $dd }
    $origPyW = (Get-Item function:Invoke-V2Py).ScriptBlock; $origToolW = (Get-Item function:Invoke-V2DbTool).ScriptBlock
    function Undo-W { Set-Item function:script:Invoke-V2Py $origPyW; Set-Item function:script:Invoke-V2DbTool $origToolW; $global:WHook = $null; $global:PyHook = $null }
    Set-Item function:script:Invoke-V2Py { param([string]$Py, [string]$Backend, [string[]]$ArgList, [string]$What) if ($global:PyHook) { & $global:PyHook }; 'SCHEMA OK' }
    Set-Item function:script:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) $global:Fake.Seq.Add("db $($ArgList[0])"); $o = & $origToolW -Py $Py -DbTool $DbTool -ArgList $ArgList; if ($global:WHook -and $ArgList[0] -eq 'verify' -and $ArgList[1] -notlike '*backups3*') { & $global:WHook }; $o }
    $global:WHook = $null; $global:PyHook = $null
    function Get-LeaseReleased { @($global:Fake.JobCalls | Where-Object { $_ -eq 'release' }).Count -ge 1 -and -not $V2StopProof.ContainsKey('integrity-v2-backend') }
    function Get-SeqIndex([string]$like, [int]$from = 0) { if ($from -lt 0) { return -1 }; $q = @($global:Fake.Seq); for ($z = $from; $z -lt $q.Count; $z++) { if ($q[$z] -like $like) { return $z } }; -1 }
    try {
      # W.ok — порядок: Disabled → scan (W2) → перша мутація → W5 scan → Manual; RESTORE-OK; lease звільнено, proof видалено
      $dW = New-WData 'w-ok'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      try { $r = @(Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items)) } catch { $r = @("STOP-CAUGHT: $($_.Exception.Message)") }   # відмова → чистий FAIL W.ok, а не обрив набору
      $iD = Get-SeqIndex 'startmode Disabled'; $iS1 = Get-SeqIndex 'job proof*--scan-sid*' $iD; $iB = Get-SeqIndex 'db backup' $iS1; $iS2 = Get-SeqIndex 'job proof*--scan-sid*' ($iB + 1); $iM = Get-SeqIndex 'startmode Manual' $iS2
      Add-Res 'W.ok' ($iD -ge 0 -and $iS1 -gt $iD -and $iB -gt $iS1 -and $iS2 -gt $iB -and $iM -gt $iS2 -and (Get-State $dW) -match 'RESTORE-OK-' -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Manual' -and (Get-LeaseReleased)) "W1→W2→мутація→W5→Manual (індекси $iD<$iS1<$iB<$iS2<$iM); RESTORE-OK; lease звільнено, proof видалено"
      Add-Res 'W.ok-out' ((@($r | Where-Object { $_ -like 'PASS  W1:*' }).Count -eq 1) -and (@($r | Where-Object { $_ -like 'PASS  W5:*' }).Count -eq 1)) 'вивід відкату містить W1 і W5 PASS'
      # W1.fail — start type не змінено → STOP до мутації; спроба повернення; lease звільнено
      $dW = New-WData 'w1-fail'; $bW = Get-State $dW; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc; $global:Fake.StartModeFail = 'Disabled'
      $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }
      Add-Res 'W1.fail' ($m -like 'STOP:*start type*' -and (& $noMut $dW $bW) -and (Get-SeqIndex 'db backup') -lt 0 -and (Get-SeqIndex 'startmode Manual') -ge 0 -and (Get-LeaseReleased)) 'W1: start type не підтверджено → STOP до мутації; start type повертається; lease звільнено'
      # W1.running — служба не зупинена → STOP, start type не чіпається
      $dW = New-WData 'w1-run'; $bW = Get-State $dW; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc -State Running
      $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }
      Add-Res 'W1.running' ($m -like 'STOP:*зараз Running*' -and (& $noMut $dW $bW) -and (Get-SeqIndex 'startmode*') -lt 0 -and (Get-LeaseReleased)) 'служба backend Running → STOP до W1 і мутації; lease звільнено'
      # W2.after — живий процес service SID у фінальному scan (уже після W1) → STOP до мутації; Disabled→Manual повернуто
      $dW = New-WData 'w2'; $bW = Get-State $dW; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc; $global:Fake.Job.Alive = @(@{ pid = 901; name = 'python.exe' })
      $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }
      $iD = Get-SeqIndex 'startmode Disabled'; $iS = Get-SeqIndex 'job proof*--scan-sid*'
      Add-Res 'W2.after' ($m -like 'STOP:*свіжий service-SID scan*' -and $iD -ge 0 -and $iS -gt $iD -and (& $noMut $dW $bW) -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Manual' -and (Get-LeaseReleased)) "фінальний scan ПІСЛЯ W1 ($iD<$iS) виявив процес → STOP до мутації; start type повернуто Manual; lease звільнено"
      # W5.* — втручання під час відкату → FAILED (не OK); start type лишається Disabled; lease звільнено
      foreach ($w5 in @(@('W5.startmode', { $global:Fake.Services['integrity-v2-backend'].StartMode = 'Manual' }, '*W5: стан служби змінився*'),
                        @('W5.scan', { $global:Fake.Job.Alive = @(@{ pid = 902; name = 'python.exe' }) }, '*W5: процес service SID*'),
                        @('W5.running', { $global:Fake.Services['integrity-v2-backend'].State = 'Running'; $global:Fake.Services['integrity-v2-backend'].ProcessId = 903 }, '*W5: стан служби змінився*'))) {
        $dW = New-WData $w5[0]; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc; $global:WHook = $w5[1]
        $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }; $global:WHook = $null
        $st = Get-State $dW
        Add-Res $w5[0] ($m -like "STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ$($w5[2])" -and $st -match 'RESTORE-FAILED-' -and $st -notmatch 'RESTORE-OK' -and (Get-SeqIndex 'startmode Manual') -lt 0 -and (Get-LeaseReleased)) "$($w5[0]): втручання під час відкату → FAILED; код не повертає Manual; lease звільнено"
      }
      $dW = New-WData 'w5-hash'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      $global:PyHook = [scriptblock]::Create("[IO.File]::AppendAllText('$(Join-Path $dW 'integrity_v2.db')', 'X')")
      $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }; $global:PyHook = $null
      Add-Res 'W5.hash' ($m -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*W5: integrity_v2.db змінено*' -and (Get-State $dW) -match 'RESTORE-FAILED-' -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Disabled' -and (Get-LeaseReleased)) 'файл змінено після копіювання → FAILED; start type лишається Disabled'
      $dW = New-WData 'w5-open'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      $global:WOpen = $null; $global:PyHook = [scriptblock]::Create("`$global:WOpen = [IO.File]::Open('$(Join-Path $dW 'v2_auth.db')', 'Open', 'Read', 'ReadWrite')")
      try { $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) } } finally { if ($global:WOpen) { $global:WOpen.Dispose() }; $global:PyHook = $null }
      Add-Res 'W5.open' ($m -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*файл БД відкритий іншим процесом: v2_auth.db*' -and (Get-State $dW) -match 'RESTORE-FAILED-' -and (Get-LeaseReleased)) 'інший handle на БД наприкінці → FAILED'
      # SC.* (auditfix3, P0): sidecar-и SQLite відновлених БД перед RESTORE-OK. Закритий файл створюється ПІСЛЯ backup, основна .db не змінюється
      #   (W5 SHA256 основних БД проходить → відмову дає саме перевірка sidecar-ів).
      foreach ($sc in @(@('SC.wal', { [IO.File]::WriteAllText("$global:ScDb-wal", ('W' * 64)) }, '*W5 sidecars: integrity_v2.db-wal непорожній (64 B)*'),
                        @('SC.journal', { [IO.File]::WriteAllText("$global:ScDb-journal", ('J' * 512)) }, '*W5 sidecars: integrity_v2.db-journal непорожній (512 B) — hot journal*'),
                        @('SC.shm-rollback', { [IO.File]::WriteAllText("$global:ScDb-shm", '') }, '*W5 sidecars: integrity_v2.db-shm у rollback-режимі*'),
                        @('SC.dir', { $null = New-Item -ItemType Directory -Path "$global:ScDb-wal" -Force }, '*W5 sidecars: integrity_v2.db-wal — не звичайний файл*'))) {
        $dW = New-WData $sc[0]; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
        $global:ScDb = Join-Path $dW 'integrity_v2.db'; $global:WHook = $sc[1]
        $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items) }; $global:WHook = $null
        $st = Get-State $dW
        Add-Res $sc[0] ($m -like "STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ$($sc[2])" -and $m -notlike '*SHA256 ≠*' -and $st -match 'RESTORE-FAILED-' -and $st -notmatch 'RESTORE-OK' -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Disabled' -and (Get-LeaseReleased)) "$($sc[0]): закритий sidecar після backup (основна .db незмінна) → RESTORE-FAILED, а не OK"
      }
      # SC.empty-ok — порожні -wal і -journal (0 B) у rollback-режимі допустимі → RESTORE-OK
      $dW = New-WData 'sc-empty'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      $global:ScDb = Join-Path $dW 'integrity_v2.db'; $global:WHook = { [IO.File]::WriteAllText("$global:ScDb-wal", ''); [IO.File]::WriteAllText("$global:ScDb-journal", '') }
      try { $r = @(Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items)) } catch { $r = @("STOP-CAUGHT: $($_.Exception.Message)") } finally { $global:WHook = $null }
      Add-Res 'SC.empty-ok' ((Get-State $dW) -match 'RESTORE-OK-' -and @($r | Where-Object { $_ -like 'PASS  W5 sidecars integrity_v2.db: режим rollback; -journal 0 B; -wal 0 B; -shm відсутній' }).Count -eq 1) 'порожні -wal/-journal у rollback-режимі → RESTORE-OK; стан sidecar-ів у виводі'
      # SC.rollback-clean — власні перевірки (verify, auth-schema) у rollback-режимі не лишають sidecar-ів
      $dW = New-WData 'sc-clean'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      try { $r = @(Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-Items)) } catch { $r = @("STOP-CAUGHT: $($_.Exception.Message)") }
      Add-Res 'SC.rollback-clean' (@($r | Where-Object { $_ -like 'PASS  W5 sidecars *: режим rollback; -journal відсутній; -wal відсутній; -shm відсутній' }).Count -eq 2) 'власні перевірки відновлених БД (rollback-режим) не лишають жодного sidecar-а'
      # SC.walmode — БД у WAL-режимі: власні read-only перевірки лишають -wal 0 B і -shm → допустимо (RESTORE-OK); непорожній -wal → FAILED
      $walPy = 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(''pragma journal_mode=wal''); c.close()'
      $srcIW = Join-Path $tmp 'srcIW.db'; & $mk $srcIW $Vi; $null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', $walPy, $srcIW) -What 'wal I'
      $srcAW = Join-Path $tmp 'srcAW.db'; & $mkA $srcAW; $null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', $walPy, $srcAW) -What 'wal A'
      $bkdW = Join-Path $tmp 'backups3w'; $null = New-Item -ItemType Directory $bkdW
      $bkIW = Join-Path $bkdW 'integrity_v2.db'; $null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-I', $dbTool, 'backup', $srcIW, $bkIW, '--expect-version', "$Vi") -What 'backup IW'
      $bkAW = Join-Path $bkdW 'v2_auth.db'; $null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-I', $dbTool, 'backup', $srcAW, $bkAW, '--expect-version', "$Va") -What 'backup AW'
      function New-WalItems { @(@{ Db = 'integrity_v2.db'; Backup = $bkIW; Sha256 = (Get-FileHash -LiteralPath $bkIW -Algorithm SHA256).Hash.ToLower(); Version = $Vi }, @{ Db = 'v2_auth.db'; Backup = $bkAW; Sha256 = (Get-FileHash -LiteralPath $bkAW -Algorithm SHA256).Hash.ToLower(); Version = $Va }) }
      $hIW = [IO.File]::ReadAllBytes($bkIW)
      $dW = New-WData 'sc-walmode'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      try { $r = @(Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-WalItems)) } catch { $r = @("STOP-CAUGHT: $($_.Exception.Message)") }
      Add-Res 'SC.walmode-ok' ($hIW[18] -eq 2 -and $hIW[19] -eq 2 -and (Get-State $dW) -match 'RESTORE-OK-' -and @($r | Where-Object { $_ -like 'PASS  W5 sidecars integrity_v2.db: режим wal; -journal відсутній; -wal * B; -shm *' }).Count -eq 1) "WAL-режим (заголовок 2/2): порожній -wal і -shm від власних read-only перевірок допустимі → RESTORE-OK ($(@($r | Where-Object { $_ -like 'PASS  W5 sidecars integrity_v2.db*' }) -join ''))"
      $dW = New-WData 'sc-walmode-bad'; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
      $global:ScDb = Join-Path $dW 'integrity_v2.db'; $global:PyHook = { [IO.File]::WriteAllText("$global:ScDb-wal", ('W' * 32)) }
      $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items (New-WalItems) }; $global:PyHook = $null
      Add-Res 'SC.walmode-nonempty' ($m -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*W5 sidecars: integrity_v2.db-wal непорожній (32 B)*' -and (Get-State $dW) -match 'RESTORE-FAILED-') 'WAL-режим: непорожній закритий -wal після перевірок → RESTORE-FAILED'
      # L.* — lease звільнено й proof видалено на КОЖНОМУ шляху відмови (до і після мутації)
      $cases = @(
        @('L.items', { , @((New-Items)[0]) }, $null, '*рівно 2 БД*'),
        @('L.block', { New-Items }, { param($d) [IO.File]::WriteAllText((Join-Path $d 'RESTORE-FAILED-test.txt'), 'x') }, '*старт backend заборонено*'),
        @('L.permitted', { New-Items }, { param($d) $V2StopProof['integrity-v2-backend'].Completeness = 'tree-only' }, '*без моделі повноти*'),
        @('L.ready', { $x = New-Items; $x[0].Sha256 = ('0' * 64); $x }, $null, '*SHA256*'),
        @('L.auth', { $x = New-Items; $x[1].Backup = $bad06; $x[1].Sha256 = (Get-FileHash -LiteralPath $bad06 -Algorithm SHA256).Hash.ToLower(); $x }, $null, '*auth-schema: FAIL*'),
        @('L.nolease', { New-Items }, { param($d) $V2StopProof['integrity-v2-backend'].Lease = $null }, '*немає чинної proof lease*'),
        @('L.mutation', { New-Items }, { param($d) $global:WHook = { Stop-V2 'тест: збій після мутації' } }, '*ВІДНОВЛЕННЯ НЕВДАЛЕ*тест: збій після мутації*'))
      foreach ($c in $cases) {
        $dW = New-WData $c[0]; Reset-Fake; Set-Proof $known3; Set-FakeBackendSvc
        if ($c[2]) { & $c[2] $dW }
        $set = & $c[1]
        $m = Get-StopMessage { Invoke-V2DbRestore -DataDir $dW -Known @() -Py $Py -DbTool $dbTool -Items $set }; $global:WHook = $null
        $relOk = if ($c[0] -eq 'L.nolease') { -not $V2StopProof.ContainsKey('integrity-v2-backend') } else { Get-LeaseReleased }
        $modeOk = if ($c[0] -eq 'L.mutation') { $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Disabled' } else { $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Manual' }
        Add-Res $c[0] ($m -like "STOP:$($c[3])" -and $relOk -and $modeOk) "$($c[0]): відмова → lease звільнено, proof видалено; start type $(if ($c[0] -eq 'L.mutation') { 'лишається Disabled (була мутація)' } else { 'Manual (мутації не було)' })"
      }
    } finally { Undo-W }
  } finally { $V2Root = $savedRoot; $V2AppRelease = $null; $V2Services['integrity-v2-backend'].Job = $null; $V2StopProof.Clear() }

  # ================================================================ CI.* — CLEAN INSTALL (окремий сценарій; фейкові служби, справжні файли SQLite)
  $ciRoot = Join-Path $tmp 'ci'; $null = New-Item -ItemType Directory $ciRoot
  # --- V1 не обов'язкова
  Reset-Fake
  $b0 = $null; try { $b0 = Get-V1Baseline -AllowAbsent } catch { }   # відмова → чистий FAIL CI.v1-absent, не ERR набору
  Add-Res 'CI.v1-absent' ($null -ne $b0 -and (-not $b0.Present) -and (Assert-V1Unchanged -Baseline $b0) -like 'PASS*' -and (Test-Stop { Get-V1Baseline } '*HacatonBackend не знайдено*')) 'V1 відсутня: -AllowAbsent → порожній baseline, контроль працює; без ключа (сценарій Upgrade) → STOP, як і раніше'
  $global:Fake.Services['HacatonBackend'] = [pscustomobject]@{ Name = 'HacatonBackend'; State = 'Running'; StartMode = 'Auto'; StartName = 'LocalSystem'; PathName = 'C:\v1\HacatonBackend.exe'; ProcessId = 0 }
  $global:Fake.Services['CaddyV1'] = [pscustomobject]@{ Name = 'CaddyV1'; State = 'Running'; StartMode = 'Auto'; StartName = 'LocalSystem'; PathName = 'C:\v1\caddy.exe run'; ProcessId = 0 }
  $b1 = $null; try { $b1 = Get-V1Baseline -AllowAbsent } catch { }
  $global:Fake.Services['HacatonBackend'].State = 'Stopped'
  Add-Res 'CI.v1-present' ($null -ne $b1 -and $b1.Present -and $b1.Services.Count -eq 2 -and (Test-Stop { Assert-V1Unchanged -Baseline $b1 } '*чинні служби змінились*')) 'V1 присутня: baseline фіксує службу і Caddy; зміна стану V1 → STOP'
  # --- Assert-V2DataReady: потрібен позитивний маркер; незавершене/невдале → STOP
  foreach ($rc in @(@('none', @(), $false), @('ok', @('CLEAN-INIT-OK-1.txt'), $true), @('restore-ok', @('RESTORE-OK-1.txt'), $true),
                    @('inprogress', @('CLEAN-INIT-IN-PROGRESS-1.txt'), $false), @('failed', @('CLEAN-INIT-FAILED-1.txt'), $false),
                    @('ok+failed', @('CLEAN-INIT-OK-1.txt', 'CLEAN-INIT-FAILED-2.txt'), $false), @('abandoned', @('CLEAN-INIT-OK-1.txt', 'CLEAN-INIT-FAILED-ABANDONED-3.txt'), $false),
                    @('restore-failed', @('CLEAN-INIT-OK-1.txt', 'RESTORE-FAILED-4.txt'), $false),
                    @('revoked', @('CLEAN-INIT-REVOKED-1.txt'), $false), @('ok+revoked', @('CLEAN-INIT-OK-2.txt', 'CLEAN-INIT-REVOKED-1.txt'), $false),
                    @('ok+failed-install', @('CLEAN-INIT-OK-1.txt', 'CLEAN-INIT-FAILED-INSTALL-5.txt'), $false), @('ok+unknown', @('CLEAN-INIT-OK-1.txt', 'CLEAN-INIT-X-6.txt'), $false))) {
    $dd = Join-Path $ciRoot "ready-$($rc[0])"; $null = New-Item -ItemType Directory $dd
    foreach ($f in $rc[1]) { [IO.File]::WriteAllText((Join-Path $dd $f), 'x') }
    $ok = if ($rc[2]) { (Assert-V2DataReady -DataDir $dd) -like 'PASS*' } else { Test-Stop { Assert-V2DataReady -DataDir $dd } '*старт backend заборонено*' }
    Add-Res "CI.ready-$($rc[0])" $ok "Assert-V2DataReady: $($rc[1] -join ' + ') → $(if ($rc[2]) { 'PASS' } else { 'STOP' })"
  }
  Add-Res 'CI.ready-nodir' (Test-Stop { Assert-V2DataReady -DataDir (Join-Path $ciRoot 'no-such') } '*немає каталогу даних*') 'немає data\ → STOP'
  # --- старт backend стандартним PreCheck без CLEAN-INIT-OK → STOP; sc start не викликається
  $savedRootCi = $V2Root; $V2Root = Join-Path $ciRoot 'srv-start\integrity-v2'; $null = New-Item -ItemType Directory "$V2Root\data"
  Reset-Fake; $global:Fake.Services['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; State = 'Stopped'; StartMode = 'Manual'; StartName = $acct; PathName = "`"$svcExe`""; ProcessId = 0 }
  $script:ciStart = 0
  $m = Get-StopMessage { Invoke-V2ServiceStart -Name 'integrity-v2-backend' -Starter { param($n) $script:ciStart++ } -Stopper { param($n) } -Checks { 'PASS' } }
  Add-Res 'CI.start-blocked' ($m -like '*немає підтвердження ініціалізації БД*' -and $script:ciStart -eq 0) 'порожній/неініціалізований data\ → старт backend заборонено (sc start не викликається)'
  $V2Root = $savedRootCi
  # --- артефакт інструментів
  $tz = Join-Path $ciRoot 'tools.zip'; $tsrc = Join-Path $ciRoot 'tsrc'; $null = New-Item -ItemType Directory "$tsrc\winsw", "$tsrc\caddy"
  [IO.File]::WriteAllText("$tsrc\winsw\integrity-v2-winsw.exe", 'W'); [IO.File]::WriteAllText("$tsrc\caddy\caddy.exe", 'C')
  function New-TestZip([string]$path, [hashtable]$entries) { Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem; $z = [IO.Compression.ZipFile]::Open($path, 'Create'); try { foreach ($k in $entries.Keys) { $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $entries[$k], $k) } } finally { $z.Dispose() } }
  New-TestZip $tz @{ 'winsw/integrity-v2-winsw.exe' = "$tsrc\winsw\integrity-v2-winsw.exe"; 'caddy/caddy.exe' = "$tsrc\caddy\caddy.exe" }
  $exp = [ordered]@{ 'winsw/integrity-v2-winsw.exe' = (Get-FileHash "$tsrc\winsw\integrity-v2-winsw.exe" -Algorithm SHA256).Hash.ToLower(); 'caddy/caddy.exe' = (Get-FileHash "$tsrc\caddy\caddy.exe" -Algorithm SHA256).Hash.ToLower() }
  Add-Res 'CI.tools-ok' ((Expand-V2Tools -ToolsZip $tz -Destination (Join-Path $ciRoot 't-ok') -ExpectedSha256 $exp) -like 'PASS*') 'артефакт інструментів: склад і SHA256 збігаються → PASS (контроль)'
  $bad = [ordered]@{ 'winsw/integrity-v2-winsw.exe' = ('0' * 64); 'caddy/caddy.exe' = $exp['caddy/caddy.exe'] }
  Add-Res 'CI.tools-tamper' (Test-Stop { Expand-V2Tools -ToolsZip $tz -Destination (Join-Path $ciRoot 't-bad') -ExpectedSha256 $bad } '*SHA256 winsw/integrity-v2-winsw.exe ≠ еталону*') 'SHA256 WinSW ≠ еталону → STOP'
  $tz2 = Join-Path $ciRoot 'tools-extra.zip'; New-TestZip $tz2 @{ 'winsw/integrity-v2-winsw.exe' = "$tsrc\winsw\integrity-v2-winsw.exe"; 'caddy/caddy.exe' = "$tsrc\caddy\caddy.exe"; 'extra/evil.exe' = "$tsrc\caddy\caddy.exe" }
  Add-Res 'CI.tools-extra' ((Test-Stop { Expand-V2Tools -ToolsZip $tz2 -Destination (Join-Path $ciRoot 't-extra') -ExpectedSha256 $exp } '*склад артефакту*') -and -not (Test-Path (Join-Path $ciRoot 't-extra'))) 'зайвий запис в артефакті → STOP до розпакування'
  $tz3 = Join-Path $ciRoot 'tools-missing.zip'; New-TestZip $tz3 @{ 'winsw/integrity-v2-winsw.exe' = "$tsrc\winsw\integrity-v2-winsw.exe" }
  Add-Res 'CI.tools-missing' (Test-Stop { Expand-V2Tools -ToolsZip $tz3 -Destination (Join-Path $ciRoot 't-miss') -ExpectedSha256 $exp } '*склад артефакту*') 'відсутній Caddy в артефакті → STOP'
  $tz4 = Join-Path $ciRoot 'tools-trav.zip'; New-TestZip $tz4 @{ '../evil.exe' = "$tsrc\winsw\integrity-v2-winsw.exe" }
  Add-Res 'CI.tools-traversal' ((Test-Stop { Expand-V2Tools -ToolsZip $tz4 -Destination (Join-Path $ciRoot 't-trav') -ExpectedSha256 ([ordered]@{ '../evil.exe' = $exp['winsw/integrity-v2-winsw.exe'] }) } '*поза каталогом*') -and -not (Test-Path (Join-Path $ciRoot 'evil.exe'))) 'запис «../» поза каталогом → STOP, файл поза каталогом не створено'
  Add-Res 'CI.tools-default' ((Test-Stop { Expand-V2Tools -ToolsZip $tz -Destination (Join-Path $ciRoot 't-def') } '*SHA256*≠ еталону*')) 'без перевизначення діють закріплені еталони WinSW 05b82d46… / Caddy 2622e239… → тестові файли відхилено'
  # --- переривання Clean Install (у частині Q діє справжній Invoke-V2Native → на час тестів підміняється фейковим: жодного реального uninstall/sc)
  $realNativeCi = (Get-Item function:Invoke-V2Native).ScriptBlock
  Set-Item function:script:Invoke-V2Native { param([string]$Exe, [string[]]$ArgList = @(), [string]$What = '', [int[]]$OkCodes = @(0), [string]$WorkingDirectory, [switch]$Utf8, [int]$TimeoutSec = 900)
    $global:Fake.Native.Add("$([IO.Path]::GetFileName($Exe)) $($ArgList -join ' ')"); if ($global:Fake.NativeHook) { & $global:Fake.NativeHook $Exe $ArgList } }
  function New-CiSrv([string]$tag) {
    $script:ciRootSrv = Join-Path $ciRoot "srv-$tag\integrity-v2"; $null = New-Item -ItemType Directory "$script:ciRootSrv\data"
    [IO.File]::WriteAllText("$script:ciRootSrv\data\integrity_v2.db", 'x')
    [IO.File]::WriteAllText("$script:ciRootSrv\CLEAN-INSTALL-FAILED-1.txt", 'synthetic failed install')
    [IO.File]::WriteAllText("$script:ciRootSrv\data\CLEAN-INIT-FAILED-INSTALL-1.txt", 'synthetic failed init')
    Reset-Fake
    foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy') { $global:Fake.Services[$n] = [pscustomobject]@{ Name = $n; State = 'Stopped'; StartMode = 'Manual'; StartName = $V2Services[$n].Account; PathName = "`"$($V2Services[$n].Exe)`""; ProcessId = 0 } }
  }
  New-CiSrv 'ok'; $V2Root = $script:ciRootSrv
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'uninstall') { foreach ($n in @($global:Fake.Services.Keys)) { if ($V2Services[$n].Exe -eq $e) { $global:Fake.Services.Remove($n) } } } }
  try { $r = @(Invoke-V2CleanInstallAbort -Reason 'тест') } catch { $r = @("ERR: $($_.Exception.Message)") } finally { $V2Root = $savedRootCi }   # відмова → чистий FAIL CI.abort-ok
  $ab = @(Get-ChildItem (Split-Path $script:ciRootSrv) -Directory | ForEach-Object Name)
  $abd = Join-Path (Split-Path $script:ciRootSrv) ($ab | Where-Object { $_ -like 'integrity-v2-abandoned-*' } | Select-Object -First 1)
  Add-Res 'CI.abort-ok' (-not (Test-Path $script:ciRootSrv) -and @($ab | Where-Object { $_ -like 'integrity-v2-abandoned-*' }).Count -eq 1 -and @(Get-ChildItem "$abd\data" -Filter 'CLEAN-INIT-FAILED-ABANDONED-*').Count -eq 1 -and -not $global:Fake.Services.Count -and (Test-Stop { Assert-V2DataReady -DataDir "$abd\data" })) 'переривання: служби V2 зупинено й видалено; корінь → -abandoned-<ts>; БД позначено ABANDONED (старт неможливий)'
  New-CiSrv 'stuck'; $V2Root = $script:ciRootSrv
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'uninstall' -and $e -eq $V2Services['integrity-v2-caddy'].Exe) { $global:Fake.Services.Remove('integrity-v2-caddy') } }
  try { $m = Get-StopMessage { Invoke-V2CleanInstallAbort -Reason 'тест' } } finally { $V2Root = $savedRootCi }
  Add-Res 'CI.abort-stuck' ($m -like '*ПЕРЕРИВАННЯ НЕ ЗАВЕРШЕНО*integrity-v2-backend досі встановлено*' -and (Test-Path $script:ciRootSrv)) 'служба лишилась після uninstall → STOP; корінь НЕ перейменовано (рішення №5)'
  New-CiSrv 'ready'; $V2Root = $script:ciRootSrv
  Remove-Item -LiteralPath "$script:ciRootSrv\CLEAN-INSTALL-FAILED-1.txt", "$script:ciRootSrv\data\CLEAN-INIT-FAILED-INSTALL-1.txt"
  [IO.File]::WriteAllText("$script:ciRootSrv\data\CLEAN-INIT-OK-1.txt", 'ready')
  try { $m = Get-StopMessage { Invoke-V2CleanInstallAbort -Reason 'тест' } } finally { $V2Root = $savedRootCi }
  Add-Res 'CI.abort-ready' ($m -like 'STOP:*немає маркера невдалого встановлення*' -and (Test-Path $script:ciRootSrv) -and $global:Fake.Services.Count -eq 2 -and -not @($global:Fake.Native | Where-Object { $_ -like '* stop *' -or $_ -like '* uninstall*' }).Count) 'Abort працюючого/готового встановлення без failed-маркера → STOP до будь-якого stop/uninstall'
  New-CiSrv 'foreign'; $V2Root = $script:ciRootSrv
  $global:Fake.Services['integrity-v2-caddy'].PathName = 'C:\foreign\caddy.exe'
  try { $m = Get-StopMessage { Invoke-V2CleanInstallAbort -Reason 'тест' } } finally { $V2Root = $savedRootCi }
  Add-Res 'CI.abort-foreign' ($m -like 'STOP:*PathName*integrity-v2-caddy*' -and (Test-Path $script:ciRootSrv) -and $global:Fake.Services.Count -eq 2 -and -not @($global:Fake.Native | Where-Object { $_ -like '* stop *' -or $_ -like '* uninstall*' }).Count) 'Abort зі сторонньою однойменною службою → STOP до будь-якого stop/uninstall'
  $V2Services['integrity-v2-backend'].Job = 'Global\x'
  try { Add-Res 'CI.abort-job' (Test-Stop { Invoke-V2CleanInstallAbort -Reason 'тест' } '*не використовує Job Object*') 'Clean Install з увімкненим Job Object → STOP' } finally { $V2Services['integrity-v2-backend'].Job = $null }
  Set-Item function:script:Invoke-V2Native $realNativeCi
  # Stop-V2Service для Caddy (раніше: помилка StrictMode через відсутнє поле Job у записі Caddy)
  Reset-Fake; $global:Fake.Services['integrity-v2-caddy'] = [pscustomobject]@{ Name = 'integrity-v2-caddy'; State = 'Stopped'; StartMode = 'Manual'; StartName = 'NT SERVICE\integrity-v2-caddy'; PathName = "`"$($V2Services['integrity-v2-caddy'].Exe)`""; ProcessId = 0 }
  try { $r = @(Stop-V2Service -Name 'integrity-v2-caddy') } catch { $r = @("ERR: $($_.Exception.Message)") }
  Add-Res 'CI.stop-caddy' ($r[-1] -like 'PASS*integrity-v2-caddy зупинено*' -and $V2StopProof['integrity-v2-caddy'].Completeness -eq 'tree-only') 'Stop-V2Service для Caddy працює (поле Job явно $null) — автозупинка/переривання Caddy можливі'
  $V2StopProof.Clear()
  # --- CI-01: пізній збій ПІСЛЯ CLEAN-INIT-OK (етапи 4.6 / 4.7 / 5) → Invoke-V2CleanInstallFailClosed інвалідує READY
  $realNativeLate = (Get-Item function:Invoke-V2Native).ScriptBlock          # тут діє справжній Invoke-V2Native → фейк: жодного реального sc
  Set-Item function:script:Invoke-V2Native { param([string]$Exe, [string[]]$ArgList = @(), [string]$What = '', [int[]]$OkCodes = @(0), [string]$WorkingDirectory, [switch]$Utf8, [int]$TimeoutSec = 900)
    $global:Fake.Native.Add("$([IO.Path]::GetFileName($Exe)) $($ArgList -join ' ')"); if ($global:Fake.NativeHook) { & $global:Fake.NativeHook $Exe $ArgList } }
  function New-LateRoot([string]$tag, [hashtable]$svc) {
    $script:lateRoot = Join-Path $ciRoot "late-$tag\integrity-v2"; $null = New-Item -ItemType Directory "$script:lateRoot\data", "$script:lateRoot\backups"
    foreach ($f in 'integrity_v2.db', 'v2_auth.db') { [IO.File]::WriteAllText("$script:lateRoot\data\$f", "db-$tag-$f") }
    [IO.File]::WriteAllText("$script:lateRoot\data\CLEAN-INIT-OK-20261119-000000.txt", 'ok')
    [IO.File]::WriteAllText("$script:lateRoot\backups\integrity_v2-initial-1.db", 'bk')
    Reset-Fake; $V2Identity.Clear(); $V2StopProof.Clear(); $p = 700
    foreach ($n in $svc.Keys) {
      $run = $svc[$n] -eq 'Running'; $p++
      $global:Fake.Services[$n] = [pscustomobject]@{ Name = $n; State = $svc[$n]; StartMode = 'Manual'; StartName = $V2Services[$n].Account; PathName = "`"$($V2Services[$n].Exe)`""; ProcessId = $(if ($run) { $p } else { 0 }) }
      if ($run) { $null = New-FakeProc $p 1 0 $V2Services[$n].Exe $V2Services[$n].Account }
    }
    $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { $sv = $global:Fake.Services[$a[1]]; if ($sv) { if ($sv.ProcessId -and $global:Fake.Procs[[int]$sv.ProcessId]) { $global:Fake.Procs[[int]$sv.ProcessId].Exited = $true }; $sv.State = 'Stopped'; $sv.ProcessId = 0 } } }
    @(Get-ChildItem "$script:lateRoot\data", "$script:lateRoot\backups" -File | Where-Object { $_.Name -notlike 'CLEAN-*' } | ForEach-Object { "$($_.Name)=$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" } | Sort-Object)
  }
  function Get-LateDbState { @(Get-ChildItem "$script:lateRoot\data", "$script:lateRoot\backups" -File | Where-Object { $_.Name -notlike 'CLEAN-*' } | ForEach-Object { "$($_.Name)=$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" } | Sort-Object) }
  $savedRootLate = $V2Root
  foreach ($lc in @(@('4.6', @{ 'integrity-v2-backend' = 'Running' }, 'служба backend запущена, Assert-V2ServiceRunning → STOP'),
                    @('4.7', @{ 'integrity-v2-backend' = 'Running'; 'integrity-v2-caddy' = 'Stopped' }, 'Caddy встановлено, старт Caddy → STOP'),
                    @('5', @{ 'integrity-v2-backend' = 'Running'; 'integrity-v2-caddy' = 'Running' }, 'обидві служби працюють, smoke → STOP'))) {
    $dbBefore = New-LateRoot $lc[0] $lc[1]; $V2Root = $script:lateRoot
    $r = $null; $m = $null
    try { $r = @(Invoke-V2CleanInstallFailClosed -Reason "тест: збій на етапі $($lc[0])" -OwnedServices @($lc[1].Keys)) } catch { $m = $_.Exception.Message } finally { $V2Root = $savedRootLate }
    $dn = @(Get-ChildItem "$script:lateRoot\data" -File | ForEach-Object Name); $rn = @(Get-ChildItem $script:lateRoot -File | ForEach-Object Name)
    $svcOk = @($lc[1].Keys | Where-Object { $global:Fake.Services[$_].State -ne 'Stopped' -or $global:Fake.Services[$_].StartMode -ne 'Disabled' }).Count -eq 0
    $V2Root = $script:lateRoot; $global:Fake.Native.Clear()
    $ms = Get-StopMessage { Invoke-V2ServiceStart -Name 'integrity-v2-backend' -Checks { 'PASS' } }; $startBlocked = $ms -match '^STOP:.*(StartMode = Disabled|старт backend заборонено)'
    $noScStart = -not @($global:Fake.Native | Where-Object { $_ -like 'sc.exe start*' }).Count
    $V2Root = $savedRootLate
    Add-Res "CI.late-$($lc[0])" ($null -eq $m -and @($r | Where-Object { $_ -like 'PASS  READY інвалідовано*' }).Count -eq 1 -and
      @($dn | Where-Object { $_ -like 'CLEAN-INIT-FAILED-INSTALL-*' }).Count -eq 1 -and -not @($dn | Where-Object { $_ -like 'CLEAN-INIT-OK-*' }).Count -and
      @($dn | Where-Object { $_ -like 'CLEAN-INIT-REVOKED-*' }).Count -eq 1 -and @($rn | Where-Object { $_ -like 'CLEAN-INSTALL-FAILED-*' }).Count -eq 1 -and $svcOk -and
      (Test-Stop { Assert-V2DataReady -DataDir "$script:lateRoot\data" } '*старт backend заборонено*') -and $startBlocked -and $noScStart -and
      ((Get-LateDbState) -join '|') -eq ($dbBefore -join '|')) "збій на $($lc[0]) після CLEAN-INIT-OK ($($lc[2])) → READY інвалідовано (FAILED-INSTALL, OK → REVOKED, маркер у корені); служби V2 Stopped + Disabled; старт backend заборонено, sc start не викликається; БД і копії не змінено й не видалено"
  }
  # маркер у data\ записати неможливо (data — файл) → STOP «FAIL-CLOSED НЕ ЗАВЕРШЕНО», але служби V2 однаково зупинено й Disabled, маркер у корені блокує старт
  $null = New-LateRoot 'nomarker' @{ 'integrity-v2-backend' = 'Running' }
  Remove-Item "$script:lateRoot\data" -Recurse -Force; [IO.File]::WriteAllText("$script:lateRoot\data", 'not a dir')
  $V2Root = $script:lateRoot
  try { $m = Get-StopMessage { Invoke-V2CleanInstallFailClosed -Reason 'тест' -OwnedServices @('integrity-v2-backend') } } finally { $V2Root = $savedRootLate }
  Add-Res 'CI.late-markerfail' ($m -like 'STOP:*FAIL-CLOSED НЕ ЗАВЕРШЕНО*CLEAN-INIT-FAILED-INSTALL не записано*' -and $global:Fake.Services['integrity-v2-backend'].State -eq 'Stopped' -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Disabled' -and @(Get-ChildItem $script:lateRoot -File -Filter 'CLEAN-INSTALL-FAILED-*').Count -eq 1) 'маркер інвалідації не записано → STOP (не PASS); служби V2 однаково зупинено й Disabled; маркер у корені збережено'
  # Disabled не підтверджено → STOP, READY однаково інвалідовано
  $null = New-LateRoot 'nodisable' @{ 'integrity-v2-backend' = 'Running' }; $global:Fake.StartModeFail = 'Disabled'; $V2Root = $script:lateRoot
  try { $m = Get-StopMessage { Invoke-V2CleanInstallFailClosed -Reason 'тест' -OwnedServices @('integrity-v2-backend') } } finally { $V2Root = $savedRootLate; $global:Fake.StartModeFail = $null }
  Add-Res 'CI.late-nodisable' ($m -like 'STOP:*FAIL-CLOSED НЕ ЗАВЕРШЕНО*Disabled не підтверджено*' -and @(Get-ChildItem "$script:lateRoot\data" -Filter 'CLEAN-INIT-FAILED-INSTALL-*').Count -eq 1 -and (Test-Stop { Assert-V2DataReady -DataDir "$script:lateRoot\data" } '*старт backend заборонено*')) 'start type Disabled не підтверджено → STOP; READY однаково інвалідовано'
  $null = New-LateRoot 'foreign-service' @{ 'integrity-v2-backend' = 'Running' }; $V2Root = $script:lateRoot
  try { $m = Get-StopMessage { Invoke-V2CleanInstallFailClosed -Reason 'конкурентна служба' -OwnedServices @() } } finally { $V2Root = $savedRootLate }
  Add-Res 'CI.foreign-service' ($m -like 'STOP:*служба існує, але цей запуск не довів її створення*' -and $global:Fake.Services['integrity-v2-backend'].State -eq 'Running' -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Manual' -and -not @($global:Fake.Native | Where-Object { $_ -like '* stop *' -or $_ -like '* config *' }).Count) 'сторонню службу після створення власного root не stop/disable; стан BLOCKED'
  $null = New-LateRoot 'owned-replaced' @{ 'integrity-v2-backend' = 'Running' }; $V2Root = $script:lateRoot
  $global:Fake.Services['integrity-v2-backend'].PathName = 'C:\foreign\backend.exe'
  try { $m = Get-StopMessage { Invoke-V2CleanInstallFailClosed -Reason 'службу замінено' -OwnedServices @('integrity-v2-backend') } } finally { $V2Root = $savedRootLate }
  Add-Res 'CI.owned-replaced' ($m -like 'STOP:*FAIL-CLOSED НЕ ЗАВЕРШЕНО*PathName*' -and $global:Fake.Services['integrity-v2-backend'].State -eq 'Running' -and $global:Fake.Services['integrity-v2-backend'].StartMode -eq 'Manual' -and -not @($global:Fake.Native | Where-Object { $_ -like '* stop *' -or $_ -like '* config *' }).Count) 'після ownership callback однойменну службу замінено → маркери FAIL, але stop/disable чужої служби заборонено'
  # старий OK + маркер невдалого встановлення в корені (без маркерів у data\) → STOP
  $dr = Join-Path $ciRoot 'rootfailed\integrity-v2'; $null = New-Item -ItemType Directory "$dr\data"; [IO.File]::WriteAllText("$dr\data\CLEAN-INIT-OK-1.txt", 'x'); [IO.File]::WriteAllText("$dr\CLEAN-INSTALL-FAILED-1.txt", 'x')
  Add-Res 'CI.ready-rootfailed' (Test-Stop { Assert-V2DataReady -DataDir "$dr\data" } '*старт backend заборонено*CLEAN-INSTALL-FAILED*') 'старий CLEAN-INIT-OK + CLEAN-INSTALL-FAILED у корені → STOP'
  # після fail-closed свідоме переривання працює (служби Disabled → видаляються, корінь → -abandoned)
  $null = New-LateRoot 'abort' @{ 'integrity-v2-backend' = 'Running'; 'integrity-v2-caddy' = 'Running' }; $V2Root = $script:lateRoot
  $global:Fake.NativeHook = { param($e, $a) if ($a[0] -eq 'stop') { $sv = $global:Fake.Services[$a[1]]; if ($sv) { if ($sv.ProcessId) { $global:Fake.Procs[[int]$sv.ProcessId].Exited = $true }; $sv.State = 'Stopped'; $sv.ProcessId = 0 } }; if ($a[0] -eq 'uninstall') { foreach ($n in @($global:Fake.Services.Keys)) { if ($V2Services[$n].Exe -eq $e) { $global:Fake.Services.Remove($n) } } } }
  $ra = $null; try { $null = Invoke-V2CleanInstallFailClosed -Reason 'тест' -OwnedServices @('integrity-v2-backend','integrity-v2-caddy'); $ra = @(Invoke-V2CleanInstallAbort -Reason 'тест після fail-closed') } catch { $ra = @("ERR: $($_.Exception.Message)") } finally { $V2Root = $savedRootLate }
  Add-Res 'CI.late-abort' (@($ra | Where-Object { $_ -like 'PASS  корінь V2 перейменовано*' }).Count -eq 1 -and -not $global:Fake.Services.Count -and -not (Test-Path $script:lateRoot)) 'після fail-closed: свідоме -Abort видаляє служби V2 і перейменовує корінь (докази збережено)'
  Set-Item function:script:Invoke-V2Native $realNativeLate
  $V2StopProof.Clear(); $V2Identity.Clear()
  # --- C3 (№4): порти V2 вільні до будь-якого запису
  Reset-Fake
  Add-Res 'CI.ports-free' ((Assert-V2PortsFree) -like 'PASS  порти вільні*') 'усі порти V2 вільні → PASS (контроль)'
  Reset-Fake; Add-FakeListener 8100 4321
  Add-Res 'CI.ports-tcp8100' (Test-Stop { Assert-V2PortsFree } '*порти V2 зайняті*TCP 127.0.0.1:8100 (PID 4321)*') 'TCP 8100 зайнятий чужим процесом → STOP (нічого не зупиняється)'
  Reset-Fake; $global:Fake.Udp = @([pscustomobject]@{ LocalAddress = '0.0.0.0'; LocalPort = 443; OwningProcess = 99 })
  Add-Res 'CI.ports-udp443' (Test-Stop { Assert-V2PortsFree } '*UDP 0.0.0.0:443*') 'UDP 443 зайнятий → STOP'
  Set-Item function:Get-V2Listeners $orig['Get-V2Listeners']
  Set-Item function:Get-NetTCPConnection { param($State, $ErrorAction) throw 'TCP API denied (synthetic)' }
  Add-Res 'CI.ports-tcp-error' (Test-Stop { Assert-V2PortsFree } '*TCP enumeration неможлива*TCP API denied*') 'збій TCP API → BLOCKED, не вільний порт'
  Set-Item function:Get-V2Listeners { param([int[]]$Ports) @($global:Fake.Listeners | Where-Object { $Ports -contains $_.LocalPort }) }
  Set-Item function:Get-V2UdpEndpoints $orig['Get-V2UdpEndpoints']
  Set-Item function:Get-NetUDPEndpoint { param($ErrorAction) throw 'UDP API denied (synthetic)' }
  Add-Res 'CI.ports-udp-error' (Test-Stop { Assert-V2PortsFree } '*UDP enumeration неможлива*UDP API denied*') 'збій UDP API → BLOCKED, не вільний порт'
  Set-Item function:Get-V2UdpEndpoints { param([int[]]$Ports) @($global:Fake.Udp | Where-Object { $Ports -contains $_.LocalPort }) }
  $cfgBase = Join-Path $tmp 'target-config-test'; $null = New-Item -ItemType Directory -Path $cfgBase
  $cfgSource = Join-Path $cfgBase 'Caddyfile.source'
  [IO.File]::WriteAllText($cfgSource, "desktop-jtgc2sg.taild5c033.ts.net:443 {`n bind 100.111.221.74 [fd7a:115c:a1e0::ef01:dddc]`n}", [Text.Encoding]::GetEncoding(1251))
  $cfgDest = Join-Path $cfgBase 'out'
  $cfgResult = @(New-V2TargetConfig -CaddySource $cfgSource -BackendSource (Join-Path $PSScriptRoot 'integrity-v2-backend.xml.template') -Destination $cfgDest -HostName 'vm-v2.example.test' -Addresses @('10.8.0.9', 'fd7a::9'))
  $cfgCaddy = [IO.File]::ReadAllText((Join-Path $cfgDest 'Caddyfile')); $cfgXml = [IO.File]::ReadAllText((Join-Path $cfgDest 'integrity-v2-backend.xml'))
  Add-Res 'CI.target-staging' ($cfgResult[-1] -like 'PASS*target config*' -and $cfgCaddy.Contains('vm-v2.example.test:443') -and $cfgCaddy.Contains('bind 10.8.0.9 [fd7a::9]') -and $cfgXml.Contains('value="https://vm-v2.example.test"') -and -not $cfgXml.Contains('desktop-jtgc2sg') -and (Test-Path (Join-Path $cfgDest 'TARGET-CONFIG-MANIFEST.txt'))) 'окремий test-host Caddyfile/XML і SHA manifest; release source не змінено'
  Add-Res 'CI.target-manifest' ((Assert-V2TargetConfigManifest -Directory $cfgDest -HostName 'vm-v2.example.test' -Addresses @('10.8.0.9', 'fd7a::9')) -like 'PASS*target config manifest*') 'target config manifest підтверджує host/bind і hashes'
  [IO.File]::AppendAllText((Join-Path $cfgDest 'Caddyfile'), "`n# tampered")
  Add-Res 'CI.target-tamper' (Test-Stop { Assert-V2TargetConfigManifest -Directory $cfgDest -HostName 'vm-v2.example.test' -Addresses @('10.8.0.9', 'fd7a::9') } '*SHA256 Caddyfile невірний*') 'зміна staged Caddyfile після генерації → STOP'
  Add-Res 'CI.target-prod-reject' (Test-Stop { Assert-V2TargetIdentity -HostName 'desktop-jtgc2sg.taild5c033.ts.net' -Addresses @('100.111.221.74') -TestHost } '*test host не може використовувати production DNS/IP*') 'test-host із production DNS/IP → STOP до будь-якої зміни'
  $oldDns = (Get-Item function:Get-V2TargetDns).ScriptBlock; $oldLocal = (Get-Item function:Get-V2TargetLocalIps).ScriptBlock
  Set-Item function:Get-V2TargetDns { param($HostName) @('10.8.0.10') }
  Set-Item function:Get-V2TargetLocalIps { @('10.8.0.9') }
  try {
    $targetHost = "$env:COMPUTERNAME.example.test"
    Add-Res 'CI.target-dns-mismatch' (Test-Stop { Assert-V2TargetIdentity -HostName $targetHost -Addresses @('10.8.0.9') -TestHost } '*фактичний набір DNS-адрес не дорівнює схваленому*') 'target DNS відрізняється від bind → STOP'
    Set-Item function:Get-V2TargetDns { param($HostName) @('10.8.0.9') }
    Add-Res 'CI.target-bind-mismatch' (Test-Stop { Assert-V2TargetIdentity -HostName $targetHost -Addresses @('10.8.0.10') -TestHost } '*не підтверджена одночасно DNS і локальним інтерфейсом*') 'bind адреси немає на локальному інтерфейсі → STOP'
  } finally { Set-Item function:Get-V2TargetDns $oldDns; Set-Item function:Get-V2TargetLocalIps $oldLocal }
  Reset-Fake
  # --- C3 (№4): цільовий хост — Windows build, Windows PowerShell 5.1 x64, вільне місце
  $global:Fake.Host = [pscustomobject]@{ PSVersion = '5.1'; PSEdition = 'Desktop'; Is64 = $true; Build = 20348; Drive = 'C:\'; FreeBytes = 50GB }
  Add-Res 'CI.host-ok' ((Assert-V2HostPreflight -ExpectedWindowsBuild 20348) -like 'PASS  хост*') 'хост відповідає цілі → PASS (контроль)'
  Add-Res 'CI.host-build' (Test-Stop { Assert-V2HostPreflight -ExpectedWindowsBuild 17763 } '*збірка Windows 20348 ≠ цільовій 17763*') 'збірка Windows ≠ серверу → STOP'
  $global:Fake.Host.FreeBytes = 1GB
  $hostSpaceMsg = Get-StopMessage { Assert-V2HostPreflight -ExpectedWindowsBuild 20348 }
  Add-Res 'CI.host-space' ($hostSpaceMsg -like 'STOP:*вільно*ГБ*<*ГБ*') 'вільного місця < 2 ГБ → STOP'
  $global:Fake.Host.FreeBytes = 50GB; $global:Fake.Host.PSVersion = '7.4'; $global:Fake.Host.PSEdition = 'Core'
  Add-Res 'CI.host-pwsh' (Test-Stop { Assert-V2HostPreflight -ExpectedWindowsBuild 20348 } '*PowerShell 7.4 Core ≠ Windows PowerShell 5.1*') 'PowerShell 7 замість 5.1 → STOP'
  $global:Fake.Host = $null
  # --- C7 (№4): fault injection на кожному кроці ініціалізації БД (seed, verify, fingerprint, backup, migrations, schema, auth-schema)
  $realPyF = (Get-Item function:Invoke-V2Py).ScriptBlock; $realDbF = (Get-Item function:Invoke-V2DbTool).ScriptBlock
  foreach ($fc in @(@('seed', 'py', 'app.seed'), @('verify', 'db', 'verify'), @('fingerprint', 'fp', ''), @('backup', 'db', 'backup'),
                    @('migrations', 'py', 'app.migrations'), @('schema', 'schema', ''), @('integrity-schema', 'db', 'schema'), @('auth-schema', 'db', 'auth-schema'))) {
    $script:fcStep = $fc
    Set-Item function:script:Invoke-V2Py { param([string]$Py, [string]$Backend, [string[]]$ArgList, [string]$What)
      $j = $ArgList -join ' '
      if ($script:fcStep[1] -eq 'py' -and $j -like "*$($script:fcStep[2])*" -and $j -notlike '*check_schema*') { Stop-V2 "$What → код 1 (тест: збій $($script:fcStep[0]))" }
      if ($j -like '*check_schema*') { if ($script:fcStep[1] -eq 'schema') { 'SCHEMA FAIL (тест)' } else { 'SCHEMA OK' } } else { "OK $What" } }
    Set-Item function:script:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList)
      if ($script:fcStep[1] -eq 'db' -and $ArgList[0] -eq $script:fcStep[2]) { Stop-V2 "v2_db_tool $($ArgList[0]) → код 1 (тест: збій $($script:fcStep[0]))" }
      switch ($ArgList[0]) { 'fingerprint' { if ($script:fcStep[1] -eq 'fp') { 'fp-other' } else { 'fp-ref' } } 'auth-schema' { 'AUTH SCHEMA OK (тест)' } 'schema' { 'INTEGRITY SCHEMA OK (тест)' } default { "OK $($ArgList[0])" } } }
    $dF = Join-Path $ciRoot "fault-$($fc[0])"; $bF = Join-Path $ciRoot "fault-$($fc[0])-bk"; $null = New-Item -ItemType Directory $dF, $bF
    $mF = $null
    try { $null = Initialize-V2CleanDatabases -Py 'py' -Backend 'be' -DbTool 'tool' -DataDir $dF -BackupDir $bF -ReferenceFingerprint 'fp-ref' } catch { $mF = $_.Exception.Message }
    finally { Set-Item function:script:Invoke-V2Py $realPyF; Set-Item function:script:Invoke-V2DbTool $realDbF }
    $namesF = @(Get-ChildItem $dF -File | ForEach-Object Name)
    $reuse = $null; try { $null = Initialize-V2CleanDatabases -Py 'py' -Backend 'be' -DbTool 'tool' -DataDir $dF -BackupDir $bF } catch { $reuse = $_.Exception.Message }
    Add-Res "CI.fault-$($fc[0])" ($mF -like 'STOP:*CLEAN INIT НЕВДАЛИЙ*' -and @($namesF | Where-Object { $_ -like 'CLEAN-INIT-FAILED-*' }).Count -eq 1 -and
      -not @($namesF | Where-Object { $_ -like 'CLEAN-INIT-IN-PROGRESS-*' -or $_ -like 'CLEAN-INIT-OK-*' }).Count -and
      (Test-Stop { Assert-V2DataReady -DataDir $dF } '*старт backend заборонено*') -and $reuse -like 'STOP:*лише на порожньому data*') "збій на кроці $($fc[0]) → CLEAN-INIT-FAILED; старт backend заборонено; повторна ініціалізація поверх часткового data\ → STOP (без reuse/auto-repair)"
  }
  Remove-Variable fcStep -Scope Script
  # --- нові БД лише в порожньому data\
  $dn = Join-Path $ciRoot 'init-notempty'; $null = New-Item -ItemType Directory $dn; [IO.File]::WriteAllText("$dn\integrity_v2.db", 'old')
  $bkn = Join-Path $ciRoot 'bk-notempty'; $null = New-Item -ItemType Directory $bkn
  Add-Res 'CI.init-notempty' ((Test-Stop { Initialize-V2CleanDatabases -Py $Py -Backend 'C:\none' -DbTool $dbTool -DataDir $dn -BackupDir $bkn } '*лише на порожньому data*') -and (@(Get-ChildItem $dn | ForEach-Object Name) -join ',') -eq 'integrity_v2.db') 'непорожній data\ → STOP до будь-якої дії; наявна БД не використовується, маркер не створено'
  # --- Complete-V2CleanDatabases на справжніх SQLite (після bootstrap): строгий auth-schema робочої БД і фінальної копії
  $ddlI = Join-Path $tmp 'integrity-ddl.sql'; [IO.File]::WriteAllText($ddlI, ((Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-I', $dbTool, 'ddl', '--kind', 'integrity', '--expect-version', "$Vi") -Utf8 -What 'integrity ddl') -join "`n"))
  $mkI = { param($path) $null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.executescript(open(sys.argv[2],encoding=''utf-8'').read()); c.execute(''pragma user_version='' + sys.argv[3]); c.commit(); c.close()', $path, $ddlI, "$Vi") -What 'mkdb integrity (DDL релізу)' }
  function New-CiData([string]$tag, [switch]$NoAdmin) {
    $dd = Join-Path $ciRoot "cmp-$tag"; $bb = Join-Path $ciRoot "cmpbk-$tag"; $null = New-Item -ItemType Directory $dd, $bb
    & $mkI (Join-Path $dd 'integrity_v2.db'); & $mkA (Join-Path $dd 'v2_auth.db')
    if (-not $NoAdmin) { $null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(''insert into v2_users(name,email,password_hash,role,created_at) values(?,?,?,?,?)'', (''A'',''a@example.test'',''h'',''admin'',''2026-11-19'')); c.commit(); c.close()', (Join-Path $dd 'v2_auth.db')) -What 'admin' }
    [IO.File]::WriteAllText((Join-Path $dd 'CREATED-BY-V2-INSTALL.txt'), 'x'); [IO.File]::WriteAllText((Join-Path $dd 'CLEAN-INIT-IN-PROGRESS-20261119-000000.txt'), 'x')
    @{ D = $dd; B = $bb; Fp = (Invoke-V2DbTool -Py $Py -DbTool $dbTool -ArgList @('fingerprint', (Join-Path $dd 'integrity_v2.db'))) }
  }
  $c = New-CiData 'ok'
  $r = @(Complete-V2CleanDatabases -Py $Py -DbTool $dbTool -DataDir $c.D -BackupDir $c.B -ReferenceFingerprint $c.Fp)
  $bks = @(Get-ChildItem $c.B -Filter '*.db' | ForEach-Object Name | Sort-Object)
  Add-Res 'CI.complete-ok' ($r[-1] -like 'PASS*CLEAN-INIT-OK-20261119-000000.txt*' -and $bks.Count -eq 2 -and @(Get-Content (Join-Path $c.B 'SHA256SUMS.txt')).Count -eq 2 -and (Assert-V2DataReady -DataDir $c.D) -like 'PASS*' -and @($r | Where-Object { $_ -like '*фінальна копія: AUTH SCHEMA OK*' }).Count -eq 1) 'робоча v2_auth і ФІНАЛЬНА копія — строгий auth-schema; 1 адміністратор; копії + SHA256SUMS → CLEAN-INIT-OK; старт дозволено'
  $c = New-CiData 'badauth'
  $null = Invoke-V2Native -Exe $Py -ArgList @('-I', '-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(''drop index idx_v2_sessions_token''); c.commit(); c.close()', (Join-Path $c.D 'v2_auth.db')) -What 'corrupt'
  $m = Get-StopMessage { Complete-V2CleanDatabases -Py $Py -DbTool $dbTool -DataDir $c.D -BackupDir $c.B -ReferenceFingerprint $c.Fp }
  Add-Res 'CI.complete-badauth' ($m -like '*CLEAN INIT НЕВДАЛИЙ*auth-schema: FAIL A09*' -and @(Get-ChildItem $c.D -Filter 'CLEAN-INIT-FAILED-*').Count -eq 1 -and (Test-Stop { Assert-V2DataReady -DataDir $c.D })) 'v2_auth.db без обов''язкового індексу → CLEAN-INIT-FAILED; старт заборонено; копії не створено'
  $c = New-CiData 'noadmin' -NoAdmin
  $m = Get-StopMessage { Complete-V2CleanDatabases -Py $Py -DbTool $dbTool -DataDir $c.D -BackupDir $c.B -ReferenceFingerprint $c.Fp }
  Add-Res 'CI.complete-noadmin' ($m -like '*рівно один адміністратор*' -and @(Get-ChildItem $c.D -Filter 'CLEAN-INIT-FAILED-*').Count -eq 1) 'bootstrap не створив адміністратора → CLEAN-INIT-FAILED'
  $c = New-CiData 'badbackup'
  $origToolCi = (Get-Item function:Invoke-V2DbTool).ScriptBlock
  Set-Item function:script:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) if ($ArgList[0] -eq 'auth-schema' -and $ArgList[1] -like '*v2_auth-initial-*') { Stop-V2 'v2_db_tool auth-schema → код 1: STOP: auth-schema: FAIL A12 (тест: копія)' }; & $origToolCi -Py $Py -DbTool $DbTool -ArgList $ArgList }
  try { $m = Get-StopMessage { Complete-V2CleanDatabases -Py $Py -DbTool $dbTool -DataDir $c.D -BackupDir $c.B -ReferenceFingerprint $c.Fp } } finally { Set-Item function:script:Invoke-V2DbTool $origToolCi }
  Add-Res 'CI.complete-badbackup' ($m -like '*CLEAN INIT НЕВДАЛИЙ*auth-schema: FAIL A12 (тест: копія)*' -and @(Get-ChildItem $c.D -Filter 'CLEAN-INIT-FAILED-*').Count -eq 1 -and -not (Test-Path (Join-Path $c.B 'SHA256SUMS.txt'))) 'фінальна копія v2_auth не пройшла строгу перевірку → CLEAN-INIT-FAILED; SHA256SUMS не записано'
  $c = New-CiData 'twomarkers'; [IO.File]::WriteAllText((Join-Path $c.D 'CLEAN-INIT-FAILED-1.txt'), 'x')
  Add-Res 'CI.complete-state' (Test-Stop { Complete-V2CleanDatabases -Py $Py -DbTool $dbTool -DataDir $c.D -BackupDir $c.B -ReferenceFingerprint $c.Fp } '*рівно один маркер CLEAN-INIT-IN-PROGRESS*') 'невизначений стан маркерів → STOP'

  # ---------------- ДЕЛЬТА 5 — static P12 справді виявляє заборонений сценарій «системний PID» (на копії комплекту)
  $ps = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName   # той самий рушій (5.1 або pwsh), що виконує тести
  foreach ($variant in @(@('control', $null, 0), @('inject-known', ('$null = Stop-V2ProcessTree -Kno' + 'wn @($x, ' + [string](2 + 2) + ')'), 1), @('inject-id', ('Stop-Process -Id ' + [string](2 + 2)), 1))) {
    $kit = Join-Path $tmp ('kit-' + $variant[0]); $null = New-Item -ItemType Directory $kit
    foreach ($f in Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object { $_.Name -ne 'debug_job.py' }) { Copy-Item -LiteralPath $f.FullName -Destination $kit }
    if ($variant[1]) { [IO.File]::AppendAllText((Join-Path $kit 'test-rev3-negative.ps1'), "`n# $($variant[1])`n$($variant[1])`n") }
    $o = @(Invoke-V2Native -Exe $ps -ArgList @('-NoProfile', '-NonInteractive', '-File', (Join-Path $kit 'static-rev3.ps1')) -OkCodes @($variant[2]) -Utf8 -What "static-rev3 ($($variant[0]))")
    $p12 = @($o | Where-Object { $_ -match '^P12 ' })
    $want = if ($variant[2] -eq 0) { 'PASS' } else { 'FAIL' }
    Add-Res 'S12' ($p12.Count -eq 1 -and $p12[0] -match " $want ") "static P12 на копії ($($variant[0])): код $($variant[2]), P12 $want"
  }
} catch {
  Add-Res 'ERR' $false "необроблена помилка тесту: $($_.Exception.Message)"
} finally {
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue      # лише тестовий каталог у %TEMP%
  foreach ($n in $guarded) { Remove-Item -Path "function:global:$n" -ErrorAction SilentlyContinue }
}
Add-Res 'I9' ($global:V2TestRealCalls.Count -eq 0) "спроб реальних викликів (Stop-Process/Get-Process/CIM/мережа/служби/ACL): $($global:V2TestRealCalls.Count) $($global:V2TestRealCalls -join ',')"
$results
$fail = @($results | Where-Object { $_ -match '^\S+\s+FAIL ' }).Count
"Підсумок: $(@($results | Where-Object { $_ -match '^\S+\s+PASS ' }).Count) PASS, $fail FAIL, $(@($results | Where-Object { $_ -match '^\S+\s+NOT RUN ' }).Count) NOT RUN"
if ($fail) { exit 1 } else { exit 0 }
