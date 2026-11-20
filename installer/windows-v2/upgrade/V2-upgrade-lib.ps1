# V2-upgrade-lib.ps1 — спільні функції оновлення на місці, відкату, щоденного резервного копіювання й ротації ключа V2.
# Windows PowerShell 5.1, від адміністратора, неінтерактивно (придатно для SSH). Підключення:
#   . "$PSScriptRoot\V2-upgrade-lib.ps1"; Initialize-V2Up -Root C:\srv\integrity-v2 [-Simulate]
# Принципи: fail-closed; жодних Read-Host; XML служби (секрети V2_SECRET_KEY, V2_SMTP_*) змінюється лише побайтово в одному
# елементі й ніколи не виводиться — у журналі лише SHA256 і значення <workingdirectory>; живий Caddyfile переписується на місці
# (ACL файла зберігається); БД відновлюються лише з перевіреної копії в НОВИЙ файл (v2_db_tool restore) з маркерами
# RESTORE-IN-PROGRESS/FAILED/OK (ті самі, що в інсталятора: FAILED блокує старт backend).
# Адаптери (*-V2Up* нижче, розділ «адаптери») — єдині точки дотику до SCM, ACL, мережі; -Simulate підміняє лише їх
# (upgrade\sim\V2-upgrade-sim.ps1), уся решта логіки (файли, ZIP, SHA256, v2_db_tool, pip, міграція) виконується справжньою.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'V2-install-common.ps1')
$ErrorActionPreference = 'Stop'

$V2UpBackend = 'integrity-v2-backend'
$V2UpCaddy = 'integrity-v2-caddy'
$V2UpHostName = 'desktop-jtgc2sg.taild5c033.ts.net'
$V2UpAddress = '100.111.221.74'
$V2UpComputer = 'DESKTOP-JTGC2SG'
$V2UpSim = $false
$V2UpLib = $PSScriptRoot
$V2UpKit = Split-Path -Parent $PSScriptRoot                      # installer\windows-v2 (v2_db_tool.py, шаблони)
$V2UpBootstrapRx = '(?i)(^|/)v2_(clean_)?bootstrap_admin\.py$'   # модулі bootstrap не розгортаються в app\ (контракт §5)
$V2UpEnvNameRx = '^(UVICORN_|V2_|INTEGRITY_)|^(APP_ENV|TRUSTED_PROXIES|FRONTEND_ORIGINS|FORWARDED_ALLOW_IPS)$'
$V2UpFailAt = @()
$V2UpLogLines = New-Object System.Collections.Generic.List[string]

function Write-V2UpLog([string]$Line) {
  $V2UpLogLines.Add($Line)
  [Console]::Out.WriteLine($Line)
}
function Initialize-V2Up {
  param([Parameter(Mandatory)] [string] $Root, [switch] $Simulate, [string[]] $FailAt = @())   # адаптери симуляції підключає сам скрипт (на рівні скрипта)
  try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
  $full = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  if ($Simulate) {
    $tempBase = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    if (-not $full.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or $full -like 'C:\srv*') { Stop-V2 "симуляція дозволена лише з -Root у %TEMP%: $full" }
    if (-not (Get-Command Get-V2UpSimState -ErrorAction SilentlyContinue)) { Stop-V2 'симуляція: адаптери sim\V2-upgrade-sim.ps1 не підключено на рівні скрипта' }
  } else {
    if ($FailAt.Count) { Stop-V2 '-SimulateFailAt лише разом із -Simulate' }
    if ($full -cne 'C:\srv\integrity-v2') { Stop-V2 "реальний режим лише для C:\srv\integrity-v2 (отримано $full)" }
  }
  $script:V2Root = $full
  $script:V2UpSim = [bool]$Simulate
  $script:V2UpFailAt = @($FailAt)
}

