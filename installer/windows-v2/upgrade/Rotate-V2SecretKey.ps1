# Rotate-V2SecretKey.ps1 — ротація V2_SECRET_KEY у XML служби backend (неінтерактивно, SSH від адміністратора).
# Новий ключ: 48 криптографічно випадкових байтів → base64 (64 символи). Значення ніколи не виводиться й не пишеться в журнал.
# Кроки: preflight (адмін, хост, служба працює, XML валідний, рівно одна V2_SECRET_KEY ≥ 32 символів) → копія XML у
# backups\secret-rotation-<stamp>\ (лише Administrators/SYSTEM) → заміна ЛИШЕ значення V2_SECRET_KEY (інші байти, зокрема V2_SMTP_*,
# незмінні) → перезапуск backend → smoke (health 200, /docs 401, CSRF 403, версії БД). Збій після заміни → XML повертається з
# копії побайтово, backend перезапускається зі старим ключем (exit 1). Ефект ротації: недійсні CSRF-токени і незавершені OTP
# (2FA, скидання пароля — їхні хеші HMAC із цим ключем); сесії (SHA-256 токена) і дані не змінюються. Caddy не перезапускається.
# Копію XML із СТАРИМ ключем після перевірки видаліть вручну (docs\UPGRADE_IN_PLACE.md, розділ «Секрети»).
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\upgrade\Rotate-V2SecretKey.ps1 -Apply -DecisionRef '<рішення №5>'
[CmdletBinding()]
param(
  [switch] $Apply,
  [string] $DecisionRef,
  [string] $Root = 'C:\srv\integrity-v2',
  [string] $BasePython = 'C:\Program Files\Python313\python.exe',
  [string] $DbTool,
  [switch] $Simulate,
  [string[]] $SimulateFailAt = @()
)
$ErrorActionPreference = 'Stop'
$SimulateFailAt = @($SimulateFailAt | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
if (-not $Apply) {
  'ПЛАН (нічого не змінено; виконати: -Apply -DecisionRef <…>): копія XML служби → новий V2_SECRET_KEY (48 випадкових байтів, base64) → перезапуск backend → smoke; збій → повернення XML і старого ключа'
  exit 0
}
. (Join-Path $PSScriptRoot 'V2-upgrade-lib.ps1')
if ($Simulate) { . (Join-Path $PSScriptRoot 'sim\V2-upgrade-sim.ps1') }
$ErrorActionPreference = 'Stop'
$Stamp = Get-Date -Format yyyyMMdd-HHmmss
$E = New-V2UpEvidence 'secret-rotation'
$RS = @{ Phase = 'A'; Bk = $null; Touched = $false; Stopped = $false }
function Step([string]$__n, [scriptblock]$__b) { Invoke-V2UpStep -__StepName $__n -__StepBody $__b -__Evidence $E }
$exitCode = 0
try {
  if (-not $DecisionRef -or -not $DecisionRef.Trim()) { Stop-V2 'потрібен -DecisionRef' }
  Initialize-V2Up -Root $Root -Simulate:$Simulate -FailAt $SimulateFailAt
  $E.Simulated = $V2UpSim
  if (-not $DbTool) { $DbTool = Join-Path $V2UpKit 'v2_db_tool.py' }
  $script:V2UpDbTool = [IO.Path]::GetFullPath($DbTool); $script:V2UpBasePython = $BasePython
  $RS.Xml = "$V2Root\services\backend\integrity-v2-backend.xml"
  Step 'rotate.preflight' {
    if (-not (Test-V2UpAdmin)) { Stop-V2 'потрібні права адміністратора' }
    Assert-V2UpHost
    $s = Assert-V2UpServiceIdentity $V2UpBackend
    if ($s.State -ne 'Running') { Stop-V2 "backend не працює ($($s.State))" }
    Test-V2WinswXml -XmlPath $RS.Xml -Name $V2UpBackend -WinswVersion $WinswRefVersion
    $RS.Versions = @{}
    foreach ($d in $V2UpDbs) {
      $info = Invoke-V2UpDbTool @('user-version', (Join-Path "$V2Root\data" $d.Db))
      if ($info -notmatch "^USER-VERSION kind=$($d.Kind) user_version=(\d+) ") { Stop-V2 "$($d.Db): $info" }
      $RS.Versions[$d.Kind] = [int]$Matches[1]
    }
    "PASS  backend працює; XML валідний; БД integrity v$($RS.Versions.integrity), auth v$($RS.Versions.auth)"
  }
  $RS.Phase = 'B'
  Step 'rotate.backup' {
    $RS.Bk = "$V2Root\backups\secret-rotation-$Stamp"
    New-V2UpAdminDir -Path $RS.Bk -DecisionRef $DecisionRef
    $RS.XmlSha = Get-V2UpSha $RS.Xml
    [IO.File]::WriteAllBytes("$($RS.Bk)\integrity-v2-backend.xml.orig", [IO.File]::ReadAllBytes($RS.Xml))
    if ((Get-V2UpSha "$($RS.Bk)\integrity-v2-backend.xml.orig") -ne $RS.XmlSha) { Stop-V2 'копія XML не підтверджена' }
    Assert-V2UpAdminOnly "$($RS.Bk)\integrity-v2-backend.xml.orig"
    "PASS  копія XML (SHA256 $($RS.XmlSha)) у $($RS.Bk)"
  }
  Step 'rotate.replace' {
    $RS.Touched = $true
    $k = New-V2RandomKey
    try { Set-V2UpXmlEnvValue -XmlPath $RS.Xml -Name 'V2_SECRET_KEY' -NewValue $k } finally { $k = $null }
    Test-V2WinswXml -XmlPath $RS.Xml -Name $V2UpBackend -WinswVersion $WinswRefVersion
  }
  Step 'rotate.restart' {
    $RS.Stopped = $true
    Stop-V2UpService $V2UpBackend
    Start-V2UpService $V2UpBackend
    Invoke-V2UpLocalSmoke $RS.Versions
  }
  $E.Result = 'PASS'
} catch {
  $E.Error = $_.Exception.Message -replace '^STOP: ', ''
  Write-V2UpLog "STOP: $($E.Error)"
  if ($RS.Phase -eq 'A') { $E.Result = 'BLOCKED'; $exitCode = 3 }
  else {
    $exitCode = 1; $E.Result = 'FAILED_ROLLED_BACK'
    if ($RS.Touched) {
      try {
        Invoke-V2UpStep -__StepName 'rotate.rollback' -__Evidence $E -__Rollback -__StepBody {
          $s = Get-V2UpService $V2UpBackend; if ($s.State -ne 'Stopped') { Stop-V2UpService $V2UpBackend }
          Restore-V2UpBytes $RS.Xml "$($RS.Bk)\integrity-v2-backend.xml.orig" $RS.XmlSha
          Start-V2UpService $V2UpBackend
          Invoke-V2UpLocalSmoke $RS.Versions
        }
      } catch { $E.Result = 'ROLLBACK_INCOMPLETE'; $exitCode = 2 }
    }
  }
} finally {
  $E.EndedUtc = [DateTime]::UtcNow.ToString('o')
  if ($RS.Bk -and (Test-Path -LiteralPath $RS.Bk)) { $E.XmlSha256Before = $RS.XmlSha; $E.XmlSha256After = (Get-V2UpSha $RS.Xml); Save-V2UpJson (Join-Path $RS.Bk 'ROTATION-EVIDENCE.json') $E }
}
Write-V2UpLog "SECRET ROTATION $($E.Result)$(if ($RS.Bk) { "; доказ $($RS.Bk)\ROTATION-EVIDENCE.json" })"
exit $exitCode
