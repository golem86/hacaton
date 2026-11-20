# Protect-V2Leftovers.ps1 — захист залишків попередніх спроб встановлення V2 БЕЗ видалення файлів.
# Цілі — ЛИШЕ прямі підкаталоги C:\srv з іменами integrity-v2-abandoned-* і V2-tls-staging-* (там старі XML служби із секретами SMTP,
# копії v2_auth.db / integrity_v2.db, копії приватного TLS-ключа). Ніколи не чіпаються: C:\srv\integrity-v2 (живий корінь),
# V2-release-TLSFIX5-* (скрипти завдання TLS-поновлення), V2-tls-maintenance, V1-recovery-* та будь-що інше.
# За замовчуванням — звіт (як -WhatIf): виводить лише імена каталогів і принципалів, чий доступ буде прибрано (без імен файлів, без вмісту).
# -Apply -DecisionRef: корінь кожної цілі → DACL лише Administrators + SYSTEM (FullControl, OI/CI), без успадкування, власник
# Administrators; усі нащадки → явні ACE прибрано, успадкування від кореня (icacls /reset /T), власник Administrators (icacls /setowner /T);
# потім повторна інвентаризація кожного об'єкта (будь-яка розбіжність → exit 2). Reparse point у дереві → ціль пропускається (STOP).
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\upgrade\Protect-V2Leftovers.ps1                 # звіт
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\upgrade\Protect-V2Leftovers.ps1 -Apply -DecisionRef '<рішення №5>'
[CmdletBinding()]
param(
  [switch] $Apply,
  [string] $DecisionRef,
  [string] $SrvRoot = 'C:\srv',
  [switch] $Simulate                    # ЛИШЕ тести: SrvRoot у %TEMP%; «Administrators» замінюється поточним користувачем (доступ не втрачається)
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
$Patterns = '^integrity-v2-abandoned-[A-Za-z0-9._-]+$', '^V2-tls-staging-[A-Za-z0-9._-]+$'
$Never = '^(integrity-v2|V2-tls-maintenance)$', '^V2-release-', '^V1-recovery-'
$SidSystem = 'S-1-5-18'
$Owner = if ($Simulate) { [Security.Principal.WindowsIdentity]::GetCurrent().User.Value } else { 'S-1-5-32-544' }
$Allowed = @($Owner, $SidSystem)
function Get-ServiceSidName([string]$Sid) {
  foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy') {
    $sha = [Security.Cryptography.SHA1]::Create()
    try { $h = $sha.ComputeHash([Text.Encoding]::Unicode.GetBytes($n.ToUpperInvariant())) } finally { $sha.Dispose() }
    if ($Sid -eq ('S-1-5-80-' + ((0..4 | ForEach-Object { [BitConverter]::ToUInt32($h, $_ * 4) }) -join '-'))) { return "NT SERVICE\$n" }
  }
  try { (New-Object Security.Principal.SecurityIdentifier $Sid).Translate([Security.Principal.NTAccount]).Value } catch { $Sid }
}
function Get-Inventory([string]$Dir) {
  $items = @(Get-Item -LiteralPath $Dir -Force) + @(Get-ChildItem -LiteralPath $Dir -Recurse -Force)
  $principals = @{}; $owners = @{}; $bad = 0; $reparse = @()
  foreach ($it in $items) {
    if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { $reparse += $it.FullName; continue }
    $acl = if ($it.PSIsContainer) { [IO.Directory]::GetAccessControl($it.FullName) } else { [IO.File]::GetAccessControl($it.FullName) }
    $o = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    $isBad = $false
    if ($Allowed -notcontains $o) { $owners[$o] = $true; $isBad = $true }
    foreach ($ace in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
      $s = $ace.IdentityReference.Value
      if ($Allowed -notcontains $s -or [string]$ace.AccessControlType -ne 'Allow') { $principals[$s] = $true; $isBad = $true }
    }
    if ($it.FullName -eq $Dir -and -not $acl.AreAccessRulesProtected) { $isBad = $true }
    if ($it.FullName -ne $Dir -and @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier])).Count) { $isBad = $true }   # явні ACE нащадків
    if ($isBad) { $bad++ }
  }
  [pscustomobject]@{ Items = $items.Count; NonCompliant = $bad; Principals = @($principals.Keys | Sort-Object); Owners = @($owners.Keys | Sort-Object); Reparse = $reparse }
}
function Invoke-Icacls([string[]]$A) {
  $psi = New-Object Diagnostics.ProcessStartInfo "$env:SystemRoot\System32\icacls.exe", ((@($A | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } })) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync(); $p.WaitForExit()
  if ($p.ExitCode -ne 0) { throw "icacls $($A[1]) → код $($p.ExitCode): $(($e.Result + $o.Result) -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 2)" }
}

