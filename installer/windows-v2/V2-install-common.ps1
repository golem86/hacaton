# Спільні функції встановлення Integrity Management Dashboard V2 — INSTALLATION REV3 + адресні виправлення P1–P6 (19.11).
# Підключення:  . .\V2-install-common.ps1   (Windows PowerShell 5.1, від адміністратора; файл — UTF-8 з BOM)
# Принцип: fail-closed. Кожна функція або повертає підтверджений результат, або кидає виняток 'STOP: …'.
# Функції НЕ змінюють ACL спільних каталогів (C:\, C:\srv), чинні служби, Caddy V1, Firewall, Tailscale.
# Процеси зупиняються ЛИШЕ через збережені handle процесів, ідентичність яких підтверджено; Stop-Process за PID не використовується.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop  # deterministic Get-FileHash under isolated TEMP

$V2Root = 'C:\srv\integrity-v2'
$V2Services = @{
  'integrity-v2-backend' = @{ Exe = 'C:\srv\integrity-v2\services\backend\integrity-v2-backend.exe'; Account = 'NT SERVICE\integrity-v2-backend'; Port = 8100
                              Job = $null }   # ЕКСПЕРИМЕНТ (етап 2): ім'я Job Object launcher-а; $null — модель повноти не затверджена → відкат backend BLOCKED
  'integrity-v2-caddy'   = @{ Exe = 'C:\srv\integrity-v2\services\caddy\integrity-v2-caddy.exe';     Account = 'NT SERVICE\integrity-v2-caddy';   Port = 443; Job = $null }   # Job явно: Stop-V2ServiceCore читає .Job (без поля — помилка StrictMode, зупинка Caddy неможлива)
}
$SidAdmins = 'S-1-5-32-544'; $SidSystem = 'S-1-5-18'
$V2JobTool = @{ Py = $null; Script = $null }
$V2BackendName = 'integrity-v2-backend'   # служба, чиї БД відновлюються; змінює лише runtime-harness.ps1 на ізольованому тест-хості (static P24)
$V2JobLocalRehearsal = $null   # ЛИШЕ rehearse-rev3.ps1 (локальна адаптація без прав адміністратора): @{ Baseline = <знімок>; ExcludePid = @(…) }. Production — $null → --unknown block   # ЕКСПЕРИМЕНТ: інтерпретатор і v2_job_launcher.py (задаються лише для тестового режиму Job Object)
$SidTrustedInstaller = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
# Еталон Caddy: caddy.exe з офіційного caddy_2.11.9_windows_amd64.zip; №4 підтвердив MATCH із серверним exe (19.11)
$CaddyRefSha256 = '2622e239c79df700b0eb92cbd950d1edee365e155a7859f358f0e55f002df591'
# P6: WinSW — фактичні дані №4 (19.11): HacatonBackend.exe, FileVersion 2.12.0.0
$WinswRefVersion = '2.12.0'
$WinswRefSha256 = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'
$V2Ports = @(8100, 443, 8199)
$V2Identity = @{}                                    # збережені дерева процесів служб (P3/P4), ключ — ім'я служби

function Stop-V2([string]$m) { throw "STOP: $m" }

# =====================================================================================================================
# OS-адаптер — ЄДИНІ точки дотику до реальних процесів, портів і змінних середовища. Тести підміняють саме їх.
# =====================================================================================================================
function Get-V2CimProcess([int]$Id) { Get-CimInstance Win32_Process -Filter "ProcessId=$Id" }
function Get-V2CimProcessList { @(Get-CimInstance Win32_Process) }
function Get-V2CimOwner($CimProcess) { Invoke-CimMethod -InputObject $CimProcess -MethodName GetOwner }
function Get-V2Listeners([int[]]$Ports) {
  try { @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $Ports -contains [int]$_.LocalPort }) }
  catch { Stop-V2 "TCP enumeration неможлива: $($_.Exception.Message)" }
}
function Get-V2UdpEndpoints([int[]]$Ports) {
  try { @(Get-NetUDPEndpoint -ErrorAction Stop | Where-Object { $Ports -contains [int]$_.LocalPort }) }
  catch { Stop-V2 "UDP enumeration неможлива: $($_.Exception.Message)" }
}
function Get-V2HostInfo {                                                       # адаптер (лише читання): ціль Windows / PowerShell / ресурси
  $drv = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($V2SrvPath))
  [pscustomobject]@{ PSVersion = "$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)"; PSEdition = $PSVersionTable.PSEdition; Is64 = [Environment]::Is64BitOperatingSystem -and [Environment]::Is64BitProcess
                     Build = [Environment]::OSVersion.Version.Build; Drive = $drv.Name; FreeBytes = $drv.AvailableFreeSpace }
}
function Open-V2ProcessHandle([int]$Id) { $p = [Diagnostics.Process]::GetProcessById($Id); $null = $p.Handle; $p }   # handle відкривається й кешується одразу
function Get-V2HandleStartTicks($Process) { $Process.StartTime.ToUniversalTime().Ticks }
function Test-V2HandleExited($Process) { [bool]$Process.HasExited }
function Stop-V2Handle($Process) { $Process.Kill() }                    # лише збережений handle; PID reuse неможливий, поки handle відкритий
function Wait-V2Handle($Process, [int]$Ms) { [bool]$Process.WaitForExit($Ms) }
function Get-V2EnvVar([string]$Name) { [Environment]::GetEnvironmentVariable($Name, 'Process') }
function Set-V2EnvVar([string]$Name, $Value) { [Environment]::SetEnvironmentVariable($Name, $Value, 'Process') }
function Get-V2Acl([string]$Path) {
  if (Test-Path -LiteralPath $Path -PathType Container) {
    if ($PSVersionTable.PSEdition -eq 'Core') { [System.IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($Path)) }
    else { [IO.Directory]::GetAccessControl($Path) }
  }
  elseif (Test-Path -LiteralPath $Path -PathType Leaf) {
    if ($PSVersionTable.PSEdition -eq 'Core') { [System.IO.FileSystemAclExtensions]::GetAccessControl([IO.FileInfo]::new($Path)) }
    else { [IO.File]::GetAccessControl($Path) }
  }
  else { Stop-V2 "ACL: шлях відсутній: $Path" }
}

