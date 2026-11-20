# Invoke-V2DailyBackup.ps1 — щоденна резервна копія робочих БД V2 (завдання Integrity-V2-DB-Backup, SYSTEM, 03:30).
# Самодостатній (лише stdlib-python і v2_db_tool.py поруч, SHA256 якого закріплено в аргументах завдання). Для кожного запуску:
#   backups\daily\<yyyyMMdd-HHmmss>\ (ACL лише Administrators/SYSTEM, без успадкування) ← v2_db_tool backup обох БД
#   (SQLite backup API: узгоджений знімок без зупинки служби) з тестом відновлення і строгою схемою, якщо версія відома;
#   SHA256SUMS.txt і DAILY-BACKUP.json (лише метадані: версії, кількість рядків, SHA256 — без вмісту БД);
#   ротація: лишаються останні -Keep (14) запусків цього завдання (лише каталоги з DAILY-BACKUP.json цього формату).
# Журнал: backups\daily\daily-backup.log (рядок на запуск). Код виходу 0 — PASS; 1 — збій (каталог невдалого запуску лишається
# з DAILY-BACKUP.json Status=FAILED і не враховується як вдала копія при ротації).
[CmdletBinding()]
param(
  [string] $Root = 'C:\srv\integrity-v2',
  [string] $Python = 'C:\Program Files\Python313\python.exe',
  [string] $DbTool,                              # за замовчуванням v2_db_tool.py поруч зі скриптом
  [Parameter(Mandatory)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string] $ExpectedToolSha256,
  [ValidateRange(2, 90)] [int] $Keep = 14,
  [switch] $Simulate                             # ЛИШЕ тести: -Root у %TEMP%, без SYSTEM/ACL
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
if (-not $DbTool) { $DbTool = Join-Path $PSScriptRoot 'v2_db_tool.py' }
$stamp = Get-Date -Format yyyyMMdd-HHmmss
$daily = Join-Path $Root 'backups\daily'
$log = Join-Path $daily 'daily-backup.log'
$state = [ordered]@{ Schema = 'integrity-v2-daily-backup/1'; Stamp = $stamp; Status = 'RUNNING'; Databases = @(); Rotated = @(); Error = $null }
$run = $null
function Invoke-Tool([string[]]$A) {
  $psi = New-Object Diagnostics.ProcessStartInfo $Python, ((@('-I', '-B', $DbTool) + $A | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $psi.EnvironmentVariables['TEMP'] = $run; $psi.EnvironmentVariables['TMP'] = $run
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(1800000)) { $p.Kill(); throw "v2_db_tool $($A[0]): тайм-аут" }
  $lines = @($o.Result -split "`r?`n" | Where-Object { $_ })
  if ($p.ExitCode -ne 0) { throw "v2_db_tool $($A[0]) → код $($p.ExitCode): $(($e.Result -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 1))" }
  $lines
}
try {
  $full = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  if ($Simulate) {
    $tb = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    if (-not $full.StartsWith($tb, [StringComparison]::OrdinalIgnoreCase)) { throw 'симуляція лише з -Root у %TEMP%' }
  } else {
    if ($full -cne 'C:\srv\integrity-v2') { throw "Root має бути C:\srv\integrity-v2" }
    if ($env:COMPUTERNAME -ne 'V2-HOST') { throw 'чужий хост' }
    $me = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($me.User.Value -ne 'S-1-5-18' -and -not ([Security.Principal.WindowsPrincipal]$me).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'потрібен SYSTEM або адміністратор' }
  }
  if ((Get-FileHash -LiteralPath $DbTool -Algorithm SHA256).Hash -ne $ExpectedToolSha256.ToUpperInvariant()) { throw 'SHA256 v2_db_tool.py ≠ закріпленому в завданні' }
  if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "немає $Python" }
  $sddl = 'O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'
  foreach ($d in $daily, (Join-Path $daily $stamp)) {
    if (Test-Path -LiteralPath $d) { if ($d -ne $daily) { throw "$d уже існує" }; continue }
    if ($Simulate) { $null = New-Item -ItemType Directory -Path $d }
    else { $sec = New-Object Security.AccessControl.DirectorySecurity; $sec.SetSecurityDescriptorSddlForm($sddl); $null = [IO.Directory]::CreateDirectory($d, $sec) }
  }
  $run = Join-Path $daily $stamp
  if (-not $Simulate) {                                       # перевірка ACL: лише Administrators/SYSTEM, без успадкування
    $acl = [IO.Directory]::GetAccessControl($run)
    $sids = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | ForEach-Object { $_.IdentityReference.Value } | Sort-Object -Unique)
    if (-not $acl.AreAccessRulesProtected -or (($sids -join ',') -ne 'S-1-5-18,S-1-5-32-544')) { throw "ACL $run ≠ Administrators/SYSTEM" }
  }
  $sums = New-Object System.Collections.Generic.List[string]
  foreach ($db in 'integrity_v2.db', 'v2_auth.db') {
    $src = Join-Path $Root "data\$db"
    $info = @(Invoke-Tool @('user-version', $src))[-1]
    if ($info -notmatch '^USER-VERSION kind=(auth|integrity) user_version=(\d+) spec=(yes|no)$') { throw "$db не розпізнано: $info" }
    $kind = $Matches[1]; $ver = $Matches[2]; $spec = $Matches[3] -eq 'yes'
    $al = @('backup', $src, (Join-Path $run $db), '--expect-version', $ver, '--kind', $kind); if ($spec) { $al += '--strict' }
    $r = @(Invoke-Tool $al)[-1]
    $sha = (Get-FileHash -LiteralPath (Join-Path $run $db) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($r -notmatch "^BACKUP OK user_version=$ver rows=(\d+) .*restore-test=ok sha256=$sha$") { throw "${db}: копію не підтверджено" }
    $state.Databases += [ordered]@{ Db = $db; Kind = $kind; Version = [int]$ver; Rows = [int]$Matches[1]; StrictSchema = $spec; Sha256 = $sha }
    $sums.Add("$sha  $db")
  }
  [IO.File]::WriteAllLines((Join-Path $run 'SHA256SUMS.txt'), [string[]]$sums, (New-Object Text.UTF8Encoding $false))
  $state.Status = 'PASS'
  # Ротація: лише вдалі запуски цього завдання (каталог yyyyMMdd-HHmmss з DAILY-BACKUP.json Status=PASS); найновіші -Keep лишаються
  $ok = @(Get-ChildItem -LiteralPath $daily -Directory | Where-Object { $_.Name -match '^[0-9]{8}-[0-9]{6}$' -and $_.Name -ne $stamp } | Where-Object {
           $j = Join-Path $_.FullName 'DAILY-BACKUP.json'
           (Test-Path -LiteralPath $j) -and ((Get-Content -LiteralPath $j -Raw -Encoding UTF8 | ConvertFrom-Json).Schema -eq 'integrity-v2-daily-backup/1') -and ((Get-Content -LiteralPath $j -Raw -Encoding UTF8 | ConvertFrom-Json).Status -eq 'PASS') } |
         Sort-Object Name -Descending)
  foreach ($old in @($ok | Select-Object -Skip ($Keep - 1))) {
    foreach ($it in @(Get-ChildItem -LiteralPath $old.FullName -Recurse -Force)) { if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "reparse point у $($old.FullName)" } }
    Remove-Item -LiteralPath $old.FullName -Recurse -Force
    $state.Rotated += $old.Name
  }
} catch {
  $state.Status = 'FAILED'; $state.Error = $_.Exception.Message
} finally {
  $state.EndedUtc = [DateTime]::UtcNow.ToString('o')
  if ($run -and (Test-Path -LiteralPath $run)) { [IO.File]::WriteAllText((Join-Path $run 'DAILY-BACKUP.json'), (ConvertTo-Json $state -Depth 5), (New-Object Text.UTF8Encoding $false)) }
  if (Test-Path -LiteralPath $daily) {
    $line = "$stamp $($state.Status) " + (@($state.Databases | ForEach-Object { "$($_.Db):v$($_.Version):rows=$($_.Rows):sha=$($_.Sha256.Substring(0, 12))" }) -join ' ') + $(if ($state.Rotated.Count) { " rotated=$($state.Rotated -join ',')" } else { '' }) + $(if ($state.Error) { " error=$($state.Error -replace '\s+', ' ')" } else { '' })
    [IO.File]::AppendAllText($log, "$line`r`n", (New-Object Text.UTF8Encoding $false))
  }
}
"DAILY-BACKUP $($state.Status) $stamp$(if ($state.Error) { ": $($state.Error)" })"
if ($state.Status -eq 'PASS') { exit 0 } else { exit 1 }