$srv = [IO.Path]::GetFullPath($SrvRoot).TrimEnd('\')
if ($Simulate) {
  $tb = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
  if (-not $srv.StartsWith($tb, [StringComparison]::OrdinalIgnoreCase)) { throw 'STOP: симуляція лише з -SrvRoot у %TEMP%' }
} elseif ($srv -cne 'C:\srv') { throw 'STOP: -SrvRoot має бути C:\srv' }
if ($Apply) {
  if (-not $DecisionRef -or -not $DecisionRef.Trim()) { throw 'STOP: потрібен -DecisionRef' }
  if (-not $Simulate) {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'STOP: потрібні права адміністратора' }
    if ($env:COMPUTERNAME -ne 'V2-HOST') { throw 'STOP: чужий хост' }
  }
}
$targets = @(Get-ChildItem -LiteralPath $srv -Directory -Force | Where-Object { $n = $_.Name; @($Patterns | Where-Object { $n -match $_ }).Count -and -not @($Never | Where-Object { $n -match $_ }).Count } | Sort-Object Name)
$report = New-Object System.Collections.Generic.List[object]
$exitCode = 0
"$(if ($Apply) { 'ЗАСТОСУВАННЯ' } else { 'ЗВІТ (нічого не змінюється; застосувати: -Apply -DecisionRef <…>)' }): цілей $($targets.Count) у $srv"
foreach ($t in $targets) {
  $inv = Get-Inventory $t.FullName
  $rec = [ordered]@{ Directory = $t.Name; Items = $inv.Items; NonCompliant = $inv.NonCompliant
                     RemovePrincipals = @($inv.Principals | ForEach-Object { Get-ServiceSidName $_ }); FixOwners = @($inv.Owners | ForEach-Object { Get-ServiceSidName $_ }); Status = 'REPORT' }
  if ($inv.Reparse.Count) { $rec.Status = 'SKIPPED-REPARSE'; $exitCode = 2 }
  elseif ($Apply -and $inv.NonCompliant) {
    try {
      # лише розділ DACL (без SACL — SeSecurityPrivilege не потрібен): захищений, Owner + SYSTEM FullControl (OI)(CI)
      $sec = New-Object Security.AccessControl.DirectorySecurity
      $sec.SetAccessRuleProtection($true, $false)
      foreach ($sid in $Owner, $SidSystem) { $sec.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier $sid), [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))) }
      [IO.Directory]::SetAccessControl($t.FullName, $sec)
      Invoke-Icacls @($t.FullName, '/setowner', "*$Owner", '/C', '/Q')
      if (@(Get-ChildItem -LiteralPath $t.FullName -Force).Count) {
        Invoke-Icacls @("$($t.FullName)\*", '/reset', '/T', '/C', '/Q')
        Invoke-Icacls @("$($t.FullName)\*", '/setowner', "*$Owner", '/T', '/C', '/Q')
      }
      $after = Get-Inventory $t.FullName
      if ($after.NonCompliant -or $after.Reparse.Count) { $rec.Status = "FAILED-VERIFY ($($after.NonCompliant) об'єктів)"; $exitCode = 2 } else { $rec.Status = 'PROTECTED' }
    } catch { $rec.Status = "FAILED: $($_.Exception.Message)"; $exitCode = 2 }
  } elseif ($Apply) { $rec.Status = 'ALREADY-COMPLIANT' }
  $report.Add($rec)
  "  $($rec.Directory): об'єктів $($rec.Items), невідповідних $($rec.NonCompliant); прибрати доступ: $(if ($rec.RemovePrincipals.Count) { $rec.RemovePrincipals -join ', ' } else { '—' }); змінити власника з: $(if ($rec.FixOwners.Count) { $rec.FixOwners -join ', ' } else { '—' }) → $($rec.Status)"
}
$summary = [ordered]@{ Schema = 'integrity-v2-protect-leftovers/1'; Utc = [DateTime]::UtcNow.ToString('o'); Apply = [bool]$Apply; DecisionRef = $DecisionRef; Simulated = [bool]$Simulate; Targets = $report }
$bk = Join-Path $srv 'integrity-v2\backups'
if ($Apply -and (Test-Path -LiteralPath $bk)) { [IO.File]::WriteAllText((Join-Path $bk ("protect-leftovers-" + (Get-Date -Format yyyyMMdd-HHmmss) + '.json')), (ConvertTo-Json $summary -Depth 5), (New-Object Text.UTF8Encoding $false)) }
ConvertTo-Json $summary -Depth 5 -Compress
exit $exitCode
