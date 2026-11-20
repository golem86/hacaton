# Set-V2SmtpGmail.ps1 — налаштування реального SMTP через Gmail (пароль застосунку) для служби integrity-v2-backend.
# ЗАПУСК: лише ІНТЕРАКТИВНО в консолі адміністратора на сервері (не через SSH-аргументи): пароль вводиться приховано.
#   powershell -ExecutionPolicy Bypass -File Set-V2SmtpGmail.ps1 -GmailAddress project.account@gmail.com
# Що робить: копія XML служби (backups\smtp-<час>, лише Administrators/SYSTEM) → значення V2_SMTP_HOST/PORT/USER/PASSWORD/FROM/
# TLS_MODE у XML (інші байти не змінюються; значення не виводяться) → перезапуск backend → /api/health 200.
# Збій на будь-якому кроці → XML повертається побайтово з копії, backend перезапускається.
[CmdletBinding()]
param(
  [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9._%+-]+@(gmail\.com|googlemail\.com|[A-Za-z0-9.-]+\.[A-Za-z]{2,})$')] [string] $GmailAddress,
  [string] $Root = 'C:\srv\integrity-v2'
)
$ErrorActionPreference = 'Stop'
$xmlPath = Join-Path $Root 'services\backend\integrity-v2-backend.xml'
$svc = 'integrity-v2-backend'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Потрібна консоль адміністратора' }
if (-not [Environment]::UserInteractive) { throw 'Скрипт запускається лише інтерактивно (пароль вводиться приховано)' }
if (-not (Test-Path -LiteralPath $xmlPath)) { throw "Немає $xmlPath" }

function Read-AppPassword {
  $a = Read-Host -AsSecureString 'Пароль застосунку Gmail (16 літер; пробіли можна)'
  $b = Read-Host -AsSecureString 'Повторіть пароль застосунку'
  $pa = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($a); $pb = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($b)
  try {
    $va = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pa)) -replace '\s', ''
    $vb = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pb)) -replace '\s', ''
    if ($va -cne $vb) { throw 'Паролі не збігаються' }
    if ($va -notmatch '^[a-zA-Z]{16}$') { throw 'Пароль застосунку Google — це 16 латинських літер' }
    return $va
  } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pa); [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pb) }
}

function Escape-Xml([string]$s) { [Security.SecurityElement]::Escape($s) }

function Set-EnvInText([string]$Text, [string]$Name, [string]$Value) {
  $rx = '<env name="' + $Name + '" value="[^"]*"\s*/>'
  $m = [regex]::Matches($Text, $rx)
  $line = '<env name="' + $Name + '" value="' + (Escape-Xml $Value) + '"/>'
  if ($m.Count -gt 1) { throw "XML: змінна $Name зустрічається $($m.Count) рази" }
  if ($m.Count -eq 1) { return $Text.Substring(0, $m[0].Index) + $line + $Text.Substring($m[0].Index + $m[0].Length) }
  $last = [regex]::Matches($Text, '(?m)^([ \t]*)<env name="[^"]+" value="[^"]*"\s*/>[ \t]*\r?\n')
  if ($last.Count -eq 0) { throw 'XML: не знайдено жодного <env> для вставки' }
  $l = $last[$last.Count - 1]; $nl = if ($l.Value.EndsWith("`r`n")) { "`r`n" } else { "`n" }
  return $Text.Substring(0, $l.Index + $l.Length) + $l.Groups[1].Value + $line + $nl + $Text.Substring($l.Index + $l.Length)
}

function Get-Sha([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }

function Wait-Health {
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try { if ((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8100/api/health' -TimeoutSec 5).StatusCode -eq 200) { return $true } } catch { }
  }
  return $false
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = Join-Path $Root "backups\smtp-$stamp"
New-Item -ItemType Directory -Path $bak | Out-Null
& icacls.exe $bak /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' | Out-Null
$copy = Join-Path $bak 'integrity-v2-backend.xml.orig'
Copy-Item -LiteralPath $xmlPath -Destination $copy
$origSha = Get-Sha $xmlPath
if ((Get-Sha $copy) -ne $origSha) { throw 'Копія XML не збігається з оригіналом' }
"PASS  копія XML служби: $copy (SHA256 $origSha; значення не виводяться)"

$appPwd = Read-AppPassword
$values = [ordered]@{
  V2_SMTP_HOST = 'smtp.gmail.com'; V2_SMTP_PORT = '587'; V2_SMTP_TLS_MODE = 'starttls'
  V2_SMTP_USER = $GmailAddress; V2_SMTP_PASSWORD = $appPwd; V2_SMTP_FROM = $GmailAddress
}
$changed = $false
try {
  $bytes = [IO.File]::ReadAllBytes($xmlPath)
  $enc = New-Object Text.UTF8Encoding($false, $true)
  $off = if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { 3 } else { 0 }
  $text = $enc.GetString($bytes, $off, $bytes.Length - $off)
  foreach ($k in $values.Keys) { $text = Set-EnvInText $text $k $values[$k] }
  [xml]$parsed = $text
  foreach ($k in $values.Keys) {
    $got = @($parsed.service.env | Where-Object { $_.name -eq $k })
    if ($got.Count -ne 1 -or $got[0].value -cne $values[$k]) { throw "XML: перевірка $k не пройдена" }
  }
  $body = $enc.GetBytes($text); $out = if ($off) { [byte[]](0xEF, 0xBB, 0xBF) + $body } else { $body }
  [IO.File]::WriteAllBytes($xmlPath, $out); $changed = $true
  $text = $null; $parsed = $null
  "PASS  XML: V2_SMTP_HOST/PORT/TLS_MODE/USER/PASSWORD/FROM записано (значення не виводяться; SHA256 $(Get-Sha $xmlPath))"
  Restart-Service -Name $svc -Force
  if (-not (Wait-Health)) { throw 'backend не відповів /api/health 200 після перезапуску' }
  "PASS  $svc перезапущено, /api/health 200"
  "ГОТОВО. Перевірка: увійдіть акаунтом із реальною поштовою адресою — код має прийти листом від $GmailAddress."
} catch {
  "FAIL  $($_.Exception.Message)"
  if ($changed) {
    [IO.File]::WriteAllBytes($xmlPath, [IO.File]::ReadAllBytes($copy))
    if ((Get-Sha $xmlPath) -ne $origSha) { "CRITICAL  XML не відновлено побайтово — відновіть вручну з $copy"; exit 2 }
    Restart-Service -Name $svc -Force
    if (Wait-Health) { "PASS  відкат: XML відновлено побайтово, backend працює" } else { "CRITICAL  відкат: backend не відповідає"; exit 2 }
  }
  exit 1
} finally { $appPwd = $null; $values = $null; [GC]::Collect() }