# =====================================================================================================================
# Адаптери (реальна реалізація). Симуляція перевизначає саме ці функції.
# =====================================================================================================================
function Test-V2UpAdmin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
function Assert-V2UpHost { if ($env:COMPUTERNAME -ne $V2UpComputer) { Stop-V2 "чужий хост $env:COMPUTERNAME (очікується $V2UpComputer)" }; "PASS  хост $V2UpComputer" }
function Get-V2UpService([string]$Name) {
  $s = Get-CimInstance Win32_Service -Filter "Name='$Name'"
  if (-not $s) { return $null }
  $deps = @(); try { $deps = @((Get-Service -Name $Name -ErrorAction Stop).ServicesDependedOn | ForEach-Object Name) } catch { }
  [pscustomobject]@{ Name = $Name; State = [string]$s.State; StartMode = [string]$s.StartMode; DelayedAutoStart = [bool]$s.DelayedAutoStart
                     StartName = [string]$s.StartName; PathName = [string]$s.PathName; ProcessId = [int]$s.ProcessId; DependsOn = $deps }
}
function Stop-V2UpService([string]$Name) {
  $s = Assert-V2UpServiceIdentity $Name
  foreach ($i in 1..30) { if ($s.State -in 'Running', 'Stopped') { break }; Start-Sleep 1; $s = Get-V2UpService $Name }
  if ($s.State -eq 'Stopped' -and -not $s.ProcessId) { return "INFO  $Name уже зупинена" }
  if ($s.State -ne 'Running') { Stop-V2 "${Name}: стан $($s.State) — зупинка неможлива" }
  $unres = New-Object 'System.Collections.Generic.List[object]'
  $tree = Get-V2ServiceTree -Name $Name -Unresolved $unres
  if ($unres.Count -or -not $tree.Count -or $tree[0].Pid -ne $s.ProcessId) { Stop-V2 "${Name}: неповне дерево процесів — зупинка без доказу заборонена" }
  foreach ($p in $tree) { if ($p.Owner -ne $V2Services[$Name].Account) { Stop-V2 "${Name}: PID $($p.Pid) — власник $($p.Owner)" } }
  $ctl = Get-Service -Name $Name
  if (@($ctl.DependentServices | Where-Object Status -ne 'Stopped').Count) { Stop-V2 "${Name}: працюють залежні служби" }
  $ctl.Stop()
  $ctl.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
  $now = Get-V2UpService $Name
  if ($now.State -ne 'Stopped' -or $now.ProcessId) { Stop-V2 "${Name}: SCM не підтвердив зупинку" }
  $null = Assert-V2TreeExited -Tree $tree
  if (@(Get-V2LateDescendants -Tree $tree).Count) { Stop-V2 "${Name}: лишилися пізні нащадки" }
  if (@(Get-V2Listeners -Ports @($V2Services[$Name].Port)).Count) { Stop-V2 "${Name}: порт $($V2Services[$Name].Port) досі слухається" }
  if ($Name -eq $V2UpBackend) { $null = Assert-V2DbFilesFree -DataDir "$V2Root\data" }
  "PASS  $Name зупинено: дерево ($($tree.Count)) завершилось, пізніх нащадків 0, порт вільний$(if ($Name -eq $V2UpBackend) { ', файли БД вільні' })"
}
function Start-V2UpService([string]$Name) {
  $s = Assert-V2UpServiceIdentity $Name
  if ($s.State -ne 'Stopped') { Stop-V2 "${Name}: старт лише зі стану Stopped (зараз $($s.State))" }
  if ($Name -eq $V2UpBackend) { $null = Assert-V2NoRestoreBlock -DataDir "$V2Root\data" }
  $ctl = Get-Service -Name $Name
  $ctl.Start()
  $ctl.WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
  $now = Get-V2UpService $Name
  if ($now.State -ne 'Running' -or -not $now.ProcessId) { Stop-V2 "${Name}: SCM не підтвердив старт" }
  $tree = Get-V2ServiceTree -Name $Name
  foreach ($p in $tree) { if ($p.Owner -ne $V2Services[$Name].Account) { Stop-V2 "${Name}: PID $($p.Pid) — власник $($p.Owner)" } }
  $addr = if ($Name -eq $V2UpBackend) { '127.0.0.1' } else { $V2UpAddress }
  $l = Wait-V2Listener -Port $V2Services[$Name].Port -Tree $tree -Addresses @($addr)
  "PASS  $Name запущено (PID $($now.ProcessId)); $l"
}
function Set-V2UpStartMode([string]$Name, [ValidateSet('delayed-auto', 'demand', 'disabled')] [string]$Mode) {
  $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('config', $Name, 'start=', $Mode) -What "sc config $Name start= $Mode"
  $s = Get-V2UpService $Name
  $ok = switch ($Mode) { 'delayed-auto' { $s.StartMode -eq 'Auto' -and $s.DelayedAutoStart } 'demand' { $s.StartMode -eq 'Manual' } 'disabled' { $s.StartMode -eq 'Disabled' } }
  if (-not $ok) { Stop-V2 "start type $Name не підтверджено: $($s.StartMode)/$($s.DelayedAutoStart) ≠ $Mode" }
  "PASS  $Name start= $Mode (read-back $($s.StartMode)$(if ($s.DelayedAutoStart) { ', delayed' }))"
}
function Get-V2UpHttpStatus([string]$Path, [string]$Method = 'GET') { Get-V2HttpStatus -Url "http://127.0.0.1:8100$Path" -Method $Method }
function Assert-V2UpHttps([string]$Path, [int]$Expected) { Assert-V2PinnedHttps -HostName $V2UpHostName -Addresses @($V2UpAddress) -Path $Path -Expected $Expected }
function Get-V2UpHttpsHeaders([string]$Path) {
  $null = Assert-V2TargetIdentity -HostName $V2UpHostName -Addresses @($V2UpAddress)
  $hf = Join-Path $env:TEMP ("v2-hdr-" + [guid]::NewGuid().ToString('N') + '.txt')
  try {
    $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\curl.exe" -What "pinned HTTPS headers $Path" -ArgList @('--disable', '--silent', '--show-error', '--output', 'NUL', '--dump-header', $hf,
      '--max-time', '20', '--noproxy', '*', '--resolve', "${V2UpHostName}:443:$V2UpAddress", "https://$V2UpHostName$Path")
    $h = @{}; foreach ($l in [IO.File]::ReadAllLines($hf)) { if ($l -match '^([A-Za-z0-9-]+):\s*(.*)$') { $h[$Matches[1].ToLowerInvariant()] = $Matches[2] } }
    $h
  } finally { if (Test-Path -LiteralPath $hf) { Remove-Item -LiteralPath $hf -Force } }
}
function Grant-V2UpAcl([string]$Path, [string]$Account, [string]$Rights) { Grant-V2 -Path $Path -Account $Account -Rights $Rights }
function Assert-V2UpAclTree([string]$Path, [string]$Service, [string]$Rights, [string]$Role) { Assert-V2AclTree -Path $Path -ServiceSid (Get-V2ServiceSid $Service) -ServiceRights $Rights -Role $Role }
function New-V2UpAdminDir([string]$Path, [string]$DecisionRef) {
  New-V2ProtectedDirectoryCore -Path $Path -Sddl 'O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)' -DecisionRef $DecisionRef -ExpectedOwnerSid $SidAdmins -AllowedSids @($SidAdmins, $SidSystem)
}
function Assert-V2UpAdminOnly([string]$Path) { Assert-V2AclExact -Acl (Get-V2Acl $Path) -Label $Path -IsContainer:(Test-Path -LiteralPath $Path -PathType Container) }
function Assert-V2UpCaddyfileAcl([string]$Path) { Assert-V2AclExact -Acl (Get-V2Acl $Path) -ServiceSid (Get-V2ServiceSid $V2UpCaddy) -ServiceRights R -Label $Path }
function Get-V2UpMachineEnvNames { @([Environment]::GetEnvironmentVariables('Machine').Keys | ForEach-Object { [string]$_ } | Where-Object { $_ -match $V2UpEnvNameRx } | Sort-Object) }
function Get-V2UpFreeBytes { ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($V2Root))).AvailableFreeSpace }
function Get-V2UpCaddyExe { "$V2Root\caddy\bin\caddy.exe" }
function Invoke-V2UpCaddyValidate([string]$File) {
  $exe = Get-V2UpCaddyExe
  $null = Assert-V2FileHash -Path $exe -Sha256 $CaddyRefSha256 -Label 'caddy.exe'
  $null = Invoke-V2Native -Exe $exe -ArgList @('validate', '--config', $File, '--adapter', 'caddyfile') -What 'caddy validate'
  "PASS  caddy validate $File"
}
function Get-V2UpVenvPython { "$V2Root\venv\Scripts\python.exe" }

