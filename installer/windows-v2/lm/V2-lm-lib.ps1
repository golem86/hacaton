# V2-lm-lib.ps1 — спільні функції служби локальної LM (llama.cpp llama-server, OpenAI-сумісний API) для V2.
# Windows PowerShell 5.1, від адміністратора, неінтерактивно (придатно для SSH). Підключення (на рівні скрипта):
#   . "$PSScriptRoot\V2-lm-lib.ps1"; [-Simulate: . upgrade\sim\V2-upgrade-sim.ps1; . lm\sim\V2-lm-sim.ps1]; Initialize-V2Up …; Register-V2LmEntry
# Принципи ті самі, що в upgrade\V2-upgrade-lib.ps1: fail-closed; жодних Read-Host; секрет (ключ API) ніколи не виводиться й не
# пишеться в журнал/доказ (лише SHA256 файлів цілком); XML backend змінюється побайтово (додається/видаляється ОДИН рядок <env>).
# Адаптери (розділ «адаптери») — єдині точки дотику до SCM, процесів, мережі, пам'яті й нативного бінарника; -Simulate
# підміняє лише їх (lm\sim\V2-lm-sim.ps1), уся решта (ZIP, SHA256, файли, XML) виконується справжньою.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'upgrade\V2-upgrade-lib.ps1')
$ErrorActionPreference = 'Stop'

$V2LmName = 'integrity-v2-lm'
$V2LmPort = 8200
$V2LmUrl = 'http://127.0.0.1:8200'
$V2LmModelFile = 'Qwen3-8B-Q4_K_M.gguf'
# Зафіксовані артефакти (погоджує власник; інтегратор може передати інші значення параметрами або -ApprovedSums)
$V2LmModelSha256 = 'd98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785'   # Qwen/Qwen3-8B-GGUF, 5,03 ГБ
$V2LmZipName = 'llama-b12180-bin-win-cpu-x64.zip'
$V2LmZipSha256 = 'b272cddf0e9c0692df0587b6f4cb8de4296e2d136b1b5b095ac0fe9807deeb20'     # ggml-org/llama.cpp b12180, CPU x64
$V2LmLibDir = $PSScriptRoot
$V2LmKeyFileRel = 'lm\secrets\api-key.txt'
# Прапорці, які мусить знати llama-server.exe (перевірка `--help` справжнього бінарника до реєстрації служби)
$V2LmRequiredFlags = @('--model', '--host', '--port', '--ctx-size', '--threads', '--parallel', '--no-webui', '--no-slots', '--jinja', '--reasoning', '--cache-ram', '--prio')
$V2LmEnvAllowed = @('LLAMA_API_KEY')
$V2LmBackendEnv = @('V2_LM_URL', 'V2_LM_API_KEY')

function Register-V2LmEntry {
  # Запис для спільних функцій (Grant-V2, Stop-V2UpService): акаунт, wrapper і порт служби LM у поточному корені
  $V2Services[$V2LmName] = @{ Exe = "$V2Root\services\lm\$V2LmName.exe"; Account = "NT SERVICE\$V2LmName"; Port = $V2LmPort; Job = $null }
}

