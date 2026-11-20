# fetch-lm-model.ps1 — завантаження моделі Qwen3-8B-Q4_K_M.gguf (Hugging Face Qwen/Qwen3-8B-GGUF, 5,03 ГБ) у ./models для
# Docker-сервісу lm (compose --profile lm) з перевіркою SHA256. Файл з'являється під кінцевим іменем лише після збігу SHA256;
# до того — <ім'я>.partial (curl докачує його при повторному запуску). Модель у Git не потрапляє (.gitignore: models/).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fetch-lm-model.ps1 [-Dest .\models] [-Revision main]
param(
  [string] $Dest = (Join-Path (Split-Path -Parent $PSScriptRoot) 'models'),
  [string] $Revision = 'main',
  [string] $Sha256 = 'd98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785'
)
$ErrorActionPreference = 'Stop'
$File = 'Qwen3-8B-Q4_K_M.gguf'
if ($Revision -notmatch '^[A-Za-z0-9._-]+$') { throw "некоректна ревізія: $Revision" }
$Url = "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/$Revision/$File"
$null = New-Item -ItemType Directory -Path $Dest -Force
$target = Join-Path $Dest $File
$partial = "$target.partial"
function Get-Sha([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
if (Test-Path -LiteralPath $target) {
  if ((Get-Sha $target) -eq $Sha256.ToLowerInvariant()) { "OK  $target уже є, SHA256 збігається"; exit 0 }
  throw "$target існує, але SHA256 не збігається — видаліть його вручну"
}
$curl = Join-Path $env:SystemRoot 'System32\curl.exe'
if (-not (Test-Path -LiteralPath $curl)) { throw 'потрібен curl.exe (Windows 10 1803+)' }
"Завантаження $Url → $partial"
& $curl --fail --location --retry 5 --retry-delay 5 --continue-at - --output $partial $Url
if ($LASTEXITCODE -ne 0) { throw "curl завершився з кодом $LASTEXITCODE (.partial збережено для докачування)" }
$got = Get-Sha $partial
if ($got -ne $Sha256.ToLowerInvariant()) {
  Remove-Item -LiteralPath $partial -Force
  throw "SHA256 $got ≠ очікуваному $Sha256 — файл видалено"
}
Rename-Item -LiteralPath $partial -NewName $File
"OK  $target (SHA256 $got)"