# =====================================================================================================================
# Службові перевірки й облік кроків
# =====================================================================================================================
function Assert-V2UpServiceIdentity([string]$Name) {
  $s = Get-V2UpService $Name
  if (-not $s) { Stop-V2 "служби $Name немає" }
  $exe = Join-Path $V2Root "services\$($Name -replace '^integrity-v2-', '')\$Name.exe"
  if ($s.StartName -ne "NT SERVICE\$Name") { Stop-V2 "${Name}: StartName = $($s.StartName)" }
  if ($s.PathName.Trim().Trim('"') -ne $exe) { Stop-V2 "${Name}: PathName = $($s.PathName)" }
  if ($s.StartMode -notin 'Manual', 'Auto') { Stop-V2 "${Name}: StartMode = $($s.StartMode) (очікується Manual або Auto)" }
  $s
}
function New-V2UpEvidence([string]$Kind) {
  [ordered]@{ Schema = "integrity-v2-$Kind/1"; Host = $env:COMPUTERNAME; Simulated = $V2UpSim; StartedUtc = [DateTime]::UtcNow.ToString('o'); Result = 'RUNNING'
              Steps = (New-Object System.Collections.Generic.List[object]); Rollback = (New-Object System.Collections.Generic.List[object]) }
}
# Тіло кроку виконується в дочірній області цієї функції: локальні імена мають префікс __ (не перекривають змінні скрипта).
# -SimulateFailAt <крок> імітує збій ПІСЛЯ виконання тіла (мутація вже відбулась) — найгірший випадок для відкату.
function Invoke-V2UpStep {
  param([Parameter(Mandatory)] [string] $__StepName, [Parameter(Mandatory)] [scriptblock] $__StepBody, [Parameter(Mandatory)] $__Evidence, [switch] $__Rollback)
  $__rec = [ordered]@{ Name = $__StepName; Status = 'RUNNING'; StartedUtc = [DateTime]::UtcNow.ToString('o'); EndedUtc = $null; Detail = @(); Error = $null }
  if ($__Rollback) { $__Evidence.Rollback.Add($__rec) } else { $__Evidence.Steps.Add($__rec) }
  Write-V2UpLog "=== $(if ($__Rollback) { 'ВІДКАТ ' })$__StepName"
  try {
    $__out = @(& $__StepBody)
    $__rec.Detail = @($__out | Where-Object { $null -ne $_ } | ForEach-Object { [string]$_ })
    foreach ($__l in $__rec.Detail) { Write-V2UpLog "    $__l" }
    $__key = $__StepName
    if ($V2UpFailAt -contains $__key) { Stop-V2 "ІМІТОВАНИЙ ЗБІЙ після кроку $__key (-SimulateFailAt)" }
    $__rec.Status = 'PASS'
  } catch {
    $__rec.Status = 'FAIL'; $__rec.Error = $_.Exception.Message -replace '^STOP: ', ''
    Write-V2UpLog "    FAIL: $($__rec.Error)"
    throw
  } finally { $__rec.EndedUtc = [DateTime]::UtcNow.ToString('o') }
}
function Save-V2UpJson([string]$Path, $Object) {
  [IO.File]::WriteAllText($Path, (ConvertTo-Json -InputObject $Object -Depth 10), (New-Object Text.UTF8Encoding $false))
}
function Get-V2UpSha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Get-V2UpStreamSha($Stream) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { ([BitConverter]::ToString($sha.ComputeHash($Stream)) -replace '-', '').ToLowerInvariant() } finally { $Stream.Dispose(); $sha.Dispose() }
}
function Read-V2UpSums([string]$Path) {
  $h = [ordered]@{}
  foreach ($l in [IO.File]::ReadAllLines($Path)) {
    if (-not $l.Trim() -or $l.TrimStart().StartsWith('#')) { continue }
    if ($l -notmatch '^([0-9a-fA-F]{64}) [ *]?(\S.*)$') { Stop-V2 "некоректний рядок у $Path" }
    $rel = $Matches[2].Trim().Replace('\', '/')
    if ($rel.StartsWith('/') -or ($rel -split '/') -contains '..' -or $rel -match ':' -or $h.Contains($rel)) { Stop-V2 "недопустимий або повторний шлях у ${Path}: $rel" }
    $h[$rel] = $Matches[1].ToLowerInvariant()
  }
  $h
}
# Маніфест дерева: відносний шлях (/) → SHA256; reparse point → STOP
function Get-V2UpTreeManifest([string]$Dir, [string]$Exclude = '') {
  $base = [IO.Path]::GetFullPath($Dir).TrimEnd('\')
  $m = [ordered]@{}
  foreach ($it in @(Get-ChildItem -LiteralPath $base -Recurse -Force | Sort-Object FullName)) {
    if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-V2 "reparse point у дереві: $($it.FullName)" }
    if ($it.PSIsContainer) { continue }
    $rel = $it.FullName.Substring($base.Length + 1).Replace('\', '/')
    if ($Exclude -and $rel -match $Exclude) { continue }
    $m[$rel] = Get-V2UpSha $it.FullName
  }
  $m
}
function Compare-V2UpManifest($Want, $Got) {
  $d = New-Object System.Collections.Generic.List[string]
  foreach ($k in $Want.Keys) { if (-not $Got.Contains($k)) { $d.Add("немає $k") } elseif ($Got[$k] -ne $Want[$k]) { $d.Add("змінено $k") } }
  foreach ($k in $Got.Keys) { if (-not $Want.Contains($k)) { $d.Add("зайвий $k") } }
  $d.ToArray()
}
function Write-V2UpManifest([string]$Path, $Manifest) {
  [IO.File]::WriteAllLines($Path, [string[]]@($Manifest.Keys | ForEach-Object { "$($Manifest[$_])  $_" }), (New-Object Text.UTF8Encoding $false))
}
function Invoke-V2UpDbTool([string[]]$ArgList) {
  if (-not (Test-Path -LiteralPath $script:V2UpDbTool -PathType Leaf)) { Stop-V2 "немає v2_db_tool.py: $script:V2UpDbTool" }
  Invoke-V2DbTool -Py $script:V2UpBasePython -DbTool $script:V2UpDbTool -ArgList $ArgList
}
function Invoke-V2UpDbToolAll([string[]]$ArgList) {
  @(Invoke-V2Native -Exe $script:V2UpBasePython -ArgList (@('-E', '-s', '-I', '-B', $script:V2UpDbTool) + $ArgList) -Utf8 -What "v2_db_tool $($ArgList[0])")
}

# =====================================================================================================================
# XML служби: лише <workingdirectory>, решта байтів незмінна; секрети не потрапляють у змінні виводу
# =====================================================================================================================
function Get-V2UpXmlWorkdir([string]$XmlPath) {
  $text = (New-Object Text.UTF8Encoding($false, $true)).GetString([IO.File]::ReadAllBytes($XmlPath))
  $m = [regex]::Matches($text, '<workingdirectory>([^<]*)</workingdirectory>')
  if ($m.Count -ne 1) { Stop-V2 "XML: очікується рівно один <workingdirectory> ($($m.Count))" }
  $m[0].Groups[1].Value
}
function Set-V2UpXmlWorkdir {
  param([Parameter(Mandatory)] [string] $XmlPath, [Parameter(Mandatory)] [string] $Old, [Parameter(Mandatory)] [string] $New)
  if ($New -notmatch '^[A-Za-z]:\\[A-Za-z0-9._\\-]+$') { Stop-V2 "нова workingdirectory поза дозволеною формою: $New" }
  $bytes = [IO.File]::ReadAllBytes($XmlPath)
  $enc = New-Object Text.UTF8Encoding($false, $true)
  $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
  $text = $enc.GetString($bytes, $(if ($bom) { 3 } else { 0 }), $bytes.Length - $(if ($bom) { 3 } else { 0 }))
  $tagOld = "<workingdirectory>$Old</workingdirectory>"
  if ([regex]::Matches($text, [regex]::Escape($tagOld)).Count -ne 1 -or [regex]::Matches($text, '<workingdirectory>').Count -ne 1) { Stop-V2 'XML: поточна workingdirectory не збігається з очікуваною' }
  $newText = $text.Replace($tagOld, "<workingdirectory>$New</workingdirectory>")
  $body = $enc.GetBytes($newText)
  $out = if ($bom) { [byte[]](0xEF, 0xBB, 0xBF) + $body } else { $body }
  $expectLen = $bytes.Length - $enc.GetByteCount($Old) + $enc.GetByteCount($New)
  if ($out.Length -ne $expectLen) { Stop-V2 'XML: довжина після заміни ≠ очікуваній (змінено щось, крім workingdirectory)' }
  [IO.File]::WriteAllBytes($XmlPath, $out)                     # truncate на місці — DACL файла не змінюється
  $text = $null; $newText = $null
  if ((Get-V2UpXmlWorkdir $XmlPath) -ne $New) { Stop-V2 'XML: read-back workingdirectory ≠ новій' }
  "PASS  XML: workingdirectory $Old → $New (інші байти без змін; SHA256 $(Get-V2UpSha $XmlPath))"
}
# Заміна значення ОДНІЄЇ змінної <env name="…" value="…"/> у XML служби: значення не виводяться і не повертаються;
# перевіряється, що змінилося лише воно (довжина файлу = стара − старе значення + нове), решта байтів (інші секрети) незмінна.
function Set-V2UpXmlEnvValue {
  param([Parameter(Mandatory)] [string] $XmlPath, [Parameter(Mandatory)] [ValidatePattern('^[A-Z0-9_]+$')] [string] $Name, [Parameter(Mandatory)] [string] $NewValue)
  if ($NewValue -notmatch '^[A-Za-z0-9+/=]{32,256}$') { Stop-V2 "нове значення $Name поза дозволеною формою (base64)" }
  $bytes = [IO.File]::ReadAllBytes($XmlPath)
  $enc = New-Object Text.UTF8Encoding($false, $true)
  $off = if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { 3 } else { 0 }
  $text = $enc.GetString($bytes, $off, $bytes.Length - $off)
  $rx = '<env name="' + $Name + '" value="([^"]*)"\s*/>'
  $m = [regex]::Matches($text, $rx)
  if ($m.Count -ne 1) { Stop-V2 "XML: очікується рівно одна змінна $Name ($($m.Count))" }
  $old = $m[0].Groups[1]
  if ($old.Value.Length -lt 32) { Stop-V2 "XML: поточне значення $Name коротше за 32 символи (не замінюється без перевірки людиною)" }
  if ($old.Value -ceq $NewValue) { Stop-V2 "нове значення $Name збігається з поточним" }
  $newText = $text.Substring(0, $old.Index) + $NewValue + $text.Substring($old.Index + $old.Length)
  $body = $enc.GetBytes($newText)
  $out = if ($off) { [byte[]](0xEF, 0xBB, 0xBF) + $body } else { $body }
  if ($out.Length -ne $bytes.Length - $enc.GetByteCount($old.Value) + $enc.GetByteCount($NewValue)) { Stop-V2 'XML: довжина після заміни ≠ очікуваній' }
  $prefixOk = $true; for ($i = 0; $i -lt $off + $enc.GetByteCount($text.Substring(0, $old.Index)); $i++) { if ($out[$i] -ne $bytes[$i]) { $prefixOk = $false; break } }
  $tailLen = $enc.GetByteCount($text.Substring($old.Index + $old.Length))
  $tailOk = $true; for ($i = 1; $i -le $tailLen; $i++) { if ($out[$out.Length - $i] -ne $bytes[$bytes.Length - $i]) { $tailOk = $false; break } }
  if (-not $prefixOk -or -not $tailOk) { Stop-V2 'XML: змінено щось, крім значення змінної' }
  [IO.File]::WriteAllBytes($XmlPath, $out)
  $text = $null; $newText = $null
  $check = [regex]::Matches($enc.GetString([IO.File]::ReadAllBytes($XmlPath)), $rx)
  if ($check.Count -ne 1 -or $check[0].Groups[1].Value -cne $NewValue) { Stop-V2 "XML: read-back $Name не підтверджено" }
  "PASS  XML: значення $Name замінено (значення не виводяться; інші байти незмінні; SHA256 $(Get-V2UpSha $XmlPath))"
}function Restore-V2UpBytes([string]$Path, [string]$Copy, [string]$Sha) {
  if ((Get-V2UpSha $Copy) -ne $Sha) { Stop-V2 "копія $Copy пошкоджена (SHA256 ≠ збереженому)" }
  [IO.File]::WriteAllBytes($Path, [IO.File]::ReadAllBytes($Copy))
  if ((Get-V2UpSha $Path) -ne $Sha) { Stop-V2 "$Path після відновлення: SHA256 ≠ оригіналу" }
  "PASS  $Path відновлено побайтово (SHA256 $Sha)"
}

# =====================================================================================================================
# Резервні копії й відновлення БД (v2_db_tool), venv
# =====================================================================================================================
$V2UpDbs = @(@{ Db = 'integrity_v2.db'; Kind = 'integrity' }, @{ Db = 'v2_auth.db'; Kind = 'auth' })
function Backup-V2UpDatabases {
  param([Parameter(Mandatory)] [string] $Dir, [Parameter(Mandatory)] [hashtable] $Versions, [switch] $Strict)
  $items = foreach ($d in $V2UpDbs) {
    $src = Join-Path "$V2Root\data" $d.Db; $dst = Join-Path $Dir $d.Db; $v = [int]$Versions[$d.Kind]
    $al = @('backup', $src, $dst, '--expect-version', "$v", '--kind', $d.Kind); if ($Strict) { $al += '--strict' }
    $r = Invoke-V2UpDbTool $al
    $sha = Get-V2UpSha $dst
    if ($r -notmatch "^BACKUP OK user_version=$v rows=(\d+) .*restore-test=ok sha256=$sha$") { Stop-V2 "резервна копія $($d.Db) не підтверджена: $r" }
    $rows = [int]$Matches[1]
    $fp = if ($d.Kind -eq 'integrity') { Invoke-V2UpDbTool @('fingerprint', $dst) } else { $null }
    [ordered]@{ Db = $d.Db; Kind = $d.Kind; Version = $v; File = (Split-Path $dst -Leaf); Sha256 = $sha; Rows = $rows; Fingerprint = $fp }
  }
  @($items)
}
function Assert-V2UpBackupItems([string]$Dir, $Items) {
  foreach ($it in $Items) {
    $p = Join-Path $Dir $it.File
    if ((Get-V2UpSha $p) -ne $it.Sha256) { Stop-V2 "копія $($it.File): SHA256 ≠ зафіксованому" }
    $v = Invoke-V2UpDbTool @('verify', $p, '--expect-version', "$($it.Version)")
    if ($v -notlike 'VERIFY OK*') { Stop-V2 "копія $($it.File): $v" }
    $s = Invoke-V2UpDbTool @('schema', $p, '--kind', $it.Kind, '--expect-version', "$($it.Version)")
    if ($s -notlike '* SCHEMA OK*') { Stop-V2 "копія $($it.File): $s" }
    "PASS  копія $($it.File): SHA256, user_version $($it.Version), строга схема"
  }
}
# Відновлення обох БД із перевіреної копії: backend зупинено, файли вільні; на час операції start type backend = Disabled
# (SCM не стартує службу, зокрема через onfailure restart); RESTORE-FAILED блокує старт до рішення людини.
function Restore-V2UpDatabases {
  param([Parameter(Mandatory)] [string] $Dir, [Parameter(Mandatory)] $Items, [Parameter(Mandatory)] [string] $Stamp, [Parameter(Mandatory)] [string] $AsideDir)
  $data = "$V2Root\data"
  $svc = Get-V2UpService $V2UpBackend
  if (-not $svc -or $svc.State -ne 'Stopped' -or $svc.ProcessId) { Stop-V2 'відновлення БД: backend не зупинено' }
  if (-not $V2UpSim -and @(Get-V2Listeners -Ports @(8100)).Count) { Stop-V2 'відновлення БД: порт 8100 слухається' }
  $null = Assert-V2NoRestoreBlock -DataDir $data
  foreach ($l in @(Assert-V2UpBackupItems -Dir $Dir -Items $Items)) { $l }
  $null = Assert-V2DbFilesFree -DataDir $data
  $origMode = if ($svc.StartMode -eq 'Auto') { 'delayed-auto' } else { 'demand' }
  $null = Set-V2UpStartMode $V2UpBackend 'disabled'
  $prog = Join-Path $data "RESTORE-IN-PROGRESS-$Stamp.txt"
  [IO.File]::WriteAllText($prog, "restore started $Stamp (Update/Rollback-V2InPlace)`n", (New-Object Text.UTF8Encoding $false))
  $done = New-Object System.Collections.Generic.List[string]
  try {
    foreach ($it in $Items) {
      foreach ($sfx in '', '-journal', '-wal', '-shm') {
        $f = Join-Path $data ($it.Db + $sfx)
        if (Test-Path -LiteralPath $f) { Rename-Item -LiteralPath $f -NewName "$($it.Db)$sfx.replaced-$Stamp" -ErrorAction Stop; $done.Add("$($it.Db)$sfx → .replaced-$Stamp") }
      }
      $r = Invoke-V2UpDbTool @('restore', (Join-Path $Dir $it.File), (Join-Path $data $it.Db), '--expect-version', "$($it.Version)", '--sha256', $it.Sha256, '--kind', $it.Kind, '--strict')
      if ($r -notlike "RESTORE OK user_version=$($it.Version) rows=$($it.Rows) *") { Stop-V2 "відновлення $($it.Db): $r" }
      if ($it.Fingerprint -and (Invoke-V2UpDbTool @('fingerprint', (Join-Path $data $it.Db))) -ne $it.Fingerprint) { Stop-V2 "відновлена $($it.Db): відбиток ≠ копії" }
      $null = Assert-V2SqliteSidecars -DbPath (Join-Path $data $it.Db)
      $done.Add("$($it.Db) ← $($it.File)")
    }
  } catch {
    $why = $_.Exception.Message -replace '^STOP: ', ''
    try { Rename-Item -LiteralPath $prog -NewName "RESTORE-FAILED-$Stamp.txt" -ErrorAction Stop; [IO.File]::AppendAllText((Join-Path $data "RESTORE-FAILED-$Stamp.txt"), "причина: $why`nвиконано: $($done -join '; ')`nbackend лишається Disabled; старт лише за рішенням людини`n") } catch { }
    Stop-V2 "ВІДНОВЛЕННЯ БД НЕВДАЛЕ: $why; виконано: $($done -join '; '); RESTORE-FAILED блокує старт backend, start type = Disabled"
  }
  Rename-Item -LiteralPath $prog -NewName "RESTORE-OK-$Stamp.txt" -ErrorAction Stop
  $null = Set-V2UpStartMode $V2UpBackend $origMode
  # Замінені файли (post-migration) — у адміністративний каталог копії; у data\ не лишаються копії з правом Modify для служби
  $null = New-Item -ItemType Directory -Path $AsideDir -Force
  foreach ($f in @(Get-ChildItem -LiteralPath $data -File -Filter "*.replaced-$Stamp")) {
    $t = Join-Path $AsideDir $f.Name; [IO.File]::Copy($f.FullName, $t, $false)
    if ((Get-V2UpSha $t) -ne (Get-V2UpSha $f.FullName)) { Stop-V2 "копія $($f.Name) не підтверджена" }
    Remove-Item -LiteralPath $f.FullName -Force
  }
  "PASS  БД відновлено: $($done -join '; '); маркер RESTORE-OK-$Stamp; start type backend повернуто ($origMode); замінені файли → $AsideDir"
}
# Копія venv — ZIP (точні байти; шляхи pip у venv довгі, а каталог копії глибший за живий venv — MAX_PATH)
function Save-V2UpVenvZip([string]$Venv, [string]$Zip, [string]$ManifestPath) {
  Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
  $m = Get-V2UpTreeManifest $Venv
  [IO.Compression.ZipFile]::CreateFromDirectory($Venv, $Zip, [IO.Compression.CompressionLevel]::Fastest, $false)
  Write-V2UpManifest $ManifestPath $m
  $diff = @(Compare-V2UpManifest $m (Get-V2UpZipManifest $Zip))
  if ($diff.Count) { Stop-V2 "копія venv (ZIP) ≠ живому: $($diff | Select-Object -First 5)" }
  "PASS  копія venv: $($m.Count) файлів → $Zip = маніфест ($ManifestPath)"
}
function Get-V2UpZipManifest([string]$Zip) {
  Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
  $m = [ordered]@{}
  $z = [IO.Compression.ZipFile]::OpenRead($Zip)
  try {
    foreach ($ze in @($z.Entries | Sort-Object FullName)) {
      $n = $ze.FullName.Replace('\', '/')
      if ($n.EndsWith('/')) { continue }
      if ($n.StartsWith('/') -or ($n -split '/') -contains '..' -or $n.Contains(':')) { Stop-V2 "ZIP: недопустимий запис $n" }
      $m[$n] = Get-V2UpStreamSha $ze.Open()
    }
  } finally { $z.Dispose() }
  $m
}
function Restore-V2UpVenv([string]$BackupZip, [string]$ManifestPath, [string]$Stamp) {
  $want = Read-V2UpSums $ManifestPath
  $diff = @(Compare-V2UpManifest $want (Get-V2UpZipManifest $BackupZip))
  if ($diff.Count) { Stop-V2 "копія venv не відповідає маніфесту: $($diff | Select-Object -First 5)" }
  $live = "$V2Root\venv"; $aside = 'venv.old'                     # коротке ім'я: шляхи pip у venv близькі до MAX_PATH
  if (Test-Path -LiteralPath "$V2Root\$aside") { Stop-V2 "$V2Root\$aside уже існує (залишок попереднього відкату) — видаліть вручну" }
  Rename-Item -LiteralPath $live -NewName $aside -ErrorAction Stop
  try {
    [IO.Compression.ZipFile]::ExtractToDirectory($BackupZip, $live)
    $null = Grant-V2UpAcl $live $V2Services[$V2UpBackend].Account '(OI)(CI)RX'
    $diff = @(Compare-V2UpManifest $want (Get-V2UpTreeManifest $live))
    if ($diff.Count) { Stop-V2 "відновлений venv ≠ маніфесту: $($diff | Select-Object -First 5)" }
    $null = Assert-V2UpAclTree $live $V2UpBackend RX code
  } catch {
    $why = $_.Exception.Message
    if (Test-Path -LiteralPath $live) { Remove-Item -LiteralPath $live -Recurse -Force }
    Rename-Item -LiteralPath "$V2Root\$aside" -NewName 'venv' -ErrorAction Stop
    Stop-V2 "venv не відновлено (повернуто стан до спроби): $why"
  }
  $warn = ''
  try { Remove-Item -LiteralPath "$V2Root\$aside" -Recurse -Force } catch { $warn = "; УВАГА: $V2Root\$aside не видалено ($($_.Exception.Message)) — видаліть вручну" }
  "PASS  venv відновлено з копії ($($want.Count) файлів = маніфест), ACL backend RX$warn"
}
function Restore-V2UpDist([string]$Stamp) {
  $fe = "$V2Root\app\frontend"; $prev = "dist.prev-$Stamp"
  if (-not (Test-Path -LiteralPath "$fe\$prev")) { Stop-V2 "немає $fe\$prev" }
  if (Test-Path -LiteralPath "$fe\dist") { Rename-Item -LiteralPath "$fe\dist" -NewName "dist.failed-$Stamp" -ErrorAction Stop }
  Rename-Item -LiteralPath "$fe\$prev" -NewName 'dist' -ErrorAction Stop
  "PASS  dist повернуто з $prev"
}
function Invoke-V2UpLocalSmoke([hashtable]$Versions) {
  $out = New-Object System.Collections.Generic.List[string]
  $ok = $false
  foreach ($i in 1..30) { if ((Get-V2UpHttpStatus '/api/health') -eq 200) { $ok = $true; break }; Start-Sleep 1 }
  if (-not $ok) { Stop-V2 'GET http://127.0.0.1:8100/api/health ≠ 200 за 30 с' }
  $out.Add('PASS  GET /api/health → 200')
  foreach ($c in @(@('GET', '/docs', 401), @('GET', '/redoc', 404), @('POST', '/v2/auth/logout', 403), @('GET', '/api/assessments', 200))) {
    $s = Get-V2UpHttpStatus $c[1] $c[0]
    if ($s -ne $c[2]) { Stop-V2 "$($c[0]) $($c[1]) → $s, очікується $($c[2])" }
    $out.Add("PASS  $($c[0]) $($c[1]) → $s")
  }
  foreach ($d in $V2UpDbs) {
    $v = Invoke-V2UpDbTool @('verify', (Join-Path "$V2Root\data" $d.Db), '--expect-version', "$($Versions[$d.Kind])")
    if ($v -notlike 'VERIFY OK*') { Stop-V2 "$($d.Db): $v" }
    $out.Add("PASS  $($d.Db): user_version $($Versions[$d.Kind])")
  }
  $out.ToArray()
}
function Invoke-V2UpHttpsSmoke([switch]$Headers) {
  $out = New-Object System.Collections.Generic.List[string]
  $ok = $false
  foreach ($i in 1..15) { try { $null = Assert-V2UpHttps '/api/health' 200; $ok = $true; break } catch { Start-Sleep 2 } }
  if (-not $ok) { $null = Assert-V2UpHttps '/api/health' 200 }
  foreach ($c in @(@('/', 200), @('/api/health', 200), @('/docs', 401), @('/redoc', 404), @('/assets/missing.js', 404))) { $out.Add((Assert-V2UpHttps $c[0] $c[1])) }
  if ($Headers) {
    $h = Get-V2UpHttpsHeaders '/'
    if (-not $h.ContainsKey('content-security-policy') -or $h['content-security-policy'] -notmatch "default-src 'self'" -or $h.ContainsKey('server') -or -not $h.ContainsKey('permissions-policy')) { Stop-V2 "HTTPS /: заголовки безпеки неповні (CSP/Permissions-Policy/без Server)" }
    $d = Get-V2UpHttpsHeaders '/docs'
    if (-not $d.ContainsKey('content-security-policy') -or $d['content-security-policy'] -notmatch "'sha256-") { Stop-V2 'HTTPS /docs: немає CSP із sha256' }
    $out.Add('PASS  HTTPS заголовки: CSP SPA, CSP /docs (sha256), Permissions-Policy, без Server')
  }
  $out.ToArray()
}