# =====================================================================================================================
# Адаптери (реальна реалізація). Симуляція перевизначає саме ці функції.
# =====================================================================================================================
function Get-V2LmFreeMemory { [int64](Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1024 }
function Get-V2LmTotalMemory { [int64](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory }
function Get-V2LmListeners { @(Get-V2Listeners -Ports @($V2LmPort) | ForEach-Object { "tcp $($_.LocalAddress):$($_.LocalPort) PID $($_.OwningProcess)" }) }
function Assert-V2LmWinswSource([string]$Path) { Assert-V2Winsw -Path $Path -Label 'WinSW (джерело — wrapper backend)' }
# Текст `--help` (stdout + stderr): llama-server друкує довідку в один із потоків залежно від збірки
function Get-V2LmHelpText([string]$Exe) {
  Assert-V2Exe $Exe 'llama-server --help'
  $psi = New-Object Diagnostics.ProcessStartInfo $Exe, '--help'
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $psi.WorkingDirectory = Split-Path -Parent $Exe
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $p = [Diagnostics.Process]::Start($psi)
  try {
    $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit(60000)) { try { $p.Kill() } catch { }; $null = $p.WaitForExit(10000); Stop-V2 'llama-server --help: тайм-аут 60 с' }
    $p.WaitForExit()
    if ($p.ExitCode -notin 0, 1) { Stop-V2 "llama-server --help → код $($p.ExitCode) (бінарник не запускається: залежності DLL / VC++ runtime / інструкції CPU?)" }
    $o.Result + "`n" + $e.Result
  } finally { $p.Dispose() }
}
function Install-V2LmScm([scriptblock]$OnCreated) { Install-V2Service -Name $V2LmName -OnCreated $OnCreated }
function Uninstall-V2LmScm {
  $s = Get-V2UpService $V2LmName
  if (-not $s) { return "INFO  служби $V2LmName немає" }
  if ($s.State -ne 'Stopped') { Stop-V2 "${V2LmName}: видалення лише зі стану Stopped (зараз $($s.State))" }
  $exe = $V2Services[$V2LmName].Exe
  if ($s.PathName.Trim().Trim('"') -ne $exe) { Stop-V2 "${V2LmName}: чужий PathName $($s.PathName) — не видаляється" }
  if (Test-Path -LiteralPath $exe -PathType Leaf) { $null = Invoke-V2Native -Exe $exe -ArgList @('uninstall') -What "WinSW uninstall $V2LmName" -WorkingDirectory (Split-Path -Parent $exe) }
  else { $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('delete', $V2LmName) -What "sc delete $V2LmName" }
  foreach ($i in 1..20) { if (-not (Get-V2UpService $V2LmName)) { break }; Start-Sleep 1 }
  if (Get-V2UpService $V2LmName) { Stop-V2 "${V2LmName}: SCM досі показує службу (позначена до видалення — закрийте services.msc і повторіть)" }
  "PASS  служба $V2LmName видалена з SCM"
}
function Start-V2LmService {
  $s = Assert-V2UpServiceIdentity $V2LmName
  if ($s.State -ne 'Stopped') { Stop-V2 "${V2LmName}: старт лише зі стану Stopped (зараз $($s.State))" }
  $ctl = Get-Service -Name $V2LmName
  $ctl.Start()
  $ctl.WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
  $now = Get-V2UpService $V2LmName
  if ($now.State -ne 'Running' -or -not $now.ProcessId) { Stop-V2 "${V2LmName}: SCM не підтвердив старт" }
  $tree = Get-V2ServiceTree -Name $V2LmName
  foreach ($p in $tree) { if ($p.Owner -ne $V2Services[$V2LmName].Account) { Stop-V2 "${V2LmName}: PID $($p.Pid) — власник $($p.Owner)" } }
  $l = Wait-V2Listener -Port $V2LmPort -Tree $tree -Addresses @('127.0.0.1') -Seconds 120   # слухач лише 127.0.0.1; чужий → STOP
  $script:V2LmTree = $tree
  "PASS  $V2LmName запущено (PID $($now.ProcessId)); $l"
}
# Усі TCP-слухачі й UDP-кінцеві точки процесів дерева служби (очікується рівно «tcp 127.0.0.1:8200»)
function Get-V2LmEndpoints {
  Add-V2TreeIdentities -Tree $script:V2LmTree
  $pids = @($script:V2LmTree | ForEach-Object { [int]$_.Pid })
  try {
    $t = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $pids -contains [int]$_.OwningProcess } | ForEach-Object { "tcp $($_.LocalAddress):$($_.LocalPort)" })
    $u = @(Get-NetUDPEndpoint -ErrorAction Stop | Where-Object { $pids -contains [int]$_.OwningProcess } | ForEach-Object { "udp $($_.LocalAddress):$($_.LocalPort)" })
  } catch { Stop-V2 "перелік мережевих точок неможливий: $($_.Exception.Message)" }
  @($t + $u | Sort-Object -Unique)
}
function Get-V2LmPriority {
  $p = @($script:V2LmTree | Where-Object { [string]$_.Exe -like '*\llama-server.exe' })
  if ($p.Count -ne 1) { Stop-V2 "у дереві служби llama-server.exe: $($p.Count) (очікується 1)" }
  [string]([Diagnostics.Process]::GetProcessById($p[0].Pid).PriorityClass)
}
function Get-V2LmHttpStatus([string]$Path, [hashtable]$Headers = @{}) { Get-V2HttpStatus -Url "$V2LmUrl$Path" -Headers $Headers }
# Лише читання: скільки правил Firewall посилаються на бінарник (очікується 0; скрипт правил НЕ додає)
function Get-V2LmFirewallRuleCount([string]$Program) {
  try { @(Get-NetFirewallApplicationFilter -Program $Program -ErrorAction Stop).Count } catch { if ($_.Exception.Message -match 'No MSFT_NetApplicationFilter|не знайдено|not found') { 0 } else { -1 } }
}