# =====================================================================================================================
# Зовнішні програми — підтверджений запуск і свіжий код (REV3, R2-04); P2: тайм-аут не приховує помилку Kill і підтверджує вихід
# =====================================================================================================================
function ConvertTo-V2Arg([string]$a) {                       # правила розбору командного рядка MSVCRT/CommandLineToArgvW
  if ($a -eq '') { return '""' }
  if ($a -notmatch '[\s"]') { return $a }
  $sb = New-Object Text.StringBuilder; [void]$sb.Append('"'); $bs = 0
  foreach ($ch in $a.ToCharArray()) {
    if ($ch -eq '\') { $bs++; continue }
    if ($ch -eq '"') { [void]$sb.Append('\' * (2 * $bs + 1)).Append('"') } else { [void]$sb.Append('\' * $bs).Append($ch) }
    $bs = 0
  }
  [void]$sb.Append('\' * (2 * $bs)).Append('"'); $sb.ToString()
}
function Assert-V2Exe([string]$Exe, [string]$What) {
  if (-not $Exe -or -not [IO.Path]::IsPathRooted($Exe) -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { Stop-V2 "${What}: виконуваний файл не знайдено або шлях не абсолютний: $Exe" }
}
function Invoke-V2Native {
  param([Parameter(Mandatory)] [string] $Exe, [string[]] $ArgList = @(), [string] $What = $Exe, [int[]] $OkCodes = @(0),
        [string] $WorkingDirectory, [switch] $Utf8, [int] $TimeoutSec = 900)
  Assert-V2Exe $Exe $What
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = $Exe; $psi.Arguments = (@($ArgList | ForEach-Object { ConvertTo-V2Arg $_ }) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
  if ($Utf8) { $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8 }
  $p = New-Object Diagnostics.Process; $p.StartInfo = $psi
  try {
    $started = $false
    try { $started = $p.Start() } catch { Stop-V2 "${What}: запуск не вдався: $($_.Exception.Message)" }
    if (-not $started) { Stop-V2 "${What}: процес не запущено" }
    $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
    # Дельта 1: перший wait має три результати — exited / timeout / виняток. Лише exited веде далі.
    $state = 'timeout'; $waitErr = $null
    try { if (Wait-V2Handle $p ($TimeoutSec * 1000)) { $state = 'exited' } } catch { $state = 'error'; $waitErr = $_.Exception.Message }
    if ($state -ne 'exited') {
      $why = if ($state -eq 'error') { "помилка очікування ($waitErr)" } else { "тайм-аут $TimeoutSec с" }
      $killErr = $null; try { Stop-V2Handle $p } catch { $killErr = $_.Exception.Message }          # контрольована зупинка через власний handle
      $exited = $null; $wait2Err = $null
      try { $exited = [bool](Wait-V2Handle $p 15000) } catch { $wait2Err = $_.Exception.Message }
      $details = @(@(if ($killErr) { "Kill: $killErr" }) + @(if ($wait2Err) { "очікування після Kill: $wait2Err" })) -join '; '
      if ($exited -ne $true) { Stop-V2 "${What}: $why; стан процесу PID $($p.Id) НЕВІДОМИЙ або не завершено$(if ($details) { " ($details)" }) — CRITICAL" }
      Stop-V2 "${What}: $why; процес PID $($p.Id) зупинено й завершення підтверджено$(if ($details) { " ($details)" })"
    }
    $null = Wait-V2Handle $p -1
    $rc = $p.ExitCode; $out = $o.Result; $err = $e.Result
  } finally { $p.Dispose() }
  if ($OkCodes -notcontains $rc) { Stop-V2 "$What → код $rc`n$out`n$err" }
  @($out -split "`r?`n" | Where-Object { $_ -ne '' })
}
function Invoke-V2Interactive {
  param([Parameter(Mandatory)] [string] $Exe, [string[]] $ArgList = @(), [Parameter(Mandatory)] [string] $WorkingDirectory, [string] $What = $Exe)
  Assert-V2Exe $Exe $What
  $oldLocation = Get-Location
  try {
    Set-Location -LiteralPath $WorkingDirectory
    & $Exe @ArgList
    $rc = $LASTEXITCODE
  } catch { Stop-V2 "${What}: запуск не вдався: $($_.Exception.Message)" }
  finally { Set-Location -LiteralPath $oldLocation.Path }
  if ($null -eq $rc) { Stop-V2 "${What}: процес не повернув exit code" }
  if ($rc -ne 0) { Stop-V2 "$What → код $rc" }
  "PASS  $What"
}
function Invoke-V2Py {
  param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $Backend, [Parameter(Mandatory)] [string[]] $ArgList, [string] $What = 'python')
  Invoke-V2Native -Exe $Py -ArgList (@('-E', '-s', '-X', 'utf8') + $ArgList) -WorkingDirectory $Backend -Utf8 -What $What
}

# --- HTTP: статус як число, без винятків; перевірка — автоматична -------------------------------------------------
function Get-V2HttpStatus {
  param([Parameter(Mandatory)] [string] $Url, [hashtable] $Headers = @{}, [string] $Method = 'GET')
  try { [int](Invoke-WebRequest -Uri $Url -Method $Method -Headers $Headers -UseBasicParsing -TimeoutSec 10 -MaximumRedirection 0).StatusCode }
  catch {
    $resp = $_.Exception.PSObject.Properties['Response']
    if ($resp -and $resp.Value) { [int]$resp.Value.StatusCode } else { 0 }
  }
}
function Assert-V2Http {
  param([Parameter(Mandatory)] [string] $Url, [Parameter(Mandatory)] [int] $Expected, [hashtable] $Headers = @{}, [string] $Method = 'GET')
  $s = Get-V2HttpStatus -Url $Url -Headers $Headers -Method $Method
  if ($s -ne $Expected) { Stop-V2 "$Method $Url → $s, очікується $Expected" }
  "PASS  $Method $Url → $s"
}
function Wait-V2Http {
  param([Parameter(Mandatory)] [string] $Url, [int] $Expected = 200, [int] $Seconds = 30)
  foreach ($i in 1..$Seconds) { if ((Get-V2HttpStatus -Url $Url) -eq $Expected) { return "PASS  GET $Url → $Expected" }; Start-Sleep 1 }
  Stop-V2 "GET $Url не дав $Expected за $Seconds с"
}

# =====================================================================================================================
# P1: ідентичність процесу — PID + час створення (UTC ticks) + exe + командний рядок + батько + власник (GetOwner.ReturnValue=0)
# Єдиний формат запису: Pid, StartUtcTicks, Exe, CommandLine, ParentPid, ParentStartUtcTicks, Owner, Handle.
# =====================================================================================================================
function ConvertTo-V2Ticks($dt) { if ($null -eq $dt) { [int64]0 } else { ([datetime]$dt).ToUniversalTime().Ticks } }
function New-V2Identity {
  param([Parameter(Mandatory)] $Process, [int] $ExpectedParent = -1, [int64] $ParentStartUtcTicks = 0)
  $id0 = [int]$Process.Id
  $cim = Get-V2CimProcess $id0; if (-not $cim) { Stop-V2 "PID ${id0}: процесу немає в CIM — ідентичність невідома" }
  $hTicks = Get-V2HandleStartTicks $Process; $cTicks = ConvertTo-V2Ticks $cim.CreationDate
  if ([math]::Abs($hTicks - $cTicks) -gt 20000) { Stop-V2 "PID ${id0}: час створення handle ≠ CIM — PID reuse або невідома ідентичність" }
  if ($ExpectedParent -ge 0 -and [int]$cim.ParentProcessId -ne $ExpectedParent) { Stop-V2 "PID ${id0}: батько $($cim.ParentProcessId), очікується $ExpectedParent" }
  $own = Get-V2CimOwner $cim
  if ($null -eq $own -or [int]$own.ReturnValue -ne 0) { Stop-V2 "PID ${id0}: GetOwner не підтверджено (ReturnValue $(if ($own) { $own.ReturnValue } else { 'null' }))" }
  [pscustomobject]@{ Pid = $id0; StartUtcTicks = [int64]$cTicks; Exe = [string]$cim.ExecutablePath; CommandLine = [string]$cim.CommandLine
                     ParentPid = [int]$cim.ParentProcessId; ParentStartUtcTicks = [int64]$ParentStartUtcTicks; Owner = "$($own.Domain)\$($own.User)"; Handle = $Process }
}
# Дерево: корінь — handle, отриманий під час запуску; нащадки — лише ті, що створені ПІСЛЯ батька (інакше це PID reuse батька),
# кожен із власним handle та ідентичністю. Наявні записи не дублюються.
# B1: помилка відкриття handle нащадка НЕ пропускається мовчки. Якщо CIM одразу після помилки показує той самий процес
# (PID + час створення) — це нерозв'язаний нащадок (PID, батько, причина): або до списку -Unresolved, або STOP.
# Пропуск лише тоді, коли CIM доводить вихід (процесу з тим PID і часом створення більше немає).
function Add-V2TreeIdentities {
  param([Parameter(Mandatory)] [System.Collections.Generic.List[object]] $Tree, [System.Collections.Generic.List[object]] $Unresolved = $null)
  $all = @(Get-V2CimProcessList)
  $i = 0
  while ($i -lt $Tree.Count) {
    $par = $Tree[$i]
    if (-not (Test-V2HandleExited $par.Handle)) {
      foreach ($c in @($all | Where-Object { [int]$_.ParentProcessId -eq $par.Pid -and [int]$_.ProcessId -ne $par.Pid })) {
        $cid = [int]$c.ProcessId
        if (@($Tree | Where-Object { $_.Pid -eq $cid }).Count) { continue }
        if ((ConvertTo-V2Ticks $c.CreationDate) -lt $par.StartUtcTicks) { continue }      # старший за батька → не наш нащадок
        $h = $null; $openErr = $null
        try { $h = Open-V2ProcessHandle $cid } catch { $openErr = $_.Exception.Message }
        if (-not $h) {
          $ct = ConvertTo-V2Ticks $c.CreationDate
          $now = $null; $cimErr = $null; try { $now = Get-V2CimProcess $cid } catch { $cimErr = $_.Exception.Message }
          if (-not $cimErr -and (-not $now -or (ConvertTo-V2Ticks $now.CreationDate) -ne $ct)) { continue }   # CIM: вихід доведено
          $u = [pscustomobject]@{ Pid = $cid; ParentPid = [int]$par.Pid; StartUtcTicks = [int64]$ct; Exe = [string]$c.ExecutablePath
                                  Reason = "handle не відкрито: $(if ($openErr) { $openErr } else { 'порожній handle' })$(if ($cimErr) { "; CIM: $cimErr" })" }
          if ($null -eq $Unresolved) { Stop-V2 "нерозв'язаний нащадок PID $cid (батько $($par.Pid)): $($u.Reason) — вихід/ідентичність не підтверджено" }
          if (-not @($Unresolved | Where-Object { $_.Pid -eq $cid -and $_.StartUtcTicks -eq $u.StartUtcTicks }).Count) { $Unresolved.Add($u) }
          continue
        }
        $Tree.Add((New-V2Identity -Process $h -ExpectedParent $par.Pid -ParentStartUtcTicks $par.StartUtcTicks))
      }
    }
    $i++
  }
}
function New-V2Tree {
  param([Parameter(Mandatory)] $RootProcess, [System.Collections.Generic.List[object]] $Unresolved = $null)
  $t = New-Object System.Collections.Generic.List[object]
  $t.Add((New-V2Identity -Process $RootProcess))
  Add-V2TreeIdentities -Tree $t -Unresolved $Unresolved
  , $t
}
# Ідентичність без змін: handle живий; PID, час створення, exe і власник у CIM — ті самі
function Assert-V2SameIdentity {
  param([Parameter(Mandatory)] $Saved)
  if ($Saved.Handle -and (Test-V2HandleExited $Saved.Handle)) { Stop-V2 "PID $($Saved.Pid) уже завершився" }
  $cim = Get-V2CimProcess $Saved.Pid; if (-not $cim) { Stop-V2 "PID $($Saved.Pid) зник" }
  if ((ConvertTo-V2Ticks $cim.CreationDate) -ne $Saved.StartUtcTicks -or [string]$cim.ExecutablePath -ne $Saved.Exe) { Stop-V2 "PID $($Saved.Pid): ідентичність змінилась (PID reuse?)" }
  $own = Get-V2CimOwner $cim
  if ($null -eq $own -or [int]$own.ReturnValue -ne 0 -or "$($own.Domain)\$($own.User)" -ne $Saved.Owner) { Stop-V2 "PID $($Saved.Pid): власник змінився або не підтверджений" }
}
# Власник кожного слухача порту — підтверджений процес дерева з незмінною ідентичністю; чужий/невідомий → STOP
function Assert-V2ListenerInTree {
  param([Parameter(Mandatory)] [int] $Port, [Parameter(Mandatory)] [System.Collections.Generic.List[object]] $Tree, [string[]] $Addresses)
  $l = @(Get-V2Listeners @($Port))
  if (-not $l.Count) { Stop-V2 "порт $Port ніхто не слухає" }
  foreach ($x in $l) {
    $own = @($Tree | Where-Object { $_.Pid -eq [int]$x.OwningProcess })
    if (-not $own.Count) { Stop-V2 "порт $Port слухає PID $($x.OwningProcess) поза підтвердженим деревом (чужий listener)" }
    Assert-V2SameIdentity $own[0]
  }
  if ($Addresses) {
    $got = @($l | ForEach-Object LocalAddress | Sort-Object -Unique)
    if (@(Compare-Object $got ($Addresses | Sort-Object -Unique)).Count) { Stop-V2 "порт $Port слухає на $($got -join ', '), очікується $($Addresses -join ', ')" }
  }
  "PASS  порт $Port — лише підтверджене дерево ($(@($Tree | ForEach-Object { $_.Pid }) -join ','))"
}
# Очікування слухача ДО першого HTTP: дерево доповнюється (дочірній python), будь-який чужий слухач → STOP одразу
function Wait-V2Listener {
  param([Parameter(Mandatory)] [int] $Port, [Parameter(Mandatory)] [System.Collections.Generic.List[object]] $Tree, [string[]] $Addresses, [int] $Seconds = 30)
  foreach ($i in 1..($Seconds * 2)) {
    Add-V2TreeIdentities -Tree $Tree
    if (@(Get-V2Listeners @($Port)).Count) { return (Assert-V2ListenerInTree -Port $Port -Tree $Tree -Addresses $Addresses) }
    if (Test-V2HandleExited $Tree[0].Handle) { Stop-V2 "процес PID $($Tree[0].Pid) завершився до появи слухача $Port" }
    Start-Sleep -Milliseconds 500
  }
  Stop-V2 "порт $Port не з'явився за $Seconds с"
}

# =====================================================================================================================
# P2: зупинка й очищення — лише через збережені handle; помилки накопичуються; temp/DB не видаляються без доведеного виходу
# =====================================================================================================================
function Stop-V2ProcessTree {
  param([Parameter(Mandatory)] [System.Collections.Generic.List[object]] $Tree)
  $problems = New-Object System.Collections.Generic.List[string]
  try { Add-V2TreeIdentities -Tree $Tree } catch { $problems.Add("нащадок з невідомою ідентичністю: $($_.Exception.Message -replace '^STOP: ', '')") }
  for ($k = $Tree.Count - 1; $k -ge 0; $k--) {                                 # спершу нащадки
    $t = $Tree[$k]
    if (-not $t.Handle) { $problems.Add("PID $($t.Pid): немає збереженого handle — не зупиняється"); continue }
    $done = $false; try { $done = Test-V2HandleExited $t.Handle } catch { $problems.Add("PID $($t.Pid): стан handle: $($_.Exception.Message)"); continue }
    if ($done) { continue }                                                    # завершився сам — коректно
    try { Stop-V2Handle $t.Handle }
    catch { $alive = $true; try { $alive = -not (Test-V2HandleExited $t.Handle) } catch { }; if ($alive) { $problems.Add("PID $($t.Pid): Kill: $($_.Exception.Message)") } }
  }
  foreach ($t in $Tree) {
    if (-not $t.Handle) { continue }
    $ok = $false; try { $ok = Wait-V2Handle $t.Handle 15000 } catch { $problems.Add("PID $($t.Pid): очікування: $($_.Exception.Message)"); continue }
    if (-not $ok) { $problems.Add("PID $($t.Pid) не завершився") }
  }
  $problems.ToArray()
}
# Доведений вихід збережених ідентичностей. Без handle (завантажено з файлу): PID відсутній або має інший час створення →
# оригінал завершився (інший процес із тим самим PID НЕ вважається V2 і не чіпається); той самий час створення → ще працює → STOP
function Assert-V2TreeExited {
  param([Parameter(Mandatory)] [AllowEmptyCollection()] $Tree)          # List[object] або масив; без приведення типу (PS 5.1)
  foreach ($t in $Tree) {
    if ($t.Handle) { if (-not (Test-V2HandleExited $t.Handle)) { Stop-V2 "процес V2 PID $($t.Pid) ($($t.Exe)) досі працює" }; continue }
    $cim = Get-V2CimProcess $t.Pid
    if ($cim -and (ConvertTo-V2Ticks $cim.CreationDate) -eq $t.StartUtcTicks) { Stop-V2 "процес V2 PID $($t.Pid) ($($t.Exe)) досі працює" }
  }
  "PASS  збережені процеси ($($Tree.Count)) завершились"
}
function Invoke-V2Cleanup {
  param($Tree, [Parameter(Mandatory)] [string] $TempDir, [Parameter(Mandatory)] [int] $Port, [string[]] $Prior = @())
  $clean = New-Object System.Collections.Generic.List[string]
  foreach ($m in $Prior) { $clean.Add($m) }
  $exited = $true
  if ($Tree -and $Tree.Count) {
    try { foreach ($m in @(Stop-V2ProcessTree -Tree $Tree)) { $clean.Add($m); $exited = $false } } catch { $clean.Add("зупинка дерева: $($_.Exception.Message)"); $exited = $false }
    try { $null = Assert-V2TreeExited -Tree $Tree.ToArray() } catch { $clean.Add(($_.Exception.Message -replace '^STOP: ', '')); $exited = $false }
  }
  if ($exited) {
    if (Test-Path -LiteralPath $TempDir) { try { Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction Stop } catch { $clean.Add("тимчасовий каталог: $($_.Exception.Message)") } }
  } elseif (Test-Path -LiteralPath $TempDir) { $clean.Add("вихід дерева не доведено — тимчасовий каталог із БД ЗБЕРЕЖЕНО: $TempDir") }
  if ($exited -and (Test-Path -LiteralPath $TempDir)) { $clean.Add("тимчасовий каталог не видалено: $TempDir") }
  try { if (@(Get-V2Listeners @($Port)).Count) { $clean.Add("порт $Port досі слухається") } } catch { $clean.Add("перевірка порту ${Port}: $($_.Exception.Message)") }
  $clean.ToArray()
}

# =====================================================================================================================
# P4: перед відкатом SQLite — доведений вихід збережених процесів (основний доказ) + евристики + монопольний доступ до файлів БД
# =====================================================================================================================
# auditfix3: власні допоміжні процеси installer-а (утримання lease) — PID + час створення; не вважаються «процесами V2»
# (їхній командний рядок містить шлях v2_job_launcher.py під коренем V2 → без цього евристика давала б хибний STOP під час відкату)
$V2OwnHelpers = @{}
function Get-V2SuspectProcesses {
  $me = @($PID)
  @(Get-V2CimProcessList | Where-Object {
      $me -notcontains [int]$_.ProcessId -and -not ($V2OwnHelpers.ContainsKey([int]$_.ProcessId) -and [math]::Abs((ConvertTo-V2Ticks $_.CreationDate) - $V2OwnHelpers[[int]$_.ProcessId]) -le 20000) -and (
      ($_.ExecutablePath -and $_.ExecutablePath.StartsWith("$V2Root\", [StringComparison]::OrdinalIgnoreCase)) -or
      ($_.CommandLine -and ($_.CommandLine.IndexOf($V2Root, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $_.CommandLine -match '--port\s+(8100|8199)\b')) ) })
}
function Assert-V2DbFilesFree {
  param([Parameter(Mandatory)] [string] $DataDir)
  $files = @(Get-ChildItem -LiteralPath $DataDir -File -Force | Where-Object { $_.Name -match '\.db(-journal|-wal|-shm)?$' })
  foreach ($f in $files) {
    $fs = $null
    try { $fs = [IO.File]::Open($f.FullName, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { Stop-V2 "файл БД відкритий іншим процесом: $($f.Name)" }
    finally { if ($fs) { $fs.Dispose() } }
  }
  "PASS  файли БД ($($files.Count)) не відкриті іншими процесами"
}
function Assert-V2NoProcesses {
  param([string] $DataDir, [AllowEmptyCollection()] $Known = @())               # масив або List[object] — без приведення типу (PS 5.1)
  if ($null -ne $Known -and $Known.Count) { $null = Assert-V2TreeExited -Tree $Known }                  # основний доказ — збережені ідентичності
  $p = @(Get-V2SuspectProcesses)
  if ($p.Count) { Stop-V2 "працюють процеси V2: $(($p | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join '; ')" }
  $l = @(Get-V2Listeners $V2Ports)
  if ($l.Count) { Stop-V2 "порти V2 слухаються: $(($l | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort) PID $($_.OwningProcess)" }) -join '; ')" }
  if ($DataDir) { $null = Assert-V2DbFilesFree -DataDir $DataDir }
  "PASS  збережені процеси V2 ($(if ($null -ne $Known) { $Known.Count } else { 0 })) завершились; евристик 0; порти вільні$(if ($DataDir) { '; файли БД вільні' })"
}
# Ідентичності служби зберігаються у файл (лише адміністраторам) — для відкату в новій сесії PowerShell
function Save-V2Identities {
  param([Parameter(Mandatory)] [string] $Name, [Parameter(Mandatory)] $Tree, [string] $Dir = "$V2Root\pkg\identities")
  $V2Identity[$Name] = $Tree
  if (-not (Test-Path -LiteralPath $Dir)) { $null = New-Item -ItemType Directory -Path $Dir }
  $rows = @($Tree | ForEach-Object { [ordered]@{ Pid = $_.Pid; StartUtcTicks = $_.StartUtcTicks; Exe = $_.Exe; CommandLine = $_.CommandLine; ParentPid = $_.ParentPid; ParentStartUtcTicks = $_.ParentStartUtcTicks; Owner = $_.Owner } })
  $path = Join-Path $Dir "$Name.json"
  [IO.File]::WriteAllText($path, (ConvertTo-Json -InputObject $rows -Depth 3), (New-Object Text.UTF8Encoding $false))
  $path
}
function Import-V2Identities {
  param([Parameter(Mandatory)] [string] $Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-V2 "немає файлу ідентичностей $Path — вихід процесів довести неможливо" }
  @((Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) | ForEach-Object {
    [pscustomobject]@{ Pid = [int]$_.Pid; StartUtcTicks = [int64]$_.StartUtcTicks; Exe = [string]$_.Exe; CommandLine = [string]$_.CommandLine; ParentPid = [int]$_.ParentPid; ParentStartUtcTicks = [int64]$_.ParentStartUtcTicks; Owner = [string]$_.Owner; Handle = $null } })
}
# Готовність до відновлення БД: усе нижче — ДО будь-якого перейменування чи копіювання
function Assert-V2RestoreReady {
  param([Parameter(Mandatory)] [string] $DataDir, [Parameter(Mandatory)] [AllowEmptyCollection()] $Known, [Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $DbTool,
        [Parameter(Mandatory)] [string] $Backup, [Parameter(Mandatory)] [string] $BackupSha256, [Parameter(Mandatory)] [int] $ExpectVersion)
  if ($null -eq $Known -or -not $Known.Count) { Stop-V2 'немає збережених ідентичностей процесів служби — вихід не доведено, відновлення заборонено' }
  $out = New-Object System.Collections.Generic.List[string]
  $out.Add((Assert-V2NoProcesses -DataDir $DataDir -Known $Known))
  $out.Add((Assert-V2FileHash -Path $Backup -Sha256 $BackupSha256 -Label 'резервна копія'))
  $v = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('verify', $Backup, '--expect-version', "$ExpectVersion")
  if ($v -notlike 'VERIFY OK*') { Stop-V2 "резервна копія не пройшла verify: $v" }
  $out.Add("PASS  резервна копія: $v")
  $out.Add('PASS  відновлення дозволено: процеси завершились, файли вільні, копія перевірена')
  $out.ToArray()
}

# =====================================================================================================================
# Дельта 3: fail-fast відновлення SQLite (DB / -journal / -wal / -shm). Дозвіл — лише після доведеного завершення ПОВНОГО дерева
# процесів backend (Stop-V2Service → $V2StopProof, або збережені ідентичності + пізні нащадки в новій сесії).
# Маркери в data\: RESTORE-IN-PROGRESS-<ts>.txt (під час), RESTORE-FAILED-<ts>.txt (провал), RESTORE-OK-<ts>.txt (успіх).
# Будь-який IN-PROGRESS або FAILED → старт backend заборонено (Assert-V2NoRestoreBlock у PreCheck), зняття — лише рішенням №5.
# =====================================================================================================================
function Assert-V2NoRestoreBlock {
  param([Parameter(Mandatory)] [string] $DataDir)
  if (-not (Test-Path -LiteralPath $DataDir)) { return 'PASS  data\ відсутній — блоків відновлення немає' }
  $m = @(Get-ChildItem -LiteralPath $DataDir -File -Force -Filter 'RESTORE-*.txt' | Where-Object { $_.Name -match '^RESTORE-(IN-PROGRESS|FAILED)-' })
  if ($m.Count) { Stop-V2 "старт backend заборонено: відновлення БД не завершено або невдале ($(($m | ForEach-Object Name) -join ', ')) — потрібне рішення №5" }
  'PASS  блоків відновлення немає'
}
# B3: доказ зупинки обов'язковий — успішний Stop-V2Service backend у цій сесії ($V2StopProof, без нерозв'язаних нащадків),
# служба зараз Stopped (або не встановлена); дерево для повторної перевірки — з доказу або (служба вже була зупинена) з файлу.
function Assert-V2RestorePermitted {
  param([Parameter(Mandatory)] [AllowEmptyCollection()] $Known)
  $n = $V2BackendName
  if (-not $V2StopProof.ContainsKey($n) -or $null -eq $V2StopProof[$n]) { Stop-V2 'відновлення заборонено: немає доказу зупинки backend (успішний Stop-V2Service у цій сесії)' }
  $pr = $V2StopProof[$n]
  if ($pr.Name -ne $n -or -not $pr.VerifiedUtc -or $pr.Unresolved -ne 0) { Stop-V2 'відновлення заборонено: доказ зупинки backend невалідний' }
  if ($pr.Completeness -ne 'job' -or $pr.JobVerified -ne $true -or $pr.JobActive -ne 0 -or $pr.OwnerScanAlive -ne 0) {
    Stop-V2 "відновлення заборонено: доказ зупинки backend без моделі повноти (Job Object: ActiveProcesses 0, процесів акаунта 0) — P4 BLOCKED (повнота: $($pr.Completeness))"
  }
  $svc = Get-V2Service $n; if ($svc -and ($svc.State -ne 'Stopped' -or $svc.ProcessId)) { Stop-V2 "відновлення заборонено: ${n} зараз $($svc.State) (PID $($svc.ProcessId))" }
  if ($pr.Tree -and $pr.Tree.Count) { $tree = $pr.Tree; $src = 'доказ Stop-V2Service' }
  elseif ($null -ne $Known -and $Known.Count) { $tree = $Known; $src = 'доказ Stop-V2Service + збережені ідентичності' }
  else { Stop-V2 'відновлення заборонено: немає дерева процесів backend для перевірки (доказ без дерева і немає файлу ідентичностей)' }
  $null = Assert-V2TreeExited -Tree $tree
  $late = @(Get-V2LateDescendants -Tree $tree); if ($late.Count) { Stop-V2 "відновлення заборонено: живі пізні нащадки $(($late | ForEach-Object { $_.ProcessId }) -join ', ')" }
  "PASS  повне дерево backend завершилось ($src), пізніх нащадків 0"
}
# B3: набір копій перевіряється ДО будь-якої мутації: рівно дві БД (integrity_v2.db v3, v2_auth.db v1), без дублікатів БД
# і шляхів копій, копії — існуючі файли поза data\, SHA256 — 64 hex.
$V2DbSet = [ordered]@{ 'integrity_v2.db' = 3; 'v2_auth.db' = 1 }
function Assert-V2RestoreItems {
  param([Parameter(Mandatory)] [string] $DataDir, [Parameter(Mandatory)] [AllowEmptyCollection()] [object[]] $Items)
  if ($Items.Count -ne $V2DbSet.Count) { Stop-V2 "набір відновлення: потрібно рівно $($V2DbSet.Count) БД ($($V2DbSet.Keys -join ', ')), отримано $($Items.Count)" }
  $dd = [IO.Path]::GetFullPath($DataDir).TrimEnd('\') + '\'
  $dbs = @{}; $bks = @{}
  foreach ($it in $Items) {
    if ($null -eq $it -or -not ($it -is [System.Collections.IDictionary])) { Stop-V2 'набір відновлення: елемент не є @{ Db; Backup; Sha256; Version }' }
    $db = [string]$it['Db']
    if (-not $V2DbSet.Contains($db)) { Stop-V2 "набір відновлення: невідома БД '$db' (дозволено: $($V2DbSet.Keys -join ', '))" }
    if ($dbs.ContainsKey($db.ToLowerInvariant())) { Stop-V2 "набір відновлення: БД $db указано двічі" }
    $dbs[$db.ToLowerInvariant()] = $true
    $ver = $it['Version']; if (-not ($ver -is [int]) -or $ver -ne $V2DbSet[$db]) { Stop-V2 "набір відновлення: ${db} — user_version $ver, потрібно $($V2DbSet[$db])" }
    if ([string]$it['Sha256'] -notmatch '^[0-9a-fA-F]{64}$') { Stop-V2 "набір відновлення: ${db} — SHA256 не 64 hex" }
    $bk = [string]$it['Backup']; if (-not $bk -or -not [IO.Path]::IsPathRooted($bk)) { Stop-V2 "набір відновлення: ${db} — шлях копії не абсолютний" }
    $bf = [IO.Path]::GetFullPath($bk)
    if ($bks.ContainsKey($bf.ToLowerInvariant())) { Stop-V2 "набір відновлення: копію $bf указано для двох БД" }
    $bks[$bf.ToLowerInvariant()] = $true
    if ($bf.StartsWith($dd, [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "набір відновлення: копія $bf лежить у data\ — заборонено" }
    if (-not (Test-Path -LiteralPath $bf -PathType Leaf)) { Stop-V2 "набір відновлення: копії $bf немає" }
  }
  "PASS  набір відновлення: $($V2DbSet.Count) БД, версії й шляхи коректні, дублікатів немає"
}
# auditfix3 (P0): супутні файли SQLite відновленої БД перед RESTORE-OK. Режим журналу — із заголовка (байти 18/19: 1/1 rollback, 2/2 WAL).
# -journal і -wal: відсутні або 0 байт (непорожній = hot journal / WAL-кадри, які SQLite застосує під час наступного відкриття);
# -shm: у rollback-режимі заборонений; у WAL — допустимий лише за відсутнього/порожнього -wal (індекс перебудовується з -wal).
# Каталог замість файлу, невідомий режим, помилка читання → STOP (у відкаті → RESTORE-FAILED).
function Assert-V2SqliteSidecars {
  param([Parameter(Mandatory)] [string] $DbPath)
  $name = Split-Path $DbPath -Leaf
  $hdr = New-Object byte[] 100; $fs = $null; $got = 0
  try { $fs = [IO.File]::Open($DbPath, 'Open', 'Read', 'Read'); $got = $fs.Read($hdr, 0, 100) } catch { Stop-V2 "W5 sidecars: $name — заголовок не прочитано: $($_.Exception.Message)" } finally { if ($fs) { $fs.Dispose() } }
  if ($got -lt 100 -or [Text.Encoding]::ASCII.GetString($hdr, 0, 16) -ne "SQLite format 3`0") { Stop-V2 "W5 sidecars: $name — не SQLite-заголовок" }
  $mode = if ($hdr[18] -eq 1 -and $hdr[19] -eq 1) { 'rollback' } elseif ($hdr[18] -eq 2 -and $hdr[19] -eq 2) { 'wal' } else { $null }
  if (-not $mode) { Stop-V2 "W5 sidecars: $name — невизначений режим журналу (write=$($hdr[18]), read=$($hdr[19]))" }
  $st = @{}
  foreach ($sfx in '-journal', '-wal', '-shm') {
    $f = "$DbPath$sfx"
    if (-not (Test-Path -LiteralPath $f)) { $st[$sfx] = -1; continue }
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { Stop-V2 "W5 sidecars: $name$sfx — не звичайний файл (невизначений стан)" }
    $st[$sfx] = [int64](Get-Item -LiteralPath $f -Force).Length
  }
  if ($st['-journal'] -gt 0) { Stop-V2 "W5 sidecars: $name-journal непорожній ($($st['-journal']) B) — hot journal" }
  if ($st['-wal'] -gt 0) { Stop-V2 "W5 sidecars: $name-wal непорожній ($($st['-wal']) B)" }
  if ($mode -eq 'rollback' -and $st['-shm'] -ge 0) { Stop-V2 "W5 sidecars: $name-shm у rollback-режимі — невизначений стан" }
  $fmt = { param($v) if ($v -lt 0) { 'відсутній' } else { "$v B" } }
  "PASS  W5 sidecars ${name}: режим $mode; -journal $(& $fmt $st['-journal']); -wal $(& $fmt $st['-wal']); -shm $(& $fmt $st['-shm'])"
}
# auditfix2 (B-03): відкат SQLite із виключенням конкурентних writer — SQLITE_WRITER_EXCLUSION_DESIGN.md (W1–W5).
# Обгортка гарантує на ВСІХ шляхах: holder (lease) звільнено, доказ зупинки backend видалено (одноразовий);
# start type повертається, якщо мутації не було; після мутації з помилкою лишається Disabled (разом із RESTORE-FAILED).
function Invoke-V2DbRestore {
  param([Parameter(Mandatory)] [string] $DataDir, [Parameter(Mandatory)] [AllowEmptyCollection()] $Known, [Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $DbTool,
        [Parameter(Mandatory)] [AllowEmptyCollection()] [object[]] $Items)   # рівно: @{ Db='integrity_v2.db'; …; Version=3 }, @{ Db='v2_auth.db'; …; Version=1 }
  $ctx = @{ StartTypeChanged = $false; OriginalStartMode = $null; MutationStarted = $false; Done = $false }
  $err = $null; $res = $null
  try { $res = Invoke-V2DbRestoreCore -DataDir $DataDir -Known $Known -Py $Py -DbTool $DbTool -Items $Items -Ctx $ctx }
  catch { $err = $_ }
  finally {
    $cleanup = New-Object System.Collections.Generic.List[string]
    $n = $V2BackendName
    $pf = $V2StopProof[$n]; $V2StopProof.Remove($n)                                         # proof одноразовий — інвалідується завжди
    if ($pf -and $pf.PSObject.Properties['Lease'] -and $pf.Lease) { try { Stop-V2JobHolder -Holder $pf.Lease } catch { $cleanup.Add("lease не звільнено: $($_.Exception.Message -replace '^STOP: ', '')") } }
    if ($ctx.StartTypeChanged -and -not $ctx.MutationStarted) {                             # мутації не було → повернути start type
      try { Set-V2ServiceStartMode -Name $n -Mode $ctx.OriginalStartMode } catch { $cleanup.Add("start type $n не повернуто: $($_.Exception.Message -replace '^STOP: ', '')") }
    }
    $ctx.Done = $true
  }
  if ($err -or $cleanup.Count) {
    $msg = if ($err) { $err.Exception.Message -replace '^STOP: ', '' } else { 'відновлення завершено' }
    if ($cleanup.Count) { $msg += "; CLEANUP: $($cleanup -join '; ')" }
    Stop-V2 $msg
  }
  $res
}
function Invoke-V2DbRestoreCore {
  param([string] $DataDir, [AllowEmptyCollection()] $Known, [string] $Py, [string] $DbTool, [AllowEmptyCollection()] [object[]] $Items, [hashtable] $Ctx)
  $n = $V2BackendName
  $out = New-Object System.Collections.Generic.List[string]
  $out.Add((Assert-V2RestoreItems -DataDir $DataDir -Items $Items))                           # B3: ДО будь-якої мутації
  $null = Assert-V2NoRestoreBlock -DataDir $DataDir                                           # попередній незавершений відкат → STOP
  $out.Add((Assert-V2RestorePermitted -Known $Known))
  $kn = $Known                                                                               # присвоєння, а не if-вираз: if-вираз розгортає 1-елементний масив у скаляр
  if ($V2StopProof[$n].Tree -and $V2StopProof[$n].Tree.Count) { $kn = $V2StopProof[$n].Tree }
  foreach ($it in $Items) {                                                                   # ПОВНА перевірка всіх копій ДО змін
    if ($it.Db -notmatch '^[A-Za-z0-9_]+\.db$') { Stop-V2 "некоректне ім'я БД: $($it.Db)" }
    foreach ($l in @(Assert-V2RestoreReady -DataDir $DataDir -Known $kn -Py $Py -DbTool $DbTool -Backup $it.Backup -BackupSha256 $it.Sha256 -ExpectVersion $it.Version)) { $out.Add($l) }
    if ($it.Db -eq 'v2_auth.db') {                                                            # етап 1: строга схема auth — ДО мутації
      $a = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('auth-schema', $it.Backup)
      if ($a -notlike 'AUTH SCHEMA OK*') { Stop-V2 "копія v2_auth.db не пройшла строгу перевірку схеми: $a" }
      $out.Add("PASS  копія v2_auth.db: $a")
    }
  }
  # Lease (W4): той самий job, що й у конфігурації; процес утримання живий
  $proof = $V2StopProof[$n]
  if (-not $proof.PSObject.Properties['Lease'] -or -not $proof.Lease -or -not $proof.JobName -or $proof.JobName -ne $V2Services[$n].Job) { Stop-V2 'відновлення заборонено: немає чинної proof lease Job Object' }
  if ($proof.Lease.PSObject.Properties['HasExited'] -and $proof.Lease.HasExited) { Stop-V2 'відновлення заборонено: proof lease завершилась' }
  # W1: нових процесів service SID не буде — SCM не запускає службу з start type Disabled (ERROR_SERVICE_DISABLED). ДО фінального scan.
  $svc = Get-V2Service $n
  if ($svc) {
    if ($svc.State -ne 'Stopped' -or $svc.ProcessId) { Stop-V2 "W1: $n не зупинена ($($svc.State), PID $($svc.ProcessId))" }
    if ($svc.StartMode -ne 'Manual') { Stop-V2 "W1: start type $n = $($svc.StartMode), очікується Manual" }
    $Ctx.OriginalStartMode = 'Manual'
    $Ctx.StartTypeChanged = $true                                                            # до виклику: часткова зміна теж повертається
    Set-V2ServiceStartMode -Name $n -Mode Disabled
    $out.Add("PASS  W1: $n — start type Disabled, Stopped (нові процеси service SID неможливі без TCB)")
  } else { $out.Add("INFO  W1: служби $n немає — процесів service SID без SCM не буде") }
  # W2: фінальний job proof + scan service SID ПІСЛЯ W1 — нуль тримається всю операцію
  $fresh = Get-V2JobReport -JobName $proof.JobName -OwnerSid (Get-V2ServiceSid $n) -Scan
  if ($fresh.verdict -ne 'PASS' -or -not $fresh.found -or -not $fresh.sd_ok -or -not $fresh.limits_ok -or [int]$fresh.active -ne 0 -or @($fresh.pids).Count -ne 0 -or @($fresh.scan.alive).Count -ne 0 -or @($fresh.scan.unknown).Count -ne 0) {
    Stop-V2 "відновлення заборонено: свіжий service-SID scan / Job proof не пройдено: $(@($fresh.problems) -join '; ')"
  }
  $null = Assert-V2DbFilesFree -DataDir $DataDir                                              # W3: жодного відкритого handle перед мутацією
  $out.Add('PASS  W2/W3: job порожній, процесів service SID 0, файли БД вільні')
  $ts = Get-Date -Format yyyyMMdd-HHmmss
  $prog = Join-Path $DataDir "RESTORE-IN-PROGRESS-$ts.txt"
  $Ctx.MutationStarted = $true                                                               # з цього моменту start type лишається Disabled до RESTORE-OK
  [IO.File]::WriteAllText($prog, "restore started $ts`n", (New-Object Text.UTF8Encoding $false))
  $done = New-Object System.Collections.Generic.List[string]
  $hash = @{}
  try {
    foreach ($it in $Items) {
      foreach ($suffix in '', '-journal', '-wal', '-shm') {                                 # БД і всі супутні файли → *.broken-<ts>; нічого не видаляється
        $f = Join-Path $DataDir ($it.Db + $suffix)
        if (Test-Path -LiteralPath $f) { Rename-Item -LiteralPath $f -NewName "$($it.Db)$suffix.broken-$ts" -ErrorAction Stop; $done.Add("$($it.Db)$suffix → .broken-$ts") }
      }
      $dst = Join-Path $DataDir $it.Db
      $out.Add((Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', $it.Backup, $dst, '--expect-version', "$($it.Version)")))
      $hash[$dst] = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash                  # W5: еталон одразу після копіювання
      $done.Add("$($it.Db) ← $($it.Backup)")
      $v = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('verify', $dst, '--expect-version', "$($it.Version)")
      if ($v -notlike 'VERIFY OK*') { Stop-V2 "відновлена $($it.Db) не пройшла verify: $v" }
      if ($it.Db -eq 'v2_auth.db') {                                                          # етап 1: строга схема ВІДНОВЛЕНОЇ auth-БД
        $a = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('auth-schema', $dst)
        if ($a -notlike 'AUTH SCHEMA OK*') { Stop-V2 "відновлена v2_auth.db не пройшла строгу перевірку схеми: $a" }
        $out.Add("PASS  відновлена v2_auth.db: $a")
      }
    }
    # B3: перевірка схеми САМЕ відновлених файлів — INTEGRITY_DB/V2_AUTH_DB вказують на data\ (без них backend перевіряв би БД за замовчуванням)
    $sc = @(Use-V2Env -Vars @{ INTEGRITY_DB = (Join-Path $DataDir 'integrity_v2.db'); V2_AUTH_DB = (Join-Path $DataDir 'v2_auth.db') } -Body { Invoke-V2Py -Py $Py -Backend "$V2Root\app\integrity-v2-dde86e6\backend" -ArgList @('-c', 'from app.migrations import check_schema; from app.database import engine; check_schema(engine); from app.v2_auth import check_auth_schema; check_auth_schema(); print(''SCHEMA OK'')') -What 'schema після відновлення' })
    if (-not $sc.Count -or $sc[-1] -ne 'SCHEMA OK') { Stop-V2 "перевірка схеми після відновлення: $(if ($sc.Count) { $sc[-1] } else { 'немає результату' })" }
    $out.Add($sc[-1])
    # W5: виявлення втручання за час операції — ДО RESTORE-OK; будь-яка невідповідність → FAILED
    if ($svc) {
      $now = Get-V2Service $n
      if (-not $now -or $now.StartMode -ne 'Disabled' -or $now.State -ne 'Stopped' -or $now.ProcessId) { Stop-V2 "W5: стан служби змінився під час відкату (StartMode $(if ($now) { $now.StartMode }), State $(if ($now) { $now.State }))" }
    }
    $end = Get-V2JobReport -JobName $proof.JobName -OwnerSid (Get-V2ServiceSid $n) -Scan
    if ($end.verdict -ne 'PASS' -or [int]$end.active -ne 0 -or @($end.pids).Count -ne 0 -or @($end.scan.alive).Count -ne 0 -or @($end.scan.unknown).Count -ne 0) { Stop-V2 "W5: процес service SID / job з'явився під час відкату: $(@($end.problems) -join '; ')" }
    $null = Assert-V2DbFilesFree -DataDir $DataDir
    foreach ($k in $hash.Keys) { if ((Get-FileHash -LiteralPath $k -Algorithm SHA256).Hash -ne $hash[$k]) { Stop-V2 "W5: $(Split-Path $k -Leaf) змінено під час відкату (SHA256 ≠ зафіксованому після копіювання)" } }
    foreach ($k in $hash.Keys) { $out.Add((Assert-V2SqliteSidecars -DbPath $k)) }                 # auditfix3: -journal / -wal / -shm
    $out.Add("PASS  W5: $(if ($svc) { 'служба Disabled/Stopped' } else { 'служби немає (W1 не застосовано)' }), процесів service SID 0, файли вільні, SHA256 відновлених БД незмінні, sidecar-и коректні")
  } catch {
    $why = $_.Exception.Message -replace '^STOP: ', ''
    $fail = Join-Path $DataDir "RESTORE-FAILED-$ts.txt"
    $note = "restore FAILED $ts`nпричина: $why`nвиконано: $($done -join '; ')`n.broken-* збережено; start type backend лишається Disabled; backend НЕ стартувати без рішення №5`n"
    try { Rename-Item -LiteralPath $prog -NewName (Split-Path $fail -Leaf) -ErrorAction Stop; [IO.File]::AppendAllText($fail, $note) } catch { }
    Stop-V2 "ВІДНОВЛЕННЯ НЕВДАЛЕ (частковий стан): $why; виконано: $($done -join '; '); маркер RESTORE-FAILED/IN-PROGRESS блокує старт backend; start type лишається Disabled"
  }
  Rename-Item -LiteralPath $prog -NewName "RESTORE-OK-$ts.txt" -ErrorAction Stop
  if ($svc) {                                                                                 # успіх: повернути Manual (інакше старт неможливий — fail-closed)
    try { Set-V2ServiceStartMode -Name $n -Mode Manual } catch { Stop-V2 "RESTORE-OK-$ts, але start type $n не повернуто в Manual: $($_.Exception.Message -replace '^STOP: ', '') — старт лише за рішенням №5" }
    $out.Add("PASS  start type $n повернуто: Manual")
  }
  $out.Add("PASS  відновлення завершено: $($done -join '; '); .broken-$ts збережено; маркер RESTORE-OK-$ts")
  $out.ToArray()
}

# =====================================================================================================================
# P5: ACL і шляхи — канонічні шляхи, reparse усіх компонентів, небезпечні ACE (зокрема GW/WriteEA/WriteAttributes),
# права для майбутніх файлів/каталогів (InheritOnly), рекурсивне зчитування, ролі code / data
# =====================================================================================================================
function Resolve-V2Path([string]$Path) {
  if (-not $Path -or -not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\')) { Stop-V2 "шлях не локальний абсолютний: $Path" }
  if ($Path -match '(^|[\\/])\.{1,2}([\\/]|$)') { Stop-V2 "шлях містить . або ..: $Path" }
  if ($Path -match '~\d') { Stop-V2 "коротке ім'я 8.3 у шляху: $Path" }
  $full = [IO.Path]::GetFullPath($Path)
  if ($full.Length -gt 3) { $full = $full.TrimEnd('\') }
  $full
}
function Assert-V2NoReparseChain([string]$Full) {
  $cur = $Full
  while ($cur) {
    if (Test-Path -LiteralPath $cur) { if ((Get-Item -LiteralPath $cur -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-V2 "reparse point у шляху: $cur" } }
    $p = [IO.Path]::GetDirectoryName($cur); if (-not $p -or $p -eq $cur) { break }; $cur = $p
  }
}
function Assert-V2InRoot([string]$Path) {
  $full = Resolve-V2Path $Path
  $root = Resolve-V2Path $V2Root
  if (-not ($full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase))) { Stop-V2 "шлях поза ${root}: $full" }
  Assert-V2NoReparseChain $full
  $full
}
$V2MaskAncestor = [int64](0x10 -bor 0x40 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000 -bor 0x40000000)   # WriteEA, DeleteChild, WriteAttributes, DELETE, WRITE_DAC, WRITE_OWNER, GA, GW
$V2MaskWrite = [int64](0x2 -bor 0x4 -bor 0x10 -bor 0x40 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000 -bor 0x40000000)
function Get-V2AclRisk {
  param([Parameter(Mandatory)] [System.Security.AccessControl.FileSystemSecurity] $Acl, [Parameter(Mandatory)] [ValidateSet('ancestor', 'v2root')] [string] $Kind,
        [switch] $IncludeInheritable, [string[]] $TrustedSids = @())
  $allowed = @($SidAdmins, $SidSystem, $SidTrustedInstaller) + $TrustedSids
  $risk = New-Object System.Collections.Generic.List[string]
  $owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
  if ($null -eq $owner -or $allowed -notcontains $owner.Value) { $risk.Add("власник $(if ($owner) { $owner.Value } else { 'невідомий' })") }
  $mask = if ($Kind -eq 'v2root') { $V2MaskWrite } else { $V2MaskAncestor }
  foreach ($ace in $Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
    if ([string]$ace.AccessControlType -ne 'Allow') { continue }
    $sid = $ace.IdentityReference.Value
    if ($allowed -contains $sid -or ($sid -eq 'S-1-3-0' -and $Kind -eq 'ancestor')) { continue }
    $io = [bool]($ace.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)
    if ($io -and -not $IncludeInheritable -and $Kind -eq 'ancestor') { continue }      # InheritOnly не діє на сам предок; для нового дочірнього — -IncludeInheritable
    $m = (([int64][int]$ace.FileSystemRights) -band [int64]4294967295) -band $mask
    if ($m) { $risk.Add(('{0} 0x{1:X} {2}{3}' -f $sid, $m, $ace.InheritanceFlags, $(if ($io) { ' InheritOnly' } else { '' }))) }
  }
  if ($Kind -eq 'v2root' -and -not $Acl.AreAccessRulesProtected) { $risk.Add('успадкування не вимкнено') }
  $risk.ToArray()
}
# Карта прав за SID для області: Object — сам об'єкт; ChildContainer / ChildObject — що отримають майбутні каталоги / файли
function Get-V2AccessMap {
  param([Parameter(Mandatory)] [System.Security.AccessControl.FileSystemSecurity] $Acl, [ValidateSet('Object', 'ChildContainer', 'ChildObject')] [string] $Scope = 'Object')
  $map = @{}
  foreach ($ace in $Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
    $io = [bool]($ace.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)
    $inh = $ace.InheritanceFlags
    $applies = switch ($Scope) {
      'Object' { -not $io }
      'ChildContainer' { [bool]($inh -band [Security.AccessControl.InheritanceFlags]::ContainerInherit) }
      'ChildObject' { [bool]($inh -band [Security.AccessControl.InheritanceFlags]::ObjectInherit) }
    }
    if (-not $applies) { continue }
    $sid = $ace.IdentityReference.Value
    if ([string]$ace.AccessControlType -ne 'Allow') { $map["DENY:$sid"] = 1; continue }
    $m = ([int64][int]$ace.FileSystemRights) -band [int64]4294967295
    if ($m -band 0x10000000) { $m = $m -bor 0x1F01FF }                                 # GENERIC_ALL ≡ FullControl
    $map[$sid] = $(if ($map.ContainsKey($sid)) { $map[$sid] } else { 0 }) -bor $m
  }
  $map
}
$V2Rights = @{ F = 0x1F01FF; M = 0x1301BF; RX = 0x1200A9; R = 0x120089 }
function Assert-V2AclExact {
  param([Parameter(Mandatory)] [System.Security.AccessControl.FileSystemSecurity] $Acl, [string] $ServiceSid, [string] $ServiceRights, [string] $Label = 'об''єкт',
        [switch] $IsContainer, [string[]] $AllowedOwners = @($SidAdmins))
  $exp = @{ $SidAdmins = $V2Rights.F; $SidSystem = $V2Rights.F }
  if ($ServiceSid) { if (-not $V2Rights.ContainsKey($ServiceRights)) { Stop-V2 "невідомий рівень прав $ServiceRights" }; $exp[$ServiceSid] = $V2Rights[$ServiceRights] }
  $scopes = @('Object'); if ($IsContainer) { $scopes += 'ChildContainer', 'ChildObject' }
  $diff = New-Object System.Collections.Generic.List[string]
  foreach ($sc in $scopes) {
    $act = Get-V2AccessMap -Acl $Acl -Scope $sc
    foreach ($k in $act.Keys) { if (-not $exp.ContainsKey($k)) { $diff.Add("${sc}: зайвий $k") } elseif (($act[$k] -band 0x1F01FF) -ne $exp[$k]) { $diff.Add(('{0}: {1} 0x{2:X} ≠ 0x{3:X}' -f $sc, $k, $act[$k], $exp[$k])) } }
    foreach ($k in $exp.Keys) { if (-not $act.ContainsKey($k)) { $diff.Add("${sc}: немає $k") } }
  }
  $owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
  if ($null -eq $owner -or $AllowedOwners -notcontains $owner.Value) { $diff.Add("власник $(if ($owner) { $owner.Value } else { '?' })") }
  if ($diff.Count) { Stop-V2 "${Label}: ACL ≠ матриці: $($diff -join '; ')" }
  "PASS  ${Label}: ACL = матриця"
}
# Рекурсивне зчитування: кожен нащадок перевіряється точно. Роль code — власник лише Administrators;
# роль data (data/logs/сховище Caddy) — власником може бути й сама служба (створені нею файли)
function Assert-V2AclTree {
  param([Parameter(Mandatory)] [string] $Path, [string] $ServiceSid, [string] $ServiceRights, [ValidateSet('code', 'data', 'admin')] [string] $Role = 'code')
  $owners = @($SidAdmins); if ($Role -eq 'data' -and $ServiceSid) { $owners += $ServiceSid }
  $full = Assert-V2InRoot $Path
  $items = @(Get-Item -LiteralPath $full -Force) + @(Get-ChildItem -LiteralPath $full -Recurse -Force)
  foreach ($it in $items) {
    if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-V2 "reparse point у дереві V2: $($it.FullName)" }
    $null = Assert-V2AclExact -Acl (Get-V2Acl $it.FullName) -ServiceSid $ServiceSid -ServiceRights $ServiceRights -Label $it.FullName -IsContainer:$it.PSIsContainer -AllowedOwners $owners
  }
  "PASS  $full — $($items.Count) об'єктів = матриця ($Role)"
}
# Повна матриця дерева V2: склад кореня, адміністративні каталоги, код (RX/R) і дані (M) — кожен нащадок
function Assert-V2AclMatrix {
  $b = Get-V2ServiceSid 'integrity-v2-backend'; $c = $null
  if (Get-V2Service 'integrity-v2-caddy') { $c = Get-V2ServiceSid 'integrity-v2-caddy' }
  $expectTop = @('app', 'backups', 'caddy', 'data', 'logs', 'pkg', 'services', 'venv')
  $top = @(Get-ChildItem -LiteralPath $V2Root -Force | ForEach-Object Name | Sort-Object)
  if (@(Compare-Object $top $expectTop).Count) { Stop-V2 "склад $V2Root ≠ очікуваному: $($top -join ', ')" }
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($r in @($V2Root, "$V2Root\app", "$V2Root\services", "$V2Root\logs", "$V2Root\caddy")) {
    $out.Add((Assert-V2AclExact -Acl (Get-V2Acl $r) -Label $r -IsContainer))
  }
  foreach ($p in "$V2Root\pkg", "$V2Root\backups") { $out.Add((Assert-V2AclTree -Path $p -Role admin)) }
  $out.Add((Assert-V2AclTree -Path "$V2Root\app\integrity-v2-dde86e6" -ServiceSid $b -ServiceRights RX -Role code))
  $out.Add((Assert-V2AclTree -Path "$V2Root\venv" -ServiceSid $b -ServiceRights RX -Role code))
  $out.Add((Assert-V2AclTree -Path "$V2Root\services\backend" -ServiceSid $b -ServiceRights RX -Role code))   # wrapper + XML із секретами: лише читання
  $out.Add((Assert-V2AclTree -Path "$V2Root\data" -ServiceSid $b -ServiceRights M -Role data))
  $out.Add((Assert-V2AclTree -Path "$V2Root\logs\backend" -ServiceSid $b -ServiceRights M -Role data))
  if ($c) {
    $out.Add((Assert-V2AclTree -Path "$V2Root\app\frontend\dist" -ServiceSid $c -ServiceRights RX -Role code))
    $out.Add((Assert-V2AclTree -Path "$V2Root\caddy\bin" -ServiceSid $c -ServiceRights RX -Role code))
    $out.Add((Assert-V2AclExact -Acl (Get-V2Acl "$V2Root\caddy\Caddyfile") -ServiceSid $c -ServiceRights R -Label "$V2Root\caddy\Caddyfile"))
    $out.Add((Assert-V2AclTree -Path "$V2Root\services\caddy" -ServiceSid $c -ServiceRights RX -Role code))
    foreach ($d in "$V2Root\caddy\data", "$V2Root\caddy\config", "$V2Root\logs\caddy") { $out.Add((Assert-V2AclTree -Path $d -ServiceSid $c -ServiceRights M -Role data)) }
    $tls = "$V2Root\caddy\tls"
    if (Test-Path -LiteralPath $tls) {
      $out.Add((Assert-V2TlsDirectory -Path $tls -ServiceSid $c))
    }
  }
  $out.ToArray()
}
function Assert-V2Ancestors {
  if (-not (Test-Path -LiteralPath 'C:\srv' -PathType Container)) { Stop-V2 'C:\srv відсутній (факт №4) — створення захищеного предка лише за окремим рішенням №5 (New-V2ProtectedDirectory)' }
  foreach ($p in 'C:\', 'C:\srv') {
    if ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-V2 "reparse point: $p" }
    $r = @(Get-V2AclRisk -Acl (Get-V2Acl $p) -Kind ancestor)
    if ($r.Count) { Stop-V2 "${p}: небезпечні права (ACL спільного каталогу НЕ змінюємо — потрібне рішення №5): $($r -join '; ')" }
    "PASS  $p — власник і права безпечні"
  }
  if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує" }
}
# Дельта 4: production-варіант для C:\srv (ЛИШЕ за рішенням №5) — без параметрів-overrides: лише канонічний шлях C:\srv,
# лише затверджений SDDL, жодних довірених SID понад Administrators/SYSTEM/TrustedInstaller.
$V2SrvPath = 'C:\srv'
$V2SrvSddl = 'O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'
function New-V2ProtectedDirectory {
  param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $DecisionRef)
  if ($Path -cne $V2SrvPath) { Stop-V2 "дозволено лише точний затверджений шлях $V2SrvPath (отримано: $Path)" }
  New-V2ProtectedDirectoryCore -Path $Path -Sddl $V2SrvSddl -DecisionRef $DecisionRef -ExpectedOwnerSid $SidAdmins -AllowedSids @($SidAdmins, $SidSystem)
}
# Ядро (спільне для production і локальних тестів). Усі перевірки SDDL і шляху — ДО створення каталогу.
function New-V2ProtectedDirectoryCore {
  param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Sddl, [Parameter(Mandatory)] [string] $DecisionRef,
        [Parameter(Mandatory)] [string] $ExpectedOwnerSid, [Parameter(Mandatory)] [string[]] $AllowedSids, [string[]] $TrustedSids = @())
  if (-not $DecisionRef.Trim()) { Stop-V2 'потрібне посилання на рішення №5' }
  $full = Resolve-V2Path $Path
  $sec0 = New-Object System.Security.AccessControl.DirectorySecurity
  try { $sec0.SetSecurityDescriptorSddlForm($Sddl) } catch { Stop-V2 "некоректний SDDL: $($_.Exception.Message)" }
  if (-not $sec0.AreAccessRulesProtected) { Stop-V2 'SDDL має бути захищеним від успадкування (D:P)' }
  $own0 = $sec0.GetOwner([Security.Principal.SecurityIdentifier]); if ($null -eq $own0 -or $own0.Value -ne $ExpectedOwnerSid) { Stop-V2 "SDDL: власник $(if ($own0) { $own0.Value } else { '?' }) ≠ затвердженому $ExpectedOwnerSid" }
  $map0 = Get-V2AccessMap -Acl $sec0 -Scope Object
  foreach ($k in $map0.Keys) { if ($AllowedSids -notcontains $k) { Stop-V2 "SDDL: сторонній або надмірний запис $k" } elseif ($map0[$k] -ne 0x1F01FF) { Stop-V2 ('SDDL: права {0} 0x{1:X} ≠ FullControl' -f $k, $map0[$k]) } }
  foreach ($k in $AllowedSids) { if (-not $map0.ContainsKey($k)) { Stop-V2 "SDDL: немає обов'язкового запису $k" } }
  foreach ($sc in 'ChildContainer', 'ChildObject') { $m = Get-V2AccessMap -Acl $sec0 -Scope $sc; if (@(Compare-Object @($m.Keys | Sort-Object) @($map0.Keys | Sort-Object)).Count) { Stop-V2 "SDDL: успадковувані записи ($sc) ≠ записам об'єкта" } }
  if (Test-Path -LiteralPath $full) { Stop-V2 "$full уже існує — повторне використання заборонено" }
  $parent = [IO.Path]::GetDirectoryName($full)
  if (-not $parent -or -not (Test-Path -LiteralPath $parent -PathType Container)) { Stop-V2 "немає батьківського каталогу $parent" }
  Assert-V2NoReparseChain $parent
  $r = @(Get-V2AclRisk -Acl (Get-V2Acl $parent) -Kind ancestor -TrustedSids $TrustedSids)
  if ($r.Count) { Stop-V2 "${parent}: небезпечні права: $($r -join '; ')" }
  $sec = $sec0
  $null = [IO.Directory]::CreateDirectory($full, $sec)
  Assert-V2NoReparseChain $full
  $now = Get-V2Acl $full
  if (-not $now.AreAccessRulesProtected) { Stop-V2 "${full}: успадкування не вимкнено після створення" }
  foreach ($sc in 'Object', 'ChildContainer', 'ChildObject') {
    $a = Get-V2AccessMap -Acl $now -Scope $sc; $e = Get-V2AccessMap -Acl $sec -Scope $sc
    if (@(Compare-Object @($a.Keys | ForEach-Object { "$_=$($a[$_])" } | Sort-Object) @($e.Keys | ForEach-Object { "$_=$($e[$_])" } | Sort-Object)).Count) { Stop-V2 "${full}: ACL ($sc) після створення ≠ заданому" }
  }
  if ($now.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sec.GetOwner([Security.Principal.SecurityIdentifier]).Value) { Stop-V2 "${full}: власник ≠ заданому" }
  "PASS  $full створено атомарно із захищеним ACL (рішення: $DecisionRef)"
}
function New-V2Root {
  param([Parameter(Mandatory)] [scriptblock] $OnCreated)
  Assert-V2Ancestors
  $sec = New-Object System.Security.AccessControl.DirectorySecurity
  $sec.SetSecurityDescriptorSddlForm('O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)')
  # Directory.CreateDirectory silently accepts an existing path. CreateDirectoryW returns
  # ERROR_ALREADY_EXISTS instead, so only this process can acquire the ownership proof.
  if (-not ('V2AtomicRoot' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class V2AtomicRoot {
  [StructLayout(LayoutKind.Sequential)]
  private struct SecurityAttributes { public int Length; public IntPtr Descriptor; public bool Inherit; }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true, EntryPoint="CreateDirectoryW")]
  private static extern bool CreateDirectory(string path, ref SecurityAttributes attributes);
  public static void Create(string path, byte[] descriptor) {
    IntPtr p = Marshal.AllocHGlobal(descriptor.Length);
    try {
      Marshal.Copy(descriptor, 0, p, descriptor.Length);
      SecurityAttributes a = new SecurityAttributes { Length = Marshal.SizeOf(typeof(SecurityAttributes)), Descriptor = p, Inherit = false };
      if (!CreateDirectory(path, ref a)) throw new Win32Exception(Marshal.GetLastWin32Error(), "atomic V2 root create failed");
    } finally { Marshal.FreeHGlobal(p); }
  }
}
'@
  }
  [V2AtomicRoot]::Create($V2Root, $sec.GetSecurityDescriptorBinaryForm())
  & $OnCreated ([guid]::NewGuid().ToString('N'))
  Assert-V2Root
}
function Assert-V2Root {
  $full = Resolve-V2Path $V2Root
  Assert-V2NoReparseChain $full
  $r = @(Get-V2AclRisk -Acl (Get-V2Acl $full) -Kind v2root)
  if ($r.Count) { Stop-V2 "${full}: $($r -join '; ')" }
  Assert-V2AclExact -Acl (Get-V2Acl $full) -Label $full -IsContainer
}
function Grant-V2 {
  param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Account, [Parameter(Mandatory)] [ValidateSet('(OI)(CI)RX', '(OI)(CI)M', 'RX', 'R')] [string] $Rights)
  if ($Account -notin @($V2Services.Values | ForEach-Object { $_.Account })) { Stop-V2 "ACL лише для акаунтів служб V2: $Account" }
  $full = Assert-V2InRoot $Path                                                       # канонічний шлях, без .., без reparse — ДО icacls
  if (-not (Test-Path -LiteralPath $full)) { Stop-V2 "немає $full" }
  $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\icacls.exe" -ArgList @($full, '/grant', "${Account}:$Rights") -What "icacls $full"
  $svcSid = (New-Object Security.Principal.NTAccount($Account)).Translate([Security.Principal.SecurityIdentifier]).Value
  $level = $Rights -replace '^\(OI\)\(CI\)', ''
  $isTlsDirectory = $full -eq "$V2Root\caddy\tls" -and $Account -eq $V2Services['integrity-v2-caddy'].Account -and $Rights -eq 'RX'
  $container = (Test-Path -LiteralPath $full -PathType Container) -and -not $isTlsDirectory
  $null = Assert-V2AclExact -Acl (Get-V2Acl $full) -ServiceSid $svcSid -ServiceRights $level -Label $full -IsContainer:$container
  "PASS  icacls $full $Account $Rights; read-back = матриця"
}
function Assert-V2FileHash {
  param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Sha256, [string] $Label = $Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-V2 "${Label}: немає файлу" }
  $h = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
  if ($h -ne $Sha256.ToLower()) { Stop-V2 "${Label}: SHA256 $h ≠ еталону $Sha256" }
  "PASS  ${Label}: SHA256 = еталон"
}

# =====================================================================================================================
# P6: WinSW 2.12.0 — точна версія й SHA джерела і кожної копії; лише схема v2 (serviceaccount/domain + user); v3 не підтримується
# =====================================================================================================================
function ConvertTo-V2Version([string]$FileVersion) { $p = @(($FileVersion -replace '[^0-9.].*$', '') -split '\.' | Where-Object { $_ -ne '' }); if ($p.Count -lt 3) { return '' }; ($p[0..2] -join '.') }
function Assert-V2Winsw {
  param([Parameter(Mandatory)] [string] $Path, [string] $Label = $Path, [string] $Sha256 = $WinswRefSha256, [string] $Version = $WinswRefVersion)
  $null = Assert-V2FileHash -Path $Path -Sha256 $Sha256 -Label $Label
  $fv = [string](Get-Item -LiteralPath $Path).VersionInfo.FileVersion
  if ((ConvertTo-V2Version $fv) -ne $Version) { Stop-V2 "${Label}: FileVersion '$fv' ≠ $Version" }
  "PASS  ${Label}: WinSW $Version, SHA256 = еталон"
}
$WinswAllowed = @('id', 'name', 'description', 'executable', 'arguments', 'workingdirectory', 'env', 'startmode', 'serviceaccount',
                  'onfailure', 'resetfailure', 'stoptimeout', 'logpath', 'log', 'depend')
function Test-V2WinswXml {
  param([Parameter(Mandatory)] [string] $XmlPath, [Parameter(Mandatory)] [string] $Name, [Parameter(Mandatory)] [string] $WinswVersion, [switch] $AllowPlaceholders)
  if ($WinswVersion -ne $WinswRefVersion) { Stop-V2 "WinSW ${WinswVersion}: дозволено лише $WinswRefVersion (факт №4)" }
  [xml]$x = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
  $s = $x.SelectSingleNode('/service'); if (-not $s) { Stop-V2 'XML: немає <service>' }
  $bad = @($s.ChildNodes | Where-Object { $_.NodeType -eq 'Element' -and $WinswAllowed -notcontains $_.LocalName } | ForEach-Object LocalName)
  if ($bad.Count) { Stop-V2 "XML: недокументовані елементи: $($bad -join ', ')" }
  $one = { param($xp) $n = $s.SelectSingleNode($xp); if ($n) { $n.InnerText } else { $null } }
  if ((& $one 'id') -ne $Name) { Stop-V2 "XML: id = $(& $one 'id')" }
  if ((& $one 'startmode') -ne 'Manual') { Stop-V2 "XML: startmode = $(& $one 'startmode')" }
  $sa = $s.SelectSingleNode('serviceaccount'); if (-not $sa) { Stop-V2 'XML: немає serviceaccount' }
  $saKids = @($sa.ChildNodes | Where-Object { $_.NodeType -eq 'Element' } | ForEach-Object LocalName | Sort-Object)
  if (($saKids -join ',') -ne 'domain,user' -or (& $one 'serviceaccount/domain') -ne 'NT SERVICE' -or (& $one 'serviceaccount/user') -ne $Name) { Stop-V2 "XML: serviceaccount має бути рівно <domain>NT SERVICE</domain><user>$Name</user> (схема WinSW 2.12; без password/username)" }
  $exe = [string](& $one 'executable')
  if (-not $exe.StartsWith("$V2Root\", [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "XML: executable поза ${V2Root}: $exe" }
  $envNames = @($s.SelectNodes('env') | ForEach-Object { $_.GetAttribute('name') })
  foreach ($n in 'INTEGRITY_DEMO_XROLE', 'V2_AUTH_DEV_MAIL', 'V2_AUTH_SECURE_COOKIE') { if ($envNames -contains $n) { Stop-V2 "XML: заборонена змінна $n" } }
  # I3 (hardening): з --no-proxy-headers IP клієнта береться з X-Forwarded-For лише від TRUSTED_PROXIES; без точного
  # TRUSTED_PROXIES=127.0.0.1,::1 усі клієнти стають 127.0.0.1 (Caddy) і ліміти спроб стають глобальними
  $argTokens = @(([string](& $one 'arguments')) -split '\s+' | Where-Object { $_ })
  if ($argTokens -contains '--no-proxy-headers') {
    $tp = @($s.SelectNodes('env') | Where-Object { $_.GetAttribute('name') -eq 'TRUSTED_PROXIES' })
    if ($tp.Count -ne 1 -or $tp[0].GetAttribute('value') -cne '127.0.0.1,::1') { Stop-V2 'XML: --no-proxy-headers вимагає рівно одну змінну TRUSTED_PROXIES=127.0.0.1,::1' }
  }
  if (-not $AllowPlaceholders -and (Select-String -LiteralPath $XmlPath -Pattern '__V2_' -Quiet)) { Stop-V2 'XML: незаповнені плейсхолдери' }
  "PASS  XML $Name — схема WinSW $WinswRefVersion, Manual, NT SERVICE\$Name"
}

# =====================================================================================================================
# P3: служби — Manual, точні властивості; власники wrapper і всіх нащадків; збереження ідентичностей; stop-and-verify лише V2
# =====================================================================================================================
function Get-V2Service([string]$Name) { Get-CimInstance Win32_Service -Filter "Name='$Name'" }
# auditfix2 W1: start type служби V2 (лише Disabled/Manual) з read-back. Адаптер — у тестах підміняється (I0).
function Set-V2ServiceStartMode {
  param([Parameter(Mandatory)] [string] $Name, [Parameter(Mandatory)] [ValidateSet('Disabled', 'Manual')] [string] $Mode)
  if (-not $V2Services.ContainsKey($Name)) { Stop-V2 "start type лише для служб V2: $Name" }
  $arg = if ($Mode -eq 'Disabled') { 'disabled' } else { 'demand' }
  $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('config', $Name, 'start=', $arg) -What "sc config $Name start= $arg"
  $chk = Get-V2Service $Name
  if (-not $chk -or $chk.StartMode -ne $Mode) { Stop-V2 "start type $Name не підтверджено: $(if ($chk) { $chk.StartMode } else { 'служби немає' }) ≠ $Mode" }
}
function Assert-V2Service {
  param([Parameter(Mandatory)] [string] $Name, [Parameter(Mandatory)] [ValidateSet('Stopped', 'Running')] [string] $State)
  $want = $V2Services[$Name]; if (-not $want) { Stop-V2 "невідома служба $Name" }
  $s = Get-V2Service $Name; if (-not $s) { Stop-V2 "служби $Name немає" }
  $path = $s.PathName.Trim().Trim('"')
  if ($s.StartName -ne $want.Account) { Stop-V2 "${Name}: StartName = $($s.StartName), очікується $($want.Account)" }
  if ($path -ne $want.Exe) { Stop-V2 "${Name}: PathName = $($s.PathName)" }
  if ($s.StartMode -ne 'Manual') { Stop-V2 "${Name}: StartMode = $($s.StartMode), очікується Manual" }
  if ($s.State -ne $State) { Stop-V2 "${Name}: State = $($s.State), очікується $State" }
  "PASS  ${Name}: $($s.StartName), Manual, $State"
}
function Install-V2Service {
  param([Parameter(Mandatory)] [string] $Name, [scriptblock] $OnCreated = $null)
  $want = $V2Services[$Name]
  if (Get-V2Service $Name) { Stop-V2 "служба $Name уже існує" }
  $null = Assert-V2Winsw -Path $want.Exe -Label "WinSW $Name (копія)"
  $installError = $null
  try { $null = Invoke-V2Native -Exe $want.Exe -ArgList @('install') -What "WinSW install $Name" }
  catch { $installError = $_ }
  $s = Get-V2Service $Name; if (-not $s) { Stop-V2 "$Name не створено" }
  # WinSW may create the SCM entry and then fail. Register ownership before any
  # account/start-mode read-back, but only for the wrapper inside our new root.
  $path = $s.PathName.Trim().Trim('"')
  if ($path -ne $want.Exe) { Stop-V2 "${Name}: створена служба має чужий PathName = $($s.PathName)" }
  if ($OnCreated) { & $OnCreated $Name }
  if ($installError) { throw $installError }
  if ($s.StartName -ne $want.Account) {
    $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('config', $Name, 'obj=', $want.Account) -What "sc config $Name"
  }
  Assert-V2Service -Name $Name -State Stopped
}
function Get-V2ServiceTree {
  param([Parameter(Mandatory)] [string] $Name, [System.Collections.Generic.List[object]] $Unresolved = $null)
  $s = Get-V2Service $Name; if (-not $s -or -not $s.ProcessId) { Stop-V2 "${Name}: немає PID процесу служби" }
  $h = $null; try { $h = Open-V2ProcessHandle ([int]$s.ProcessId) } catch { Stop-V2 "${Name}: handle процесу $($s.ProcessId) не відкрито: $($_.Exception.Message)" }
  New-V2Tree -RootProcess $h -Unresolved $Unresolved
}
function Assert-V2ServiceRunning {
  param([Parameter(Mandatory)] [string] $Name, [string[]] $Addresses, [string] $IdentityDir = "$V2Root\pkg\identities")
  foreach ($i in 1..20) { if ((Get-V2Service $Name).State -eq 'Running') { break }; Start-Sleep 1 }
  $out = New-Object System.Collections.Generic.List[string]
  $out.Add((Assert-V2Service -Name $Name -State Running))
  $tree = Get-V2ServiceTree -Name $Name
  $V2Identity[$Name] = $tree                                                   # одразу — для автозупинки й відкату навіть при провалі нижче
  $acct = $V2Services[$Name].Account
  foreach ($t in $tree) { if ($t.Owner -ne $acct) { Stop-V2 "${Name}: PID $($t.Pid) ($($t.Exe)) — власник $($t.Owner) ≠ $acct" } }
  $out.Add((Wait-V2Listener -Port $V2Services[$Name].Port -Tree $tree -Addresses $Addresses))     # до будь-якого HTTP
  foreach ($t in $tree) { if ($t.Owner -ne $acct) { Stop-V2 "${Name}: нащадок PID $($t.Pid) — власник $($t.Owner) ≠ $acct" } }
  $out.Add("PASS  ${Name}: власники wrapper і нащадків ($($tree.Count)) = $acct; ідентичності: $(Save-V2Identities -Name $Name -Tree $tree -Dir $IdentityDir)")
  $out.ToArray()
}
# Stop-and-verify лише V2: sc stop цієї служби → Stopped → доведений вихід збережених процесів → порт служби вільний.
# Незавершені процеси або слухач → CRITICAL BLOCKED (нічого не зупиняється «про всяк випадок»).
# Дельта 2: пізні нащадки — процеси, батько яких є в дереві, створені ПІСЛЯ батька (у т.ч. осиротілі після його виходу).
# Повертає записи CIM (без handle); рекурсивно охоплює нащадків нащадків, які ще живі.
function Get-V2LateDescendants {
  param([Parameter(Mandatory)] [AllowEmptyCollection()] $Tree)
  $all = @(Get-V2CimProcessList)
  $known = @{}; foreach ($t in $Tree) { $known[[int]$t.Pid] = [int64]$t.StartUtcTicks }
  $late = New-Object System.Collections.Generic.List[object]
  $queue = New-Object System.Collections.Generic.List[object]; foreach ($k in $known.Keys) { $queue.Add(@($k, $known[$k])) }
  $i = 0
  while ($i -lt $queue.Count) {
    $ppid = [int]$queue[$i][0]; $pticks = [int64]$queue[$i][1]
    foreach ($c in @($all | Where-Object { [int]$_.ParentProcessId -eq $ppid -and [int]$_.ProcessId -ne $ppid })) {
      $cid = [int]$c.ProcessId; $ct = ConvertTo-V2Ticks $c.CreationDate
      if ($ct -lt $pticks) { continue }                                           # старший за батька — не нащадок (PID reuse)
      if ($known.ContainsKey($cid) -and $known[$cid] -eq $ct) { continue }          # уже в дереві
      if (@($late | Where-Object { [int]$_.ProcessId -eq $cid }).Count) { continue }
      $late.Add($c); $queue.Add(@($cid, $ct))
    }
    $i++
  }
  $late.ToArray()
}
# =====================================================================================================================
# Етап 2/3 (ЕКСПЕРИМЕНТ): модель повноти процесів backend через Windows Job Object (v2_job_launcher.py). Не затверджено для
# production: увімкнення — лише $V2Services[...].Job + $V2JobTool за окремим рішенням №5.
# =====================================================================================================================
# SID віртуального акаунта служби (NT SERVICE\<ім'я>): S-1-5-80-<5 × UInt32 із SHA1(UTF-16LE(ІМ'Я у верхньому регістрі))>
function Get-V2ServiceSid([string]$Name) {
  $sha = [Security.Cryptography.SHA1]::Create()
  try { $h = $sha.ComputeHash([Text.Encoding]::Unicode.GetBytes($Name.ToUpperInvariant())) } finally { $sha.Dispose() }
  'S-1-5-80-' + ((0..4 | ForEach-Object { [BitConverter]::ToUInt32($h, $_ * 4) }) -join '-')
}
function Invoke-V2JobTool {
  param([Parameter(Mandatory)] [string[]] $ArgList)
  if (-not $V2JobTool.Py -or -not $V2JobTool.Script) { Stop-V2 'Job Object: не задано інтерпретатор або v2_job_launcher.py' }
  @(Invoke-V2Native -Exe $V2JobTool.Py -ArgList (@('-I', '-E', '-s', $V2JobTool.Script) + $ArgList) -OkCodes @(0, 2) -Utf8 -What "v2_job_launcher $($ArgList[0])")
}
# Звіт proof (JSON). Без -Scan — лише стан job (SD, ліміти, PID-list). Production: --unknown block; -LocalBaseline — лише локальна репетиція.
function Get-V2JobReport {
  param([Parameter(Mandatory)] [string] $JobName, [Parameter(Mandatory)] [string] $OwnerSid, [switch] $Scan, [string] $LocalBaseline, [int[]] $ExcludePid = @())
  if ($V2JobLocalRehearsal -and $V2JobLocalRehearsal.OwnerSid) { $OwnerSid = $V2JobLocalRehearsal.OwnerSid }   # лише rehearse: власник job/scan — поточний користувач
  $a = @('proof', '--job', $JobName, '--expect-owner', $OwnerSid)
  if ($Scan -and -not $LocalBaseline -and $V2JobLocalRehearsal) { $LocalBaseline = $V2JobLocalRehearsal.Baseline; $ExcludePid = @($ExcludePid) + @($V2JobLocalRehearsal.ExcludePid) }
  if ($ExcludePid.Count) { $a += @('--exclude-pid', ($ExcludePid -join ',')) }
  if ($Scan -and $V2JobLocalRehearsal -and $V2JobLocalRehearsal.ScopeRoot) { $a += @('--scope-root', (@($V2JobLocalRehearsal.ScopeRoot) -join ',')) }   # лише rehearse
  if ($Scan) { $a += @('--scan-sid', $OwnerSid); if ($LocalBaseline) { $a += @('--unknown', 'baseline', '--baseline', $LocalBaseline) } else { $a += @('--unknown', 'block') } }
  # auditfix2: BLOCKED лише через scan (job порожній, SD/ліміти OK) — до 5 спостережень з інтервалом 400 мс: короткоживучі процеси
  # (напр. conhost.exe щойно завершеного процесу) зникають; стійка присутність → BLOCKED. PASS — лише за реального чистого спостереження.
  for ($try = 1; $try -le 5; $try++) {
    $o = @(Invoke-V2JobTool -ArgList $a)
    if (-not $o.Count) { Stop-V2 'Job proof: немає результату' }
    try { $r = ConvertFrom-Json -InputObject ([string]$o[-1]) } catch { Stop-V2 "Job proof: некоректний JSON: $($o[-1])" }
    if ($null -eq $r -or $null -eq $r.PSObject.Properties['verdict']) { Stop-V2 'Job proof: у звіті немає verdict' }
    $scanOnly = $Scan -and $r.verdict -ne 'PASS' -and $r.found -and $r.sd_ok -and $r.limits_ok -and [int]$r.active -eq 0 -and @($r.pids).Count -eq 0
    if (-not $scanOnly -or $try -eq 5) { break }
    Start-Sleep -Milliseconds 400
  }
  $r
}
# Утримання handle job на час зупинки: job не зникає разом із launcher-ом, тож доказ ActiveProcesses = 0 можливий після stop.
function Start-V2JobHolder {
  param([Parameter(Mandatory)] [string] $JobName)
  if (-not $V2JobTool.Py -or -not $V2JobTool.Script) { Stop-V2 'Job Object: не задано інтерпретатор або v2_job_launcher.py' }
  $psi = New-Object Diagnostics.ProcessStartInfo $V2JobTool.Py
  $psi.Arguments = "-I -E -s `"$($V2JobTool.Script)`" hold --job `"$JobName`""
  $psi.UseShellExecute = $false; $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.CreateNoWindow = $true
  $p = [Diagnostics.Process]::Start($psi); $null = $p.Handle
  $first = $p.StandardOutput.ReadLine()
  if ($first -ne 'HOLD OK') { try { Stop-V2Handle $p } catch { }; Stop-V2 "Job Object: утримання handle '$JobName' неможливе ($first)" }
  $V2OwnHelpers[[int]$p.Id] = $p.StartTime.ToUniversalTime().Ticks                        # auditfix3: власний процес installer-а
  $p
}
function Stop-V2JobHolder {
  param([Parameter(Mandatory)] $Holder)
  try { $Holder.StandardInput.Close() } catch { }
  if (-not (Wait-V2Handle $Holder 10000)) { Stop-V2Handle $Holder; if (-not (Wait-V2Handle $Holder 5000)) { Stop-V2 'Job Object: процес утримання handle не завершився' } }
  if ($Holder.PSObject.Properties['Id']) { $V2OwnHelpers.Remove([int]$Holder.Id) }
}
# Stop-and-verify лише V2 (дельта 2): БЕЗПОСЕРЕДНЬО перед sc stop — актуальне дерево служби з handle, ідентичністю й власником
# кожного процесу (корінь має збігатися зі збереженим); sc stop цієї служби → Stopped → доведений вихід усього актуального
# дерева → немає пізніх нащадків і евристичних процесів V2 → порт вільний. Будь-яка неповнота → CRITICAL BLOCKED (sc stop
# однаково виконується: зупинка V2 — безпечна дія; нічого іншого не зупиняється). Доказ зберігається в $V2StopProof.
$V2StopProof = @{}
function Stop-V2Service {
  param([Parameter(Mandatory)] [string] $Name)
  $previousProof = $V2StopProof[$Name]
  $V2StopProof.Remove($Name)  # до будь-якого early return
  if ($previousProof -and $previousProof.PSObject.Properties['Lease'] -and $previousProof.Lease) { try { Stop-V2JobHolder -Holder $previousProof.Lease } catch { Stop-V2 "стару proof lease не закрито: $($_.Exception.Message)" } }
  $ctx = @{ Holder = $null }; $ok = $false; $err = $null; $res = $null; $relErr = $null
  try { $res = Stop-V2ServiceCore -Name $Name -Ctx $ctx; $ok = $true }
  catch { $err = $_ }
  finally {
    if (-not $ok) {                                                              # auditfix2: будь-яка відмова — без доказу й без lease
      $V2StopProof.Remove($Name)
      if ($ctx.Holder) { try { Stop-V2JobHolder -Holder $ctx.Holder } catch { $relErr = $_.Exception.Message -replace '^STOP: ', '' } }
    }
  }
  if ($err) { Stop-V2 "$($err.Exception.Message -replace '^STOP: ', '')$(if ($relErr) { "; CLEANUP: lease не звільнено: $relErr" })" }
  $res
}
function Stop-V2ServiceCore {
  param([string] $Name, [hashtable] $Ctx)
  $s = Get-V2Service $Name; if (-not $s) { return "INFO  $Name не встановлено; доказ зупинки відсутній" }
  $acct = $V2Services[$Name].Account
  $problems = New-Object System.Collections.Generic.List[string]
  $saved = $null; if ($V2Identity.ContainsKey($Name) -and $V2Identity[$Name]) { $saved = $V2Identity[$Name] }
  $tree = $null
  $unres = New-Object System.Collections.Generic.List[object]                   # B1: нащадки, чий handle не відкрито
  $jobName = $V2Services[$Name].Job; $holder = $null; $jobProof = $null; $svcSid = Get-V2ServiceSid $Name
  if ($s.State -ne 'Stopped' -or $s.ProcessId) {
    if (-not $s.ProcessId) { $problems.Add("немає PID процесу служби — дерево не встановлено") }
    else {
      try {
        $tree = Get-V2ServiceTree -Name $Name -Unresolved $unres                    # актуальне дерево: handle + ідентичність кожного
        if ($saved -and ($saved[0].Pid -ne $tree[0].Pid -or $saved[0].StartUtcTicks -ne $tree[0].StartUtcTicks)) { $problems.Add("корінь служби змінився з моменту старту (PID $($saved[0].Pid) → $($tree[0].Pid))") }
        if ($saved) { foreach ($t in $saved) { if (-not (Test-V2HandleExited $t.Handle) -and -not @($tree | Where-Object { $_.Pid -eq $t.Pid -and $_.StartUtcTicks -eq $t.StartUtcTicks }).Count) { $tree.Add($t) } } }
        foreach ($t in $tree) { if ($t.Owner -ne $acct) { $problems.Add("PID $($t.Pid) — власник $($t.Owner) ≠ $acct") } }
      } catch { $problems.Add("актуальне дерево не встановлено: $($_.Exception.Message -replace '^STOP: ', '')") }
    }
  }
  if ($jobName) {                                                               # S06: job, його SD, ліміти й членство — ДО sc stop
    try {
      $holder = Start-V2JobHolder -JobName $jobName
      $Ctx.Holder = $holder                                                       # обгортка звільнить його на будь-якій відмові
      $pre = Get-V2JobReport -JobName $jobName -OwnerSid $svcSid
      if (-not $pre.found) { $problems.Add("Job Object '$jobName' не знайдено") }
      else {
        if (-not $pre.sd_ok) { $problems.Add("SD Job Object не відповідає очікуваному (власник $svcSid)") }
        if (-not $pre.limits_ok) { $problems.Add("ліміти Job Object $($pre.limits) ≠ очікуваним") }
        if ($tree) {
          $lau = @($tree | Where-Object { [string]$_.CommandLine -match 'v2_job_launcher\.py' })
          if ($lau.Count -ne 1) { $problems.Add("launcher у дереві служби: $($lau.Count) (очікується 1)") }
          else {
            $inJob = @($pre.pids | ForEach-Object { [int]$_ })
            $desc = @{}; $desc[[int]$lau[0].Pid] = $true; $changed = $true
            while ($changed) { $changed = $false; foreach ($t in $tree) { if (-not $desc.ContainsKey([int]$t.Pid) -and $desc.ContainsKey([int]$t.ParentPid)) { $desc[[int]$t.Pid] = $true; $changed = $true } } }
            foreach ($t in $tree) { if ([int]$t.Pid -ne [int]$lau[0].Pid -and $desc.ContainsKey([int]$t.Pid) -and $inJob -notcontains [int]$t.Pid) { $problems.Add("PID $($t.Pid) (нащадок launcher-а) поза Job Object") } }
          }
        }
      }
    } catch { $problems.Add("Job Object до stop: $($_.Exception.Message -replace '^STOP: ', '')") }
  }
  if ($s.State -ne 'Stopped') { $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('stop', $Name) -What "sc stop $Name" -OkCodes @(0, 1062) }
  foreach ($i in 1..30) { if ((Get-V2Service $Name).State -eq 'Stopped') { break }; Start-Sleep 1 }
  if ((Get-V2Service $Name).State -ne 'Stopped') { $problems.Add("$Name не перейшла в Stopped") }
  if ($jobName) {                                                               # S07/S08: спершу job (поки installer утримує handle, процеси job живі): terminate ЛИШЕ цього job → ActiveProcesses 0, процесів акаунта 0
    try {
      $post = Get-V2JobReport -JobName $jobName -OwnerSid $svcSid -Scan
      if ($post.found -and ([int]$post.active -gt 0 -or @($post.pids).Count)) {
        if ($problems.Count -or -not $pre -or -not $pre.found -or -not $pre.sd_ok -or -not $pre.limits_ok -or -not $post.sd_ok -or -not $post.limits_ok) {
          Stop-V2 'Job Object: terminate заборонено — identity, DACL, limits або дерево не підтверджено'
        }
        $null = Invoke-V2JobTool -ArgList @('terminate', '--job', $jobName, '--expect-owner', $svcSid)     # лише цей job V2; нічого за PID
        $post = Get-V2JobReport -JobName $jobName -OwnerSid $svcSid -Scan
      }
      if ($post.verdict -ne 'PASS') { $problems.Add("Job Object після stop: $(@($post.problems) -join '; ')") } else { $jobProof = $post }
    } catch { $problems.Add("Job Object після stop: $($_.Exception.Message -replace '^STOP: ', '')") }
  }
  foreach ($u in $unres) {                                                      # B1: без handle вихід/ідентичність не доведені → BLOCKED
    $now = $null; try { $now = Get-V2CimProcess $u.Pid } catch { }
    $st = if ($now -and (ConvertTo-V2Ticks $now.CreationDate) -eq $u.StartUtcTicks) { 'досі живий' } else { 'після stop у CIM відсутній, але ідентичність не підтверджувалась' }
    $problems.Add("нерозв'язаний нащадок PID $($u.Pid) (батько $($u.ParentPid)): $($u.Reason); $st")
  }
  if ($tree) {
    $roots = New-Object System.Collections.Generic.List[object]; foreach ($t in $tree) { $roots.Add($t) }; foreach ($u in $unres) { $roots.Add($u) }
    try { $null = Assert-V2TreeExited -Tree $tree } catch { $problems.Add(($_.Exception.Message -replace '^STOP: ', '')) }
    try { $late = @(Get-V2LateDescendants -Tree $roots); if ($late.Count) { $problems.Add("пізні нащадки живі: $(($late | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ', ')") } } catch { $problems.Add("перевірка пізніх нащадків: $($_.Exception.Message)") }
  }
  try { $sp = @(Get-V2SuspectProcesses | Where-Object { $_.CommandLine -match "--port\s+$($V2Services[$Name].Port)\b" -or ($_.ExecutablePath -and $_.ExecutablePath.StartsWith("$V2Root\", [StringComparison]::OrdinalIgnoreCase)) })
        if ($sp.Count) { $problems.Add("евристика: процеси V2 живі: $(($sp | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ', ')") } } catch { $problems.Add("евристика: $($_.Exception.Message)") }
  $l = @(Get-V2Listeners @($V2Services[$Name].Port)); if ($l.Count) { $problems.Add("порт $($V2Services[$Name].Port) досі слухає PID $(@($l | ForEach-Object OwningProcess) -join ',')") }
  if ($Name -eq 'integrity-v2-backend' -and (Test-Path -LiteralPath "$V2Root\data")) {          # S10: DB/WAL/SHM не утримуються
    try { $null = Assert-V2DbFilesFree -DataDir "$V2Root\data" } catch { $problems.Add(($_.Exception.Message -replace '^STOP: ', '')) }
  }
  if ($problems.Count) { Stop-V2 "CRITICAL BLOCKED — ${Name}: $($problems -join '; ')" }
  if ($unres.Count) { Stop-V2 "CRITICAL BLOCKED — ${Name}: нерозв'язані нащадки — доказ зупинки не створюється" }   # захист від регресії
  $V2StopProof[$Name] = [pscustomobject]@{ Name = $Name; Tree = $tree; Unresolved = 0; VerifiedUtc = [datetime]::UtcNow
                                            Completeness = $(if ($jobProof) { 'job' } else { 'tree-only' }); JobVerified = [bool]$jobProof
                                            JobName = $jobName; JobActive = $(if ($jobProof) { [int]$jobProof.active } else { -1 }); OwnerScanAlive = $(if ($jobProof) { 0 } else { -1 }); Lease = $holder }
  "PASS  $Name зупинено; актуальне дерево ($(if ($tree) { $tree.Count } else { 0 })) завершилось, пізніх нащадків 0; порт вільний; повнота: $(if ($jobProof) { 'Job Object (ActiveProcesses 0, PID-list порожній, процесів акаунта 0)' } else { 'лише дерево (без Job Object)' })"
}
# Старт: відмова ДО старту (PreCheck) нічого не зупиняє; будь-яка помилка ПІСЛЯ спроби старту — зокрема всередині Starter
# (частковий старт) — веде до stop-and-verify лише цієї V2-служби, потім STOP.
function Invoke-V2ServiceStart {
  param([Parameter(Mandatory)] [string] $Name, [Parameter(Mandatory)] [scriptblock] $Checks,
        [scriptblock] $PreCheck = { param($n) $null = Assert-V2Service -Name $n -State Stopped; if ($n -eq 'integrity-v2-backend') { $null = Assert-V2DataReady -DataDir "$V2Root\data" } },
        [scriptblock] $Starter = { param($n) $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('start', $n) -What "sc start $n" },
        [scriptblock] $Stopper = { param($n) Stop-V2Service -Name $n })
  $prevProof = $V2StopProof[$Name]; $V2StopProof.Remove($Name)                  # auditfix2: після старту доказ зупинки не чинний
  if ($prevProof -and $prevProof.PSObject.Properties['Lease'] -and $prevProof.Lease) {
    try { Stop-V2JobHolder -Holder $prevProof.Lease } catch { Stop-V2 "старт $Name заборонено: lease попереднього stop не звільнено: $($_.Exception.Message -replace '^STOP: ', '')" }
  }
  & $PreCheck $Name
  $res = $null
  try { & $Starter $Name; $res = @(& $Checks) }
  catch {
    $why = $_.Exception.Message -replace '^STOP: ', ''
    $st = $null
    try { $st = & $Stopper $Name } catch { Stop-V2 "$why; АВТОЗУПИНКА $Name НЕ ПІДТВЕРДЖЕНА: $($_.Exception.Message -replace '^STOP: ', '')" }
    Stop-V2 "$why; $Name автоматично зупинено ($st)"
  }
  $res
}

# --- Baseline V1 (лише читання). V1 — DEPRECATED / OUT OF SCOPE: лише контроль, що встановлення V2 його не зачепило ----------
function Get-V2ServiceList { @(Get-CimInstance Win32_Service) }   # адаптер (у тестах підміняється)
# -AllowAbsent (Clean Install): V1 не обов'язкова — якщо її немає, baseline порожній, контроль «без змін» працює так само
function Get-V1Baseline {
  param([switch] $AllowAbsent)
  $v1 = @(Get-V2ServiceList | Where-Object { ($_.Name -eq 'HacatonBackend' -or $_.PathName -match '(?i)caddy') -and $_.Name -notlike 'integrity-v2-*' } | Sort-Object Name)
  if (-not $AllowAbsent) {
    if (-not ($v1 | Where-Object { $_.Name -eq 'HacatonBackend' })) { Stop-V2 'baseline: службу HacatonBackend не знайдено' }
    if (-not ($v1 | Where-Object { $_.PathName -match '(?i)caddy' })) { Stop-V2 'baseline: чинну службу Caddy не знайдено' }
  }
  $svc = @($v1 | ForEach-Object { '{0}|{1}|{2}|{3}|{4}|{5}' -f $_.Name, $_.State, $_.StartMode, $_.StartName, $_.PathName, $_.ProcessId })
  $pids = @($v1 | Where-Object { $_.ProcessId } | ForEach-Object { [int]$_.ProcessId })
  $all = @(Get-V2CimProcessList)
  $i = 0; while ($i -lt $pids.Count) { foreach ($c in @($all | Where-Object { [int]$_.ParentProcessId -eq $pids[$i] })) { if ($pids -notcontains [int]$c.ProcessId) { $pids += [int]$c.ProcessId } }; $i++ }
  $ports = @(if ($pids.Count) { Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $pids -contains [int]$_.OwningProcess } |
    Sort-Object LocalPort, LocalAddress | ForEach-Object { '{0}:{1}|{2}' -f $_.LocalAddress, $_.LocalPort, $_.OwningProcess } })
  [pscustomobject]@{ Services = $svc; Ports = $ports; Present = [bool]$v1.Count; AllowAbsent = [bool]$AllowAbsent }
}
function Assert-V1Unchanged {
  param([Parameter(Mandatory)] $Baseline)
  $now = Get-V1Baseline -AllowAbsent:([bool]$Baseline.AllowAbsent)
  $d = @(Compare-Object $Baseline.Services $now.Services) + @(Compare-Object $Baseline.Ports $now.Ports)
  if ($d.Count) { Stop-V2 "чинні служби змінились (стан/PID/порти): $(($d | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) -join '; ')" }
  'PASS  чинні служби без змін (HacatonBackend, Caddy: стан, режим, акаунт, шлях, PID, порти)'
}

# --- I03: секрети у XML служби — без виводу; BSTR обнуляється у finally (REV3, без змін) ----------------------------------
function Set-V2Secrets {
  param([Parameter(Mandatory)] [string] $XmlPath, [string[]] $Prompted = @('V2_SMTP_HOST', 'V2_SMTP_USER', 'V2_SMTP_PASSWORD', 'V2_SMTP_FROM'),
        [scriptblock] $SecretReader = { param($n) Read-Host -Prompt $n -AsSecureString }, [switch] $Rehearsal)
  if (-not $Rehearsal -and -not $XmlPath.StartsWith("$V2Root\services\", [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "секрети лише в $V2Root\services\" }
  $t = [IO.File]::ReadAllText($XmlPath)
  try {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $b = New-Object byte[] 48
    try { $rng.GetBytes($b); $t = $t.Replace('__V2_SECRET_KEY__', [Convert]::ToBase64String($b)) } finally { [Array]::Clear($b, 0, $b.Length); $rng.Dispose() }
    foreach ($n in $Prompted) {
      $s = & $SecretReader $n
      if ($null -eq $s -or $s.Length -eq 0) { Stop-V2 "порожнє значення $n" }
      $p = [IntPtr]::Zero
      try {
        $p = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
        $t = $t.Replace("__${n}__", [Security.SecurityElement]::Escape([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)))
      } finally {
        if ($p -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p) }
        $s.Dispose()
      }
    }
    if ($t.Contains('__V2_')) { Stop-V2 'незаповнені плейсхолдери' }
    [IO.File]::WriteAllText($XmlPath, $t, (New-Object Text.UTF8Encoding $false))
  } finally { $t = $null; [GC]::Collect() }
  if (Select-String -LiteralPath $XmlPath -Pattern '__V2_' -Quiet) { Stop-V2 'незаповнені плейсхолдери' }
  'PASS  секрети записано у XML (значення не виводились)'
}

# --- P2: тимчасове оточення — помилки відновлення не приховуються ----------------------------------------------------------
function Use-V2Env {
  param([Parameter(Mandatory)] [hashtable] $Vars, [Parameter(Mandatory)] [scriptblock] $Body)
  $saved = @{}; foreach ($k in $Vars.Keys) { $saved[$k] = Get-V2EnvVar $k }
  $bodyErr = $null; $result = $null
  try { foreach ($k in $Vars.Keys) { Set-V2EnvVar $k ([string]$Vars[$k]) }; $result = @(& $Body) } catch { $bodyErr = $_ }
  $restoreErr = New-Object System.Collections.Generic.List[string]
  foreach ($k in $saved.Keys) {
    try { Set-V2EnvVar $k $saved[$k]; $now = Get-V2EnvVar $k; if ("$now" -ne "$($saved[$k])") { $restoreErr.Add("$k не відновлено") } } catch { $restoreErr.Add("${k}: $($_.Exception.Message)") }
  }
  if ($bodyErr -and $restoreErr.Count) { Stop-V2 "$($bodyErr.Exception.Message -replace '^STOP: ', ''); ВІДНОВЛЕННЯ ENV: $($restoreErr -join '; ')" }
  if ($bodyErr) { throw $bodyErr }
  if ($restoreErr.Count) { Stop-V2 "відновлення env: $($restoreErr -join '; ')" }
  $result
}
function New-V2RandomKey { $r = [Security.Cryptography.RandomNumberGenerator]::Create(); $b = New-Object byte[] 48; try { $r.GetBytes($b); [Convert]::ToBase64String($b) } finally { [Array]::Clear($b, 0, 48); $r.Dispose() } }

# =====================================================================================================================
# Репетиція 5а (P1/P2): handle запущеного процесу реєструється ОДРАЗУ після Start (до відновлення env); слухач і ідентичність
# перевіряються ДО першого HTTP; очищення — завжди; невдале очищення або невідомий вихід дерева → STOP, temp із БД зберігається
# =====================================================================================================================
function Invoke-V2Rehearsal {
  param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $Backend, [Parameter(Mandatory)] [string] $DbTool, [int] $Port = 8199,
        [string] $FrontendOrigin = 'https://desktop-jtgc2sg.taild5c033.ts.net',
        [scriptblock] $PreSteps, [scriptblock] $Launcher)
  Assert-V2Exe $Py 'python'
  if (@(Get-V2Listeners @($Port)).Count) { Stop-V2 "порт $Port зайнятий" }
  $T = Join-Path $env:TEMP ("v2-rehearsal-" + [guid]::NewGuid().ToString('N')); $null = New-Item -ItemType Directory -Path $T
  $launched = New-Object System.Collections.Generic.List[object]
  $tree = $null; $out = New-Object System.Collections.Generic.List[string]; $bodyErr = $null
  if (-not $PreSteps) {
    $PreSteps = {
      $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.seed') -What 'seed (копія)'
      $out.Add("FINGERPRINT $(Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('fingerprint', "$T\integrity_v2.db"))")
      $out.Add((Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$T\integrity_v2.db", "$T\integrity_v2.bak.db", '--expect-version', '3')))
      $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.migrations', '--apply', '--confirm-verified-backup') -What 'migrations (копія)'
      $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.migrations import check_schema; from app.database import engine; check_schema(engine); from app.v2_auth import check_auth_schema; check_auth_schema(); print(''SCHEMA OK'')') -What 'schema check (копія)'
    }
  }
  if (-not $Launcher) {
    $Launcher = {
      param($list)
      $psi = New-Object Diagnostics.ProcessStartInfo
      $psi.FileName = $Py; $psi.WorkingDirectory = $Backend; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
      $psi.Arguments = (@('-E', '-s', '-X', 'utf8', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port", '--workers', '1', '--no-access-log', '--no-proxy-headers') | ForEach-Object { ConvertTo-V2Arg $_ }) -join ' '
      $p = [Diagnostics.Process]::Start($psi)
      if ($p) { $null = $p.Handle; $list.Add($p) }                               # handle збережено одразу після запуску
    }
  }
  try {
    $vars = @{ APP_ENV = 'release'; INTEGRITY_DB = "$T\integrity_v2.db"; V2_AUTH_DB = "$T\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey)
               FRONTEND_ORIGINS = $FrontendOrigin; TRUSTED_PROXIES = '127.0.0.1,::1'; INTEGRITY_ANALYTICS_DEMO = '1'
               INTEGRITY_DEMO_XROLE = $null; V2_AUTH_DEV_MAIL = $null; V2_AUTH_SECURE_COOKIE = $null }
    $null = Use-V2Env -Vars $vars -Body { & $PreSteps; & $Launcher $launched }
    if (-not $launched.Count) { Stop-V2 'uvicorn не запущено' }
    $tree = New-V2Tree -RootProcess $launched[0]
    $out.Add((Wait-V2Listener -Port $Port -Tree $tree -Addresses @('127.0.0.1')))          # P1: до першого HTTP
    $out.Add((Wait-V2Http -Url "http://127.0.0.1:$Port/api/health"))
    $out.Add((Assert-V2ListenerInTree -Port $Port -Tree $tree -Addresses @('127.0.0.1')))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/docs" -Expected 401))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/openapi.json" -Expected 401))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/redoc" -Expected 404))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/api/assessments/1/participation" -Headers @{ 'X-Role' = 'manager' } -Expected 401))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/v2/auth/logout" -Method POST -Expected 403))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/v2/auth/dev-mail/latest" -Expected 404))
    $out.Add((Assert-V2Http -Url "http://127.0.0.1:$Port/api/assessments" -Expected 200))
  } catch { $bodyErr = $_ }
  # --- очищення: завжди; лише власні handle ---
  $prior = New-Object System.Collections.Generic.List[string]
  if (-not $tree -and $launched.Count) {
    try { $tree = New-V2Tree -RootProcess $launched[0] }
    catch {
      $prior.Add("ідентичність запущеного процесу не підтверджено: $($_.Exception.Message -replace '^STOP: ', '')")
      $tree = New-Object System.Collections.Generic.List[object]
      foreach ($p in $launched) { $tree.Add([pscustomobject]@{ Pid = [int]$p.Id; StartUtcTicks = [int64](Get-V2HandleStartTicks $p); Exe = ''; CommandLine = ''; ParentPid = -1; ParentStartUtcTicks = [int64]0; Owner = ''; Handle = $p }) }
    }
  }
  $clean = @(Invoke-V2Cleanup -Tree $tree -TempDir $T -Port $Port -Prior $prior.ToArray())
  if ($bodyErr -and $clean.Count) { Stop-V2 "$($bodyErr.Exception.Message -replace '^STOP: ', ''); ОЧИЩЕННЯ: $($clean -join '; ')" }
  if ($bodyErr) { throw $bodyErr }
  if ($clean.Count) { Stop-V2 "очищення репетиції: $($clean -join '; ')" }
  $out.Add('PASS  репетиція: дерево процесів (власні handle) зупинено й завершення доведено, env відновлено, тимчасові файли видалено, порт вільний')
  $out.ToArray()
}

# --- I04, I06: БД (REV3, без змін) ----------------------------------------------------------------------------------------------
function Invoke-V2DbTool {
  param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $DbTool, [Parameter(Mandatory)] [string[]] $ArgList)
  $r = @(Invoke-V2Native -Exe $Py -ArgList (@('-E', '-s', '-I', $DbTool) + $ArgList) -Utf8 -What "v2_db_tool $($ArgList[0])")
  if (-not $r.Count) { Stop-V2 "v2_db_tool $($ArgList[0]): немає результату" }
  $r[-1]
}
function Assert-V2SyntheticDb {
  param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $DbTool, [Parameter(Mandatory)] [string] $DataDir, [Parameter(Mandatory)] [string] $ReferenceFingerprint)
  $marker = Join-Path $DataDir 'CREATED-BY-V2-INSTALL.txt'
  if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { Stop-V2 'немає маркера свіжої синтетичної БД — DEMO заборонено' }
  $fp = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('fingerprint', (Join-Path $DataDir 'integrity_v2.db'))
  if ($fp -ne $ReferenceFingerprint) { Stop-V2 "відбиток БД $fp ≠ еталону репетиції $ReferenceFingerprint — DEMO заборонено" }
  $u = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('users', (Join-Path $DataDir 'v2_auth.db'))
  if ($u -notmatch '^USERS admin=\d+$') { Stop-V2 "у v2_auth є не лише адміністратори команди: $u" }
  "PASS  синтетична БД підтверджена (маркер, відбиток $fp, $u) — INTEGRITY_ANALYTICS_DEMO=1 дозволено"
}

# =====================================================================================================================
# CLEAN INSTALL (перше встановлення на нові порожні SQLite). Не використовує механізми Upgrade/Rollback:
# Invoke-V2DbRestore, Assert-V2Restore*, Set-V2ServiceStartMode, Job Object (static P27/P28). Інструменти — з артефакту V2, не з V1.
# =====================================================================================================================
$V2ToolsSha256 = [ordered]@{ 'winsw/integrity-v2-winsw.exe' = $WinswRefSha256; 'caddy/caddy.exe' = $CaddyRefSha256 }   # вміст артефакту integrity-v2-tools
# Артефакт інструментів V2 (WinSW 2.12.0, Caddy 2.11.9): лише перевірені SHA256; збирається з джерел, підтверджених №4 (preflight / офіційний реліз)
function New-V2ToolsArtifact {
  param([Parameter(Mandatory)] [string] $WinswPath, [Parameter(Mandatory)] [string] $CaddyPath, [Parameter(Mandatory)] [string] $OutZip)
  $null = Assert-V2Winsw -Path $WinswPath -Label 'WinSW (джерело артефакту)'
  $null = Assert-V2FileHash -Path $CaddyPath -Sha256 $CaddyRefSha256 -Label 'caddy.exe (джерело артефакту)'
  if (Test-Path -LiteralPath $OutZip) { Stop-V2 "артефакт $OutZip уже існує" }
  Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
  $z = [IO.Compression.ZipFile]::Open($OutZip, 'Create')
  try {
    $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $WinswPath, 'winsw/integrity-v2-winsw.exe', 'Optimal')
    $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $CaddyPath, 'caddy/caddy.exe', 'Optimal')
  } finally { $z.Dispose() }
  "PASS  артефакт інструментів: $OutZip (SHA256 $((Get-FileHash -LiteralPath $OutZip -Algorithm SHA256).Hash.ToLower()))"
}
# Розпакування артефакту: рівно очікувані записи, без шляхів поза каталогом, SHA256 кожного = еталону; WinSW — ще й версія 2.12.0
function Expand-V2Tools {
  param([Parameter(Mandatory)] [string] $ToolsZip, [Parameter(Mandatory)] [string] $Destination, [System.Collections.IDictionary] $ExpectedSha256 = $V2ToolsSha256)
  if (-not (Test-Path -LiteralPath $ToolsZip -PathType Leaf)) { Stop-V2 "артефакту інструментів немає: $ToolsZip" }
  if (Test-Path -LiteralPath $Destination) { Stop-V2 "каталог інструментів уже існує: $Destination" }
  Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
  $z = [IO.Compression.ZipFile]::OpenRead($ToolsZip)
  try {
    $names = @($z.Entries | Where-Object { $_.FullName -notmatch '/$' } | ForEach-Object FullName | Sort-Object)
    $want = @($ExpectedSha256.Keys | Sort-Object)
    if (($names -join '|') -ne ($want -join '|')) { Stop-V2 "склад артефакту ≠ очікуваному: $($names -join ', ')" }
    $null = New-Item -ItemType Directory -Path $Destination
    foreach ($e in $z.Entries) {
      if ($e.FullName -match '/$') { continue }
      $dst = [IO.Path]::GetFullPath((Join-Path $Destination $e.FullName))
      if (-not $dst.StartsWith([IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "запис поза каталогом: $($e.FullName)" }
      $null = New-Item -ItemType Directory -Path (Split-Path $dst) -Force
      [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dst)
    }
  } finally { $z.Dispose() }
  foreach ($k in $ExpectedSha256.Keys) {
    $p = Join-Path $Destination $k
    if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() -ne $ExpectedSha256[$k]) { Stop-V2 "SHA256 $k ≠ еталону" }
  }
  "PASS  інструменти V2: $(($ExpectedSha256.Keys | ForEach-Object { "$_ = $($ExpectedSha256[$_].Substring(0, 8))…" }) -join '; ')"
}
# Готовність даних до старту backend: незавершена/невдала ініціалізація або відновлення → STOP;
# потрібен ПОЗИТИВНИЙ маркер CLEAN-INIT-OK (Clean Install) або RESTORE-OK (відкат). Незавершені БД не використовуються.
function Assert-V2DataReady {
  param([Parameter(Mandatory)] [string] $DataDir)
  if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) { Stop-V2 "старт backend заборонено: немає каталогу даних $DataDir" }
  $null = Assert-V2NoRestoreBlock -DataDir $DataDir
  $all = @(Get-ChildItem -LiteralPath $DataDir -File -Force | ForEach-Object Name)
  $bad = @($all | Where-Object { $_ -match '^CLEAN-INIT-' -and $_ -notmatch '^CLEAN-INIT-OK-' })     # CI-01: FAILED / IN-PROGRESS / REVOKED / невідомий — незалежно від наявності старого OK
  $root = Split-Path -Parent ([IO.Path]::GetFullPath($DataDir))
  if ($root -and (Test-Path -LiteralPath $root -PathType Container)) { $bad += @(Get-ChildItem -LiteralPath $root -File -Force -Filter 'CLEAN-INSTALL-FAILED-*' | ForEach-Object Name) }
  if ($bad.Count) { Stop-V2 "старт backend заборонено: ініціалізація БД не завершена або невдала ($($bad -join ', ')) — Clean Install перервати (Invoke-V2CleanInstallAbort)" }
  if (-not @($all | Where-Object { $_ -match '^(CLEAN-INIT-OK|RESTORE-OK)-' }).Count) { Stop-V2 'старт backend заборонено: немає підтвердження ініціалізації БД (CLEAN-INIT-OK / RESTORE-OK)' }
  'PASS  дані готові: ініціалізацію підтверджено маркером'
}
function Set-V2InitMarker {
  param([string] $DataDir, [string] $From, [ValidateSet('OK', 'FAILED')] [string] $To, [string] $Note = '')
  $ts = ($From -replace '^CLEAN-INIT-IN-PROGRESS-', '' -replace '\.txt$', '')
  $new = "CLEAN-INIT-$To-$ts.txt"
  Rename-Item -LiteralPath (Join-Path $DataDir $From) -NewName $new -ErrorAction Stop
  if ($Note) { [IO.File]::AppendAllText((Join-Path $DataDir $new), "$Note`n") }
  $new
}
# Крок 4.5 (до bootstrap): нові БД лише в ПОРОЖНЬОМУ data\ — seed → verify → відбиток → backup → migrations → схема → строгий auth-schema
function Initialize-V2CleanDatabases {
  param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $Backend, [Parameter(Mandatory)] [string] $DbTool,
        [Parameter(Mandatory)] [string] $DataDir, [Parameter(Mandatory)] [string] $BackupDir, [string] $ReferenceFingerprint)
  if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) { Stop-V2 "немає каталогу даних $DataDir" }
  $pre = @(Get-ChildItem -LiteralPath $DataDir -Force)
  if ($pre.Count) { Stop-V2 "Clean Install лише на порожньому data\: знайдено $($pre.Count) об'єкт(и) ($(($pre | Select-Object -First 5 | ForEach-Object Name) -join ', ')) — наявні БД не використовуються" }
  if (-not (Test-Path -LiteralPath $BackupDir -PathType Container)) { Stop-V2 "немає каталогу копій $BackupDir" }
  $ts = Get-Date -Format yyyyMMdd-HHmmss
  $mk = "CLEAN-INIT-IN-PROGRESS-$ts.txt"
  [IO.File]::WriteAllText((Join-Path $DataDir $mk), "clean init started $ts`n", (New-Object Text.UTF8Encoding $false))
  $out = New-Object System.Collections.Generic.List[string]
  try {
    Set-Content -LiteralPath (Join-Path $DataDir 'CREATED-BY-V2-INSTALL.txt') -Value "created $(Get-Date -Format s) by app.seed (package dde86e6)" -Encoding UTF8
    $dbI = Join-Path $DataDir 'integrity_v2.db'; $dbA = Join-Path $DataDir 'v2_auth.db'   # не $A/$I: імена змінних PowerShell нечутливі до регістру
    $r = @(Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = $dbI; V2_AUTH_DB = $dbA; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
      $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.seed') -What 'seed (Clean Install)'
      Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('verify', $dbI, '--expect-version', '3')
      $fp = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('fingerprint', $dbI)
      if ($ReferenceFingerprint -and $fp -ne $ReferenceFingerprint) { Stop-V2 'відбиток нової БД ≠ репетиції 5а' }
      Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', $dbI, (Join-Path $BackupDir "integrity_v2-pre-migration-$ts.db"), '--expect-version', '3')
      $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.migrations', '--apply', '--confirm-verified-backup') -What 'migrations (Clean Install)'
      @(Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.migrations import check_schema; from app.database import engine; check_schema(engine); from app.v2_auth import check_auth_schema; check_auth_schema(); print(''SCHEMA OK'')') -What 'schema (Clean Install)')[-1]
    })
    if ($r[-1] -ne 'SCHEMA OK') { Stop-V2 "перевірка схеми нових БД: $($r[-1])" }
    $a = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('auth-schema', $dbA)
    if ($a -notlike 'AUTH SCHEMA OK*') { Stop-V2 "нова v2_auth.db не пройшла строгу перевірку схеми: $a" }
    foreach ($l in $r) { $out.Add("$l") }; $out.Add("PASS  нова v2_auth.db: $a")
  } catch {
    $why = $_.Exception.Message -replace '^STOP: ', ''
    try { $null = Set-V2InitMarker -DataDir $DataDir -From $mk -To FAILED -Note "причина: $why" } catch { }
    Stop-V2 "CLEAN INIT НЕВДАЛИЙ: $why; маркер CLEAN-INIT-FAILED блокує старт backend; нові БД не використовуються — Invoke-V2CleanInstallAbort"
  }
  $out.Add("PASS  етап ініціалізації БД (до bootstrap) — маркер $mk")
  $out.ToArray()
}
# Крок 4.5 (після bootstrap адміністратора): строгий auth-schema робочої БД і ФІНАЛЬНОЇ копії, DEMO-умова, початкові копії → CLEAN-INIT-OK
function Complete-V2CleanDatabases {
  param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $DbTool, [Parameter(Mandatory)] [string] $DataDir,
        [Parameter(Mandatory)] [string] $BackupDir, [Parameter(Mandatory)] [string] $ReferenceFingerprint)
  $mk = @(Get-ChildItem -LiteralPath $DataDir -File -Filter 'CLEAN-INIT-*.txt' | ForEach-Object Name)
  if ($mk.Count -ne 1 -or $mk[0] -notmatch '^CLEAN-INIT-IN-PROGRESS-') { Stop-V2 "очікується рівно один маркер CLEAN-INIT-IN-PROGRESS: $($mk -join ', ')" }
  $out = New-Object System.Collections.Generic.List[string]
  try {
    $dbA = Join-Path $DataDir 'v2_auth.db'; $dbI = Join-Path $DataDir 'integrity_v2.db'   # не $A/$I: імена змінних PowerShell нечутливі до регістру
    $a = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('auth-schema', $dbA)
    if ($a -notlike 'AUTH SCHEMA OK*') { Stop-V2 "v2_auth.db після bootstrap не пройшла строгу перевірку схеми: $a" }
    $u = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('users', $dbA)
    if ($u -notmatch '\badmin=1\b') { Stop-V2 "очікується рівно один адміністратор: $u" }
    $out.Add((Assert-V2SyntheticDb -Py $Py -DbTool $DbTool -DataDir $DataDir -ReferenceFingerprint $ReferenceFingerprint))
    $ts = ($mk[0] -replace '^CLEAN-INIT-IN-PROGRESS-', '' -replace '\.txt$', '')
    $bi = Join-Path $BackupDir "integrity_v2-initial-$ts.db"; $ba = Join-Path $BackupDir "v2_auth-initial-$ts.db"
    $out.Add((Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', $dbI, $bi, '--expect-version', '3')))
    $out.Add((Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', $dbA, $ba, '--expect-version', '1')))
    $ab = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('auth-schema', $ba)
    if ($ab -notlike 'AUTH SCHEMA OK*') { Stop-V2 "фінальна копія v2_auth не пройшла строгу перевірку схеми: $ab" }
    $sums = foreach ($f in $bi, $ba) { '{0}  {1}' -f (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower(), (Split-Path $f -Leaf) }
    [IO.File]::AppendAllText((Join-Path $BackupDir 'SHA256SUMS.txt'), (($sums -join "`n") + "`n"))
    $out.Add("PASS  v2_auth.db: $a; $u; фінальна копія: $ab")
  } catch {
    $why = $_.Exception.Message -replace '^STOP: ', ''
    try { $null = Set-V2InitMarker -DataDir $DataDir -From $mk[0] -To FAILED -Note "причина: $why" } catch { }
    Stop-V2 "CLEAN INIT НЕВДАЛИЙ (після bootstrap): $why; маркер CLEAN-INIT-FAILED блокує старт backend — Invoke-V2CleanInstallAbort"
  }
  $out.Add("PASS  Clean Install: БД ініціалізовано — маркер $(Set-V2InitMarker -DataDir $DataDir -From $mk[0] -To OK)")
  $out.ToArray()
}
# Переривання часткового Clean Install: лише об'єкти V2. Служби V2 зупиняються (доказ tree-only) і видаляються; корінь V2
# перейменовується на <корінь>-abandoned-<ts> (докази зберігаються, БД ніколи не використовуються повторно). Будь-яка
# недоведеність (служба лишилась, процес не завершився) → STOP, корінь НЕ перейменовується — рішення №5.
# CI-01: збій Clean Install ПІСЛЯ створення кореня (зокрема після CLEAN-INIT-OK на 4.6 / 4.7 / 5) → READY інвалідується fail-closed:
#   (1) маркер CLEAN-INIT-FAILED-INSTALL у data\ (блокує старт незалежно від старого OK); (2) CLEAN-INIT-OK → CLEAN-INIT-REVOKED;
#   (3) маркер CLEAN-INSTALL-FAILED у корені; (4) зупинка лише служб V2; (5) start type служб V2 → Disabled (ручний sc start теж неможливий).
# БД і копії НЕ видаляються й не змінюються; resume неможливий (повторний Clean Install лише після свідомого -Abort).
function Invoke-V2CleanInstallFailClosed {
  param([Parameter(Mandatory)] [string] $Reason, [string[]] $OwnedServices = @())
  $out = New-Object System.Collections.Generic.List[string]
  $problems = New-Object System.Collections.Generic.List[string]
  $ts = Get-Date -Format yyyyMMdd-HHmmss-fff
  $dataDir = Join-Path $V2Root 'data'
  $enc = New-Object Text.UTF8Encoding $false
  try {                                                                           # (1) спершу блокуючий маркер — він діє, навіть якщо подальші кроки не вдадуться
    if (-not (Test-Path -LiteralPath $dataDir -PathType Container)) { $null = New-Item -ItemType Directory -Path $dataDir -ErrorAction Stop }
    [IO.File]::WriteAllText((Join-Path $dataDir "CLEAN-INIT-FAILED-INSTALL-$ts.txt"), "збій Clean Install $ts`nпричина: $Reason`n", $enc)
    $out.Add("PASS  READY інвалідовано: CLEAN-INIT-FAILED-INSTALL-$ts")
  } catch { $problems.Add("маркер CLEAN-INIT-FAILED-INSTALL не записано: $($_.Exception.Message)") }
  try {                                                                           # (2) позитивний маркер відкликається
    foreach ($ok in @(Get-ChildItem -LiteralPath $dataDir -File -Force -Filter 'CLEAN-INIT-OK-*' -ErrorAction Stop)) {
      Rename-Item -LiteralPath $ok.FullName -NewName ($ok.Name -replace '^CLEAN-INIT-OK-', 'CLEAN-INIT-REVOKED-') -ErrorAction Stop
      $out.Add("PASS  $($ok.Name) відкликано")
    }
  } catch { $problems.Add("CLEAN-INIT-OK не відкликано: $($_.Exception.Message)") }
  try { [IO.File]::WriteAllText((Join-Path $V2Root "CLEAN-INSTALL-FAILED-$ts.txt"), "причина: $Reason`n", $enc) }    # (3)
  catch { $problems.Add("маркер CLEAN-INSTALL-FAILED не записано: $($_.Exception.Message)") }
  foreach ($n in 'integrity-v2-caddy', 'integrity-v2-backend') {                 # (4)+(5) лише служби V2
    $svc = Get-V2Service $n
    if (-not $svc) { $out.Add("INFO  $n не встановлено"); continue }
    if ($OwnedServices -notcontains $n) { $problems.Add("${n}: служба існує, але цей запуск не довів її створення — stop/disable заборонено"); continue }
    $svcPath = $svc.PathName.Trim().Trim('"')
    if ($svcPath -ne $V2Services[$n].Exe) { $problems.Add("${n}: PathName змінився після підтвердження ownership — stop/disable заборонено"); continue }
    try { $out.Add((Stop-V2Service -Name $n)) } catch { $problems.Add("$n не зупинено: $($_.Exception.Message -replace '^STOP: ', '')") }
    try { Set-V2ServiceStartMode -Name $n -Mode Disabled; $out.Add("PASS  $n → Disabled") } catch { $problems.Add("${n}: Disabled не підтверджено: $($_.Exception.Message -replace '^STOP: ', '')") }
  }
  try { $null = Assert-V2DataReady -DataDir $dataDir; $problems.Add('Assert-V2DataReady після інвалідації досі PASS') }
  catch { $out.Add('PASS  старт backend заблоковано (Assert-V2DataReady → STOP)') }
  if ($problems.Count) { Stop-V2 "FAIL-CLOSED НЕ ЗАВЕРШЕНО: $($problems -join '; ') — служби V2 не запускати; рішення №5" }
  $out.ToArray()
}
# C3 (№4): preflight Clean Install — порти V2 вільні ДО будь-якого запису (лише читання; чужі слухачі не зупиняються, ACL/порти не змінюються)
# C3 (№4): цільові Windows (збірка = серверу з read-only preflight), Windows PowerShell 5.1 x64, вільне місце — до будь-якого запису
function Assert-V2HostPreflight {
  param([Parameter(Mandatory)] [int] $ExpectedWindowsBuild, [long] $MinFreeBytes = 2GB)
  $h = Get-V2HostInfo
  $bad = New-Object System.Collections.Generic.List[string]
  if ($h.PSVersion -ne '5.1' -or $h.PSEdition -ne 'Desktop') { $bad.Add("PowerShell $($h.PSVersion) $($h.PSEdition) ≠ Windows PowerShell 5.1") }
  if (-not $h.Is64) { $bad.Add('не x64 ОС/процес') }
  if ([int]$h.Build -ne $ExpectedWindowsBuild) { $bad.Add("збірка Windows $($h.Build) ≠ цільовій $ExpectedWindowsBuild") }
  if ([long]$h.FreeBytes -lt $MinFreeBytes) { $bad.Add(("вільно {0:N1} ГБ на {1} < {2:N1} ГБ" -f ($h.FreeBytes / 1GB), $h.Drive, ($MinFreeBytes / 1GB))) }
  if ($bad.Count) { Stop-V2 "preflight хоста: $($bad -join '; ')" }
  "PASS  хост: Windows build $($h.Build), PowerShell $($h.PSVersion) $($h.PSEdition) x64, вільно $([math]::Round($h.FreeBytes / 1GB, 1)) ГБ на $($h.Drive)"
}
function Assert-V2PortsFree {
  param([int[]] $Tcp = @(80, 443, 8100, 8199), [int[]] $Udp = @(443))
  $busy = New-Object System.Collections.Generic.List[string]
  foreach ($l in @(Get-V2Listeners -Ports $Tcp)) { $busy.Add("TCP $($l.LocalAddress):$($l.LocalPort) (PID $($l.OwningProcess))") }
  foreach ($u in @(Get-V2UdpEndpoints -Ports $Udp)) { $busy.Add("UDP $($u.LocalAddress):$($u.LocalPort) (PID $($u.OwningProcess))") }
  if ($busy.Count) { Stop-V2 "порти V2 зайняті: $($busy -join '; ') — Clean Install неможливий; конфлікт вирішує №5 (порти/ACL не змінюються)" }
  "PASS  порти вільні: TCP $($Tcp -join ','); UDP $($Udp -join ',')"
}
function Get-V2TargetDns([string]$HostName) { @([Net.Dns]::GetHostAddresses($HostName) | ForEach-Object ToString) }
function Get-V2TargetLocalIps { @(Get-NetIPAddress -ErrorAction Stop | ForEach-Object IPAddress) }
function Assert-V2TargetIdentity {
  param([Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string[]]$Addresses, [switch]$TestHost)
  $prodHost = 'desktop-jtgc2sg.taild5c033.ts.net'
  $prodAddresses = @('100.111.221.74')
  $reservedProdAddresses = @('100.111.221.74', 'fd7a:115c:a1e0::ef01:dddc')
  if ($HostName -notmatch '^[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$' -or -not $Addresses.Count -or @($Addresses | Sort-Object -Unique).Count -ne $Addresses.Count) { Stop-V2 'target DNS/IP: некоректний host або адреси' }
  if ($TestHost -and ($HostName -ieq $prodHost -or @($Addresses | Where-Object { $reservedProdAddresses -contains $_ }).Count)) { Stop-V2 'test host не може використовувати production DNS/IP' }
  if ($TestHost -and $env:COMPUTERNAME -ieq 'DESKTOP-JTGC2SG') { Stop-V2 'production машина не може бути test host' }
  if (-not $TestHost -and ($HostName -ine $prodHost -or (@($Addresses | Sort-Object) -join ',') -ne (@($prodAddresses | Sort-Object) -join ','))) { Stop-V2 'production target config відрізняється від закріпленого — потрібне окреме рішення' }
  if ($HostName.Split('.')[0] -ine $env:COMPUTERNAME) { Stop-V2 "target hostname $HostName ≠ локальному $env:COMPUTERNAME" }
  try {
    $dns = @(Get-V2TargetDns $HostName)
    $local = @(Get-V2TargetLocalIps)
  } catch { Stop-V2 "target DNS/IP: перевірка неможлива: $($_.Exception.Message)" }
  $approved = New-Object System.Collections.Generic.List[string]
  foreach ($address in $Addresses) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($address, [ref]$parsed) -or $local -notcontains $parsed.ToString()) { Stop-V2 "target DNS/IP: $address не підтверджена одночасно DNS і локальним інтерфейсом" }
    $approved.Add($parsed.ToString())
  }
  if (@($approved | Sort-Object -Unique).Count -ne $approved.Count) { Stop-V2 'target DNS/IP: дублікати схвалених адрес' }
  $resolved = New-Object System.Collections.Generic.List[string]
  foreach ($address in $dns) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($address, [ref]$parsed)) { Stop-V2 "target DNS/IP: недійсна DNS-адреса $address" }
    $resolved.Add($parsed.ToString())
  }
  if ($TestHost -and @($resolved | Where-Object { $reservedProdAddresses -contains $_ }).Count) { Stop-V2 'target DNS/IP: production IP у DNS тестового хоста' }
  if (@(Compare-Object -ReferenceObject @($approved | Sort-Object -Unique) -DifferenceObject @($resolved | Sort-Object -Unique)).Count) { Stop-V2 'target DNS/IP: фактичний набір DNS-адрес не дорівнює схваленому' }
  "PASS  target $HostName; DNS/local bind $($Addresses -join ',')"
}
function Assert-V2PinnedHttps {
  param([Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string[]]$Addresses,
        [Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][int]$Expected,
        [hashtable]$Headers = @{}, [ValidateSet('GET','POST')][string]$Method = 'GET',
        [ValidateRange(1,65535)][int]$Port = 443, [string]$CaFile, [switch]$TestHost)
  if ($Path -notmatch '^/[a-zA-Z0-9/_\.\-]*$') { Stop-V2 'HTTPS path поза дозволеною формою' }
  $null = Assert-V2TargetIdentity -HostName $HostName -Addresses $Addresses -TestHost:$TestHost
  $ip = $null
  if (-not [Net.IPAddress]::TryParse($Addresses[0], [ref]$ip)) { Stop-V2 'HTTPS endpoint: адреса недійсна' }
  $address = if ($ip.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetworkV6) { "[$($ip.ToString())]" } else { $ip.ToString() }
  $authority = if ($Port -eq 443) { $HostName } else { "${HostName}:$Port" }
  $url = "https://$authority$Path"
  # --disable first: no user curlrc; --resolve pins the socket, while URL host retains SNI and certificate hostname verification.
  $args = @('--disable','--silent','--show-error','--output','NUL','--write-out','%{http_code}','--max-time','20',
            '--noproxy','*','--resolve',"${HostName}:${Port}:$address",'--request',$Method)
  if ($CaFile) { $args += @('--cacert',$CaFile) }  # synthetic loopback TLS test only; installer never supplies this
  foreach ($key in @($Headers.Keys | Sort-Object)) { $args += @('--header',"${key}: $($Headers[$key])") }
  $args += $url
  try { $status = @(Invoke-V2Native -Exe "$env:SystemRoot\System32\curl.exe" -ArgList $args -What "pinned HTTPS $HostName")[-1] }
  catch { Stop-V2 "pinned HTTPS ${HostName}/${address}: $($_.Exception.Message -replace '^STOP: ', '')" }
  if ($status -notmatch '^[0-9]{3}$' -or [int]$status -ne $Expected) { Stop-V2 "$Method $url pinned to $address → $status, очікується $Expected" }
  "PASS  $Method $url pinned to $address → $status"
}
function New-V2TargetConfig {
  param([Parameter(Mandatory)][string]$CaddySource, [Parameter(Mandatory)][string]$BackendSource,
        [Parameter(Mandatory)][string]$Destination, [Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string[]]$Addresses,
        [switch]$UseFileTls)
  $prodHost = 'desktop-jtgc2sg.taild5c033.ts.net'
  $prodBind = 'bind 100.111.221.74 [fd7a:115c:a1e0::ef01:dddc]'
  # I2 (hardening): Caddyfile — UTF-8 без BOM; невалідний UTF-8 → виняток (раніше cp1251 давав подвійне кодування коментарів)
  $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
  $caddyBytes = [IO.File]::ReadAllBytes($CaddySource)
  if ($caddyBytes.Length -ge 3 -and $caddyBytes[0] -eq 0xEF -and $caddyBytes[1] -eq 0xBB -and $caddyBytes[2] -eq 0xBF) { Stop-V2 'target config: Caddyfile має бути UTF-8 без BOM' }
  try { $caddy = $strictUtf8.GetString($caddyBytes) } catch { Stop-V2 "target config: Caddyfile не є коректним UTF-8: $($_.Exception.Message)" }
  $xml = [IO.File]::ReadAllText($BackendSource, [Text.Encoding]::UTF8)
  if ([regex]::Matches($caddy, [regex]::Escape($prodHost)).Count -ne 1 -or [regex]::Matches($caddy, [regex]::Escape($prodBind)).Count -ne 1 -or
      [regex]::Matches($xml, 'name="FRONTEND_ORIGINS" value="https://' + [regex]::Escape($prodHost) + '"').Count -ne 1) { Stop-V2 'target config: production template не відповідає закріпленій формі' }
  $bind = 'bind ' + (($Addresses | ForEach-Object { if ($_ -match ':') { "[$_]" } else { $_ } }) -join ' ')
  $caddy = $caddy.Replace($prodHost, $HostName).Replace($prodBind, $bind)
  if ($UseFileTls) {
    if ([regex]::Matches($caddy, '(?m)^\s*auto_https disable_redirects\s*$').Count -ne 1 -or
        [regex]::Matches($caddy, [regex]::Escape($bind)).Count -ne 1 -or
        $caddy -match '(?m)^\s*tls\s') { Stop-V2 'Unexpected baseline Caddy TLS configuration' }
    $caddy = $caddy.Replace('auto_https disable_redirects', 'auto_https off').Replace(
      $bind, "$bind`n`ttls C:/srv/integrity-v2/caddy/tls/site.crt C:/srv/integrity-v2/caddy/tls/site.key")
  }
  $xml = $xml.Replace('name="FRONTEND_ORIGINS" value="https://' + $prodHost + '"', 'name="FRONTEND_ORIGINS" value="https://' + $HostName + '"')
  if (Test-Path -LiteralPath $Destination) { Stop-V2 'target config: staging каталог уже існує' }
  $null = New-Item -ItemType Directory -Path $Destination -ErrorAction Stop
  $cf = Join-Path $Destination 'Caddyfile'; $xf = Join-Path $Destination 'integrity-v2-backend.xml'
  [IO.File]::WriteAllText($cf, $caddy, $strictUtf8)
  [IO.File]::WriteAllText($xf, $xml, (New-Object Text.UTF8Encoding $false))
  $manifest = @("target=$HostName", "bind=$($Addresses -join ',')", "Caddyfile=$((Get-FileHash -LiteralPath $cf -Algorithm SHA256).Hash.ToLower())", "integrity-v2-backend.xml=$((Get-FileHash -LiteralPath $xf -Algorithm SHA256).Hash.ToLower())")
  [IO.File]::WriteAllLines((Join-Path $Destination 'TARGET-CONFIG-MANIFEST.txt'), [string[]]$manifest, (New-Object Text.UTF8Encoding $false))
  "PASS  target config $Destination; $($manifest -join '; ')"
}
function Assert-V2TargetConfigManifest {
  param([Parameter(Mandatory)][string]$Directory, [Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string[]]$Addresses)
  $lines = @(Get-Content -LiteralPath (Join-Path $Directory 'TARGET-CONFIG-MANIFEST.txt') -ErrorAction Stop)
  if ($lines.Count -ne 4 -or $lines[0] -ne "target=$HostName" -or $lines[1] -ne "bind=$($Addresses -join ',')") { Stop-V2 'target config manifest: target/bind невірний' }
  foreach ($name in 'Caddyfile','integrity-v2-backend.xml') {
    $entry = @($lines | Where-Object { $_ -like "$name=*" })
    if ($entry.Count -ne 1) { Stop-V2 "target config manifest: немає $name" }
    $expected = $entry[0].Substring($name.Length + 1)
    if ($expected -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath (Join-Path $Directory $name) -Algorithm SHA256).Hash.ToLower() -ne $expected) { Stop-V2 "target config manifest: SHA256 $name невірний" }
  }
  'PASS  target config manifest: host/bind і SHA256 файлів підтверджено'
}
function Assert-V2TlsDirectory {
  param([Parameter(Mandatory)][string]$Path, [string]$ServiceSid)
  Assert-V2NoReparseChain $Path
  $dir = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
  if (-not $dir.PSIsContainer -or $dir.FullName -ne $Path) { Stop-V2 'Unexpected V2 TLS directory' }
  $entries = @(Get-ChildItem -LiteralPath $Path -Force)
  if ($entries.Count -ne 2) { Stop-V2 'V2 TLS directory must contain exactly two files' }
  $dirRights = if ($ServiceSid) { 'RX' } else { $null }
  $fileRights = if ($ServiceSid) { 'R' } else { $null }
  # The directory ACE is direct. Files have independent, read-only Caddy ACEs.
  $dirAcl = Get-V2Acl $Path
  $null = Assert-V2AclExact -Acl $dirAcl -ServiceSid $ServiceSid -ServiceRights $dirRights -Label $Path
  foreach ($scope in 'ChildContainer','ChildObject') {
    $map = Get-V2AccessMap -Acl $dirAcl -Scope $scope
    if ($map.Count -ne 2 -or ($map[$SidAdmins] -band 0x1F01FF) -ne $V2Rights.F -or
        ($map[$SidSystem] -band 0x1F01FF) -ne $V2Rights.F) { Stop-V2 'V2 TLS directory must only inherit SYSTEM and Administrators rights to children' }
  }
  foreach ($name in 'site.crt','site.key') {
    $file = Get-Item -LiteralPath (Join-Path $Path $name) -Force -ErrorAction Stop
    if ($file.PSIsContainer -or -not $file.Length -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Stop-V2 'Unexpected V2 TLS file' }
    $null = Assert-V2AclExact -Acl (Get-V2Acl $file.FullName) -ServiceSid $ServiceSid -ServiceRights $fileRights -Label $file.FullName
  }
  'PASS  V2 TLS directory and certificate/key ACL'
}
function Assert-V2StagedTlsPair {
  param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$CertificateSha256)
  if ($Path -notmatch '^C:\\srv\\V2-tls-staging-\d{8}-\d{6}$' -or $CertificateSha256 -notmatch '^[a-fA-F0-9]{64}$') {
    Stop-V2 'Unexpected TLS staging path or certificate SHA256'
  }
  Assert-V2NoReparseChain $Path
  $dir = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
  if (-not $dir.PSIsContainer -or $dir.FullName -ne $Path) { Stop-V2 'Missing TLS staging directory' }
  $acl = Get-V2Acl $Path
  if (-not $acl.AreAccessRulesProtected) { Stop-V2 'TLS staging ACL must be protected' }
  $null = Assert-V2AclExact -Acl $acl -IsContainer -Label $Path
  foreach ($name in 'site.crt','site.key') {
    $file = Get-Item -LiteralPath (Join-Path $Path $name) -Force -ErrorAction Stop
    if ($file.PSIsContainer -or -not $file.Length -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Stop-V2 'Unexpected TLS staging file' }
    $null = Assert-V2AclExact -Acl (Get-V2Acl $file.FullName) -Label $file.FullName
  }
  $null = Assert-V2FileHash -Path (Join-Path $Path 'site.crt') -Sha256 $CertificateSha256 -Label 'Tailscale certificate'
  'PASS  protected TLS staging pair and certificate SHA256'
}
function Invoke-V2CleanInstallAbort {
  param([Parameter(Mandatory)] [string] $Reason, $Baseline)
  if ($V2Services['integrity-v2-backend'].Job) { Stop-V2 'Clean Install не використовує Job Object ($V2Services.Job має бути $null)' }
  # Abort is only for a failed attempt. Prove that state before touching SCM;
  # a successful install or an unrelated same-name service must remain intact.
  if (-not (Test-Path -LiteralPath $V2Root -PathType Container)) { Stop-V2 'Abort: немає кореня невдалого встановлення' }
  $dataDir = Join-Path $V2Root 'data'
  if (-not (Test-Path -LiteralPath $dataDir -PathType Container) -or
      -not @(Get-ChildItem -LiteralPath $V2Root -File -Force -Filter 'CLEAN-INSTALL-FAILED-*').Count -or
      -not @(Get-ChildItem -LiteralPath $dataDir -File -Force -Filter 'CLEAN-INIT-FAILED-INSTALL-*').Count -or
      @(Get-ChildItem -LiteralPath $dataDir -File -Force -Filter 'CLEAN-INIT-OK-*').Count) {
    Stop-V2 'Abort: немає маркера невдалого встановлення або READY досі чинний'
  }
  foreach ($n in 'integrity-v2-caddy', 'integrity-v2-backend') {
    $svc = Get-V2Service $n
    if (-not $svc) { continue }
    $path = $svc.PathName.Trim().Trim('"')
    if ($path -ne $V2Services[$n].Exe) { Stop-V2 "Abort: PathName $n не відповідає власному WinSW: $($svc.PathName)" }
  }
  $out = New-Object System.Collections.Generic.List[string]
  $problems = New-Object System.Collections.Generic.List[string]
  foreach ($n in 'integrity-v2-caddy', 'integrity-v2-backend') {
    if (-not (Get-V2Service $n)) { $out.Add("INFO  $n не встановлено"); continue }
    try { $out.Add((Stop-V2Service -Name $n)) } catch { $problems.Add("$n не зупинено: $($_.Exception.Message -replace '^STOP: ', '')"); continue }
    try { $null = Invoke-V2Native -Exe $V2Services[$n].Exe -ArgList @('uninstall') -What "WinSW uninstall $n" } catch { $problems.Add("$n uninstall: $($_.Exception.Message -replace '^STOP: ', '')") }
    if (Get-V2Service $n) { $problems.Add("$n досі встановлено") } else { $out.Add("PASS  $n видалено") }
  }
  if ($problems.Count) { Stop-V2 "ПЕРЕРИВАННЯ НЕ ЗАВЕРШЕНО: $($problems -join '; ') — корінь V2 не перейменовано; рішення №5" }
  if (Test-Path -LiteralPath $V2Root) {
    $ts = Get-Date -Format yyyyMMdd-HHmmss
    $dataDir = Join-Path $V2Root 'data'
    if (Test-Path -LiteralPath $dataDir) { [IO.File]::WriteAllText((Join-Path $dataDir "CLEAN-INIT-FAILED-ABANDONED-$ts.txt"), "abandoned $ts`nпричина: $Reason`n", (New-Object Text.UTF8Encoding $false)) }
    $leaf = (Split-Path $V2Root -Leaf) + "-abandoned-$ts"
    Rename-Item -LiteralPath $V2Root -NewName $leaf -ErrorAction Stop
    $out.Add("PASS  корінь V2 перейменовано: $leaf (докази збережено; БД не використовуються)")
  }
  if ($Baseline) { $out.Add((Assert-V1Unchanged -Baseline $Baseline)) }
  $out.ToArray()
}