# =====================================================================================================================
# Вхідні артефакти: суми, ZIP llama.cpp, модель
# =====================================================================================================================
function Resolve-V2LmExpectedSums {
  param([string] $ApprovedSums, [string] $ZipSha256, [string] $ModelSha256, [string] $ZipLeaf, [string] $ModelLeaf)
  $z = $ZipSha256; $m = $ModelSha256
  if ($ApprovedSums) {
    if (-not (Test-Path -LiteralPath $ApprovedSums -PathType Leaf)) { Stop-V2 "немає файла сум $ApprovedSums" }
    $h = Read-V2UpSums $ApprovedSums
    if (-not $h.Contains($ZipLeaf) -or -not $h.Contains($ModelLeaf)) { Stop-V2 "у $ApprovedSums немає рядків для $ZipLeaf і $ModelLeaf" }
    if ($z -and $z -ne $h[$ZipLeaf]) { Stop-V2 "SHA256 $ZipLeaf у параметрі ≠ $ApprovedSums" }
    if ($m -and $m -ne $h[$ModelLeaf]) { Stop-V2 "SHA256 $ModelLeaf у параметрі ≠ $ApprovedSums" }
    $z = $h[$ZipLeaf]; $m = $h[$ModelLeaf]
  }
  if ($z -notmatch '^[0-9a-fA-F]{64}$' -or $m -notmatch '^[0-9a-fA-F]{64}$') { Stop-V2 'очікувані SHA256 мають бути 64 hex-символи' }
  @{ Zip = $z.ToLowerInvariant(); Model = $m.ToLowerInvariant() }
}
# Записи ZIP: без абсолютних шляхів, '..', ':'; llama-server.exe — у корені або в одному каталозі верхнього рівня; усі записи — під ним
function Get-V2LmZipLayout([string]$Zip) {
  Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
  $z = [IO.Compression.ZipFile]::OpenRead($Zip)
  try {
    $names = @($z.Entries | ForEach-Object { $_.FullName.Replace('\', '/') } | Where-Object { -not $_.EndsWith('/') })
  } finally { $z.Dispose() }
  foreach ($n in $names) { if ($n.StartsWith('/') -or ($n -split '/') -contains '..' -or $n.Contains(':')) { Stop-V2 "ZIP: недопустимий запис $n" } }
  $srv = @($names | Where-Object { $_ -match '(?i)^([^/]+/)?llama-server\.exe$' })
  if ($srv.Count -ne 1) { Stop-V2 "ZIP: llama-server.exe знайдено $($srv.Count) раз(и) у корені/першому рівні (очікується 1)" }
  $prefix = $srv[0].Substring(0, $srv[0].Length - 'llama-server.exe'.Length)
  $outside = @($names | Where-Object { -not $_.StartsWith($prefix, [StringComparison]::Ordinal) })
  if ($outside.Count) { Stop-V2 "ZIP: записи поза каталогом llama-server.exe: $($outside | Select-Object -First 3)" }
  [pscustomobject]@{ Prefix = $prefix; Count = $names.Count; Server = $srv[0] }
}
function Expand-V2LmZip([string]$Zip, [string]$Dest, [string]$Prefix) {
  Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
  $m = [ordered]@{}
  $z = [IO.Compression.ZipFile]::OpenRead($Zip)
  try {
    foreach ($ze in @($z.Entries | Sort-Object FullName)) {
      $n = $ze.FullName.Replace('\', '/')
      if ($n.EndsWith('/')) { continue }
      $rel = $n.Substring($Prefix.Length)
      $target = [IO.Path]::GetFullPath((Join-Path $Dest ($rel.Replace('/', '\'))))
      if (-not $target.StartsWith($Dest.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "ZIP: запис $n поза $Dest" }
      $null = New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force
      if (Test-Path -LiteralPath $target) { Stop-V2 "ZIP: повторний запис $rel" }
      $want = Get-V2UpStreamSha $ze.Open()
      $in = $ze.Open(); $out = [IO.File]::Open($target, [IO.FileMode]::CreateNew)
      try { $in.CopyTo($out) } finally { $out.Dispose(); $in.Dispose() }
      if ((Get-V2UpSha $target) -ne $want) { Stop-V2 "ZIP: $rel після розпакування ≠ запису архіву" }
      $m[$rel] = $want
    }
  } finally { $z.Dispose() }
  $m
}
function Test-V2LmHelpFlags([string]$Help) {
  $missing = @($V2LmRequiredFlags | Where-Object { $Help -notmatch ('(?m)(^|[\s,])' + [regex]::Escape($_) + '([\s,=]|$)') })
  if ($missing.Count) { Stop-V2 "llama-server.exe не знає прапорців: $($missing -join ', ') — версія бінарника ≠ очікуваній (b12180)" }
  # Ключ API: файл (не видно в командному рядку) → інакше змінна LLAMA_API_KEY у XML служби LM → інакше STOP
  if ($Help -match '(?m)(^|[\s,])--api-key-file([\s,=]|$)') { return 'File' }
  if ($Help -match 'LLAMA_API_KEY') { return 'Env' }
  Stop-V2 'llama-server.exe не підтримує ні --api-key-file, ні LLAMA_API_KEY — ключ лише в командному рядку (видно в Win32_Process); встановлення зупинено'
}

# =====================================================================================================================
# XML служби LM: генерація з шаблону і сувора перевірка (loopback, NT SERVICE, без секретів у аргументах)
# =====================================================================================================================
function New-V2LmXmlText([string]$Template, [ValidateSet('File', 'Env')] [string]$KeyMode, [string]$Key) {
  $t = [IO.File]::ReadAllText($Template, (New-Object Text.UTF8Encoding($false, $true)))
  if ($t -match '__[A-Z0-9_]+__') { Stop-V2 'шаблон LM містить плейсхолдери — шаблон має бути без секретів і без підстановок' }
  $t = $t.Replace('C:\srv\integrity-v2', $V2Root)
  $nl = if ($t.Contains("`r`n")) { "`r`n" } else { "`n" }
  if ($KeyMode -eq 'Env') {
    $arg = " --api-key-file $V2Root\$V2LmKeyFileRel"
    if (-not $t.Contains($arg)) { Stop-V2 'шаблон LM: немає аргументу --api-key-file' }
    if ($Key -notmatch '^[A-Za-z0-9+/=]{32,256}$') { Stop-V2 'ключ API поза дозволеною формою' }
    $t = $t.Replace($arg, '')
    $anchor = '  <priority>'
    if (-not $t.Contains($anchor)) { Stop-V2 'шаблон LM: немає <priority>' }
    $t = $t.Replace($anchor, "  <env name=`"LLAMA_API_KEY`" value=`"$Key`"/>$nl$anchor")
  }
  $t
}
$V2LmWinswAllowed = @($WinswAllowed) + 'priority'
function Test-V2LmXml {
  param([Parameter(Mandatory)] [string] $XmlPath, [ValidateSet('File', 'Env', 'Any')] [string] $KeyMode = 'Any', [string] $Root = $V2Root)
  [xml]$x = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
  $s = $x.SelectSingleNode('/service'); if (-not $s) { Stop-V2 'XML LM: немає <service>' }
  $bad = @($s.ChildNodes | Where-Object { $_.NodeType -eq 'Element' -and $V2LmWinswAllowed -notcontains $_.LocalName } | ForEach-Object LocalName)
  if ($bad.Count) { Stop-V2 "XML LM: недокументовані елементи: $($bad -join ', ')" }
  $one = { param($xp) $n = $s.SelectSingleNode($xp); if ($n) { $n.InnerText } else { $null } }
  if ((& $one 'id') -ne $V2LmName) { Stop-V2 "XML LM: id = $(& $one 'id')" }
  if ((& $one 'startmode') -ne 'Manual') { Stop-V2 'XML LM: startmode має бути Manual (Automatic (Delayed) — через sc config після перевірки)' }
  $sa = $s.SelectSingleNode('serviceaccount')
  $saKids = if ($sa) { @($sa.ChildNodes | Where-Object { $_.NodeType -eq 'Element' } | ForEach-Object LocalName | Sort-Object) -join ',' } else { '' }
  if ($saKids -ne 'domain,user' -or (& $one 'serviceaccount/domain') -ne 'NT SERVICE' -or (& $one 'serviceaccount/user') -ne $V2LmName) { Stop-V2 "XML LM: serviceaccount має бути рівно NT SERVICE\$V2LmName" }
  if ((& $one 'executable') -ne "$Root\lm\bin\llama-server.exe") { Stop-V2 "XML LM: executable = $(& $one 'executable')" }
  if ((& $one 'logpath') -ne "$Root\logs\lm") { Stop-V2 "XML LM: logpath = $(& $one 'logpath')" }
  if ((& $one 'priority') -ne 'BelowNormal') { Stop-V2 "XML LM: priority = $(& $one 'priority') (очікується BelowNormal)" }
  if (@($s.SelectNodes('onfailure') | Where-Object { $_.GetAttribute('action') -eq 'restart' }).Count -lt 1) { Stop-V2 'XML LM: немає onfailure restart' }
  $tok = @(([string](& $one 'arguments')) -split '\s+' | Where-Object { $_ })
  $argOf = { param($flag) $i = [array]::IndexOf($tok, $flag); if ($i -ge 0 -and $i + 1 -lt $tok.Count) { $tok[$i + 1] } else { $null } }
  if (@($tok | Where-Object { $_ -eq '--host' }).Count -ne 1 -or (& $argOf '--host') -ne '127.0.0.1') { Stop-V2 'XML LM: --host має бути рівно 127.0.0.1 (лише loopback)' }
  if (@($tok | Where-Object { $_ -eq '--port' }).Count -ne 1 -or (& $argOf '--port') -ne "$V2LmPort") { Stop-V2 "XML LM: --port має бути $V2LmPort" }
  if ((& $argOf '-m') -ne "$Root\lm\models\$V2LmModelFile") { Stop-V2 "XML LM: -m = $(& $argOf '-m')" }
  foreach ($f in '--no-webui', '--no-slots') { if ($tok -notcontains $f) { Stop-V2 "XML LM: немає $f" } }
  foreach ($kv in @(@('-c', '8192'), @('--parallel', '1'), @('--reasoning', 'off'), @('--cache-ram', '0'), @('--prio', '-1'))) {
    if ((& $argOf $kv[0]) -ne $kv[1]) { Stop-V2 "XML LM: очікується $($kv[0]) $($kv[1])" }
  }
  if ((& $argOf '-t') -notmatch '^[1-9][0-9]?$') { Stop-V2 'XML LM: -t має бути 1..99' }
  if (@($tok | Where-Object { $_ -match '^(0\.0\.0\.0|::|\[::\]|--listen)$' }).Count) { Stop-V2 'XML LM: адреса поза loopback' }
  if ($tok -contains '--api-key' -or $tok -contains '-v' -or $tok -contains '--verbose' -or $tok -contains '--log-verbose') { Stop-V2 'XML LM: ключ у командному рядку або докладний журнал (промпти в журналі) заборонені' }
  $envs = @($s.SelectNodes('env'))
  foreach ($e in $envs) { if ($V2LmEnvAllowed -notcontains $e.GetAttribute('name')) { Stop-V2 "XML LM: недозволена змінна $($e.GetAttribute('name'))" } }
  $hasFile = $tok -contains '--api-key-file'
  $mode = if ($hasFile -and -not $envs.Count) { 'File' } elseif (-not $hasFile -and $envs.Count -eq 1) { 'Env' } else { Stop-V2 'XML LM: має бути рівно одне джерело ключа (--api-key-file або LLAMA_API_KEY)' }
  if ($mode -eq 'File' -and (& $argOf '--api-key-file') -ne "$Root\$V2LmKeyFileRel") { Stop-V2 "XML LM: --api-key-file = $(& $argOf '--api-key-file')" }
  if ($mode -eq 'Env' -and $envs[0].GetAttribute('value') -notmatch '^[A-Za-z0-9+/=]{32,256}$') { Stop-V2 'XML LM: LLAMA_API_KEY поза дозволеною формою' }
  if ($KeyMode -ne 'Any' -and $mode -ne $KeyMode) { Stop-V2 "XML LM: джерело ключа $mode ≠ $KeyMode" }
  if ([IO.File]::ReadAllText($XmlPath) -match '__[A-Z0-9_]+__') { Stop-V2 'XML LM: незаповнені плейсхолдери' }
  "PASS  XML $V2LmName — WinSW $WinswRefVersion, Manual, NT SERVICE\$V2LmName, 127.0.0.1:$V2LmPort, BelowNormal, ключ: $mode"
}

# =====================================================================================================================
# XML backend: додавання / видалення ОДНОГО рядка <env> (решта байтів незмінна; значення не виводяться)
# =====================================================================================================================
function Read-V2LmXmlBytes([string]$XmlPath) {
  $bytes = [IO.File]::ReadAllBytes($XmlPath)
  $enc = New-Object Text.UTF8Encoding($false, $true)
  $off = if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { 3 } else { 0 }
  @{ Bytes = $bytes; Enc = $enc; Off = $off; Text = $enc.GetString($bytes, $off, $bytes.Length - $off) }
}
function Write-V2LmXmlSplice($R, [int]$Pos, [int]$RemoveLen, [string]$Insert, [string]$XmlPath) {
  # Нові байти = префікс (без змін) + вставка + суфікс (без змін); перевірка побайтово до запису
  $t = $R.Text; $enc = $R.Enc
  $newText = $t.Substring(0, $Pos) + $Insert + $t.Substring($Pos + $RemoveLen)
  $body = $enc.GetBytes($newText)
  $out = if ($R.Off) { [byte[]](0xEF, 0xBB, 0xBF) + $body } else { $body }
  $pre = $R.Off + $enc.GetByteCount($t.Substring(0, $Pos)); $tail = $enc.GetByteCount($t.Substring($Pos + $RemoveLen))
  if ($out.Length -ne $R.Bytes.Length - $enc.GetByteCount($t.Substring($Pos, $RemoveLen)) + $enc.GetByteCount($Insert)) { Stop-V2 'XML: довжина після зміни ≠ очікуваній' }
  for ($i = 0; $i -lt $pre; $i++) { if ($out[$i] -ne $R.Bytes[$i]) { Stop-V2 'XML: змінено байти перед рядком' } }
  for ($i = 1; $i -le $tail; $i++) { if ($out[$out.Length - $i] -ne $R.Bytes[$R.Bytes.Length - $i]) { Stop-V2 'XML: змінено байти після рядка' } }
  [IO.File]::WriteAllBytes($XmlPath, $out)                     # truncate на місці — DACL файла не змінюється
}
function Add-V2LmXmlEnv {
  param([Parameter(Mandatory)] [string] $XmlPath, [Parameter(Mandatory)] [ValidatePattern('^V2_LM_[A-Z_]+$')] [string] $Name, [Parameter(Mandatory)] [string] $Value)
  if ($Value -notmatch '^(http://127\.0\.0\.1:\d{2,5}|[A-Za-z0-9+/=]{32,256})$') { Stop-V2 "значення $Name поза дозволеною формою" }
  $R = Read-V2LmXmlBytes $XmlPath
  if ([regex]::Matches($R.Text, '<env name="' + $Name + '"').Count) { Stop-V2 "XML: змінна $Name уже є" }
  $m = [regex]::Matches($R.Text, '(?m)^[ \t]*<env name="[A-Za-z0-9_]+" value="[^"]*"\s*/>[ \t]*\r?\n')
  if (-not $m.Count) { Stop-V2 'XML: немає рядків <env> — місце вставки невідоме' }
  $last = $m[$m.Count - 1]
  $indent = [regex]::Match($last.Value, '^[ \t]*').Value
  $nl = if ($last.Value.EndsWith("`r`n")) { "`r`n" } else { "`n" }
  Write-V2LmXmlSplice $R ($last.Index + $last.Length) 0 "$indent<env name=`"$Name`" value=`"$Value`"/>$nl" $XmlPath
  $R = $null
  [xml]$chk = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
  $n = @($chk.SelectNodes('/service/env') | Where-Object { $_.GetAttribute('name') -eq $Name })
  if ($n.Count -ne 1 -or $n[0].GetAttribute('value') -cne $Value) { Stop-V2 "XML: read-back $Name не підтверджено" }
  "PASS  XML: додано $Name (значення не виводиться; інші байти незмінні; SHA256 $(Get-V2UpSha $XmlPath))"
}
function Remove-V2LmXmlEnv {
  param([Parameter(Mandatory)] [string] $XmlPath, [Parameter(Mandatory)] [ValidatePattern('^V2_LM_[A-Z_]+$')] [string] $Name)
  $R = Read-V2LmXmlBytes $XmlPath
  $m = [regex]::Matches($R.Text, '(?m)^[ \t]*<env name="' + $Name + '" value="[^"]*"\s*/>[ \t]*\r?\n')
  if ($m.Count -eq 0) { return "INFO  XML: змінної $Name немає" }
  if ($m.Count -ne 1 -or [regex]::Matches($R.Text, '<env name="' + $Name + '"').Count -ne 1) { Stop-V2 "XML: змінна $Name має неочікувану форму або повторюється" }
  Write-V2LmXmlSplice $R $m[0].Index $m[0].Length '' $XmlPath
  $R = $null
  if ([IO.File]::ReadAllText($XmlPath).Contains("<env name=`"$Name`"")) { Stop-V2 "XML: $Name не видалено" }
  "PASS  XML: видалено $Name (інші байти незмінні; SHA256 $(Get-V2UpSha $XmlPath))"
}
function Get-V2LmBackendEnvNames([string]$XmlPath) {
  [xml]$x = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
  @($x.SelectNodes('/service/env') | ForEach-Object { $_.GetAttribute('name') } | Where-Object { $_ -like 'V2_LM_*' })
}
function Wait-V2LmHealth([int]$Seconds) {
  $last = 0
  $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
  while ([DateTime]::UtcNow -lt $deadline) {
    $last = Get-V2LmHttpStatus '/health'
    if ($last -eq 200) { return "PASS  GET $V2LmUrl/health → 200" }
    $s = Get-V2UpService $V2LmName
    if (-not $s -or $s.State -ne 'Running') { Stop-V2 "${V2LmName}: служба вийшла зі стану Running під час завантаження моделі (журнал logs\lm)" }
    Start-Sleep 2
  }
  Stop-V2 "GET $V2LmUrl/health → $last за $Seconds с (503 — модель ще вантажиться або не вистачає пам'яті; журнал logs\lm)"
}
function Wait-V2LmBackendHealth {
  foreach ($i in 1..30) { if ((Get-V2UpHttpStatus '/api/health') -eq 200) { return 'PASS  GET http://127.0.0.1:8100/api/health → 200' }; Start-Sleep 1 }
  Stop-V2 'GET http://127.0.0.1:8100/api/health ≠ 200 за 30 с'
}
