# Uninstall-V2LmService.ps1 — видалення служби локальної LM integrity-v2-lm (неінтерактивно, SSH, від адміністратора).
# Без -Apply — ЗВІТ: що буде змінено (служба, рядки V2_LM_* у XML backend, файли), нічого не змінюється (exit 0 / 3).
# -Apply -DecisionRef '<рішення>':
#   1 backend.xml     копія XML backend у backups\lm-uninstall-<stamp>\ (ACL адмінів); видаляються ЛИШЕ рядки V2_LM_URL і
#                     V2_LM_API_KEY (решта байтів незмінна); перезапуск backend; GET /api/health → 200.
#                     Збій → XML побайтово з копії, перезапуск backend (exit 1).
#   2 lm.service      зупинка (доведена: дерево процесів, порт 8200 вільний) і видалення служби з SCM (WinSW uninstall).
#   3 lm.files        завжди: services\lm (wrapper, XML), lm\secrets (ключ API); -RemoveFiles: lm\bin і маніфест;
#                     -RemoveModel: lm\models (5 ГБ) і порожній lm\. logs\lm лишається (видаляйте вручну окремим рішенням).
# Збій у кроках 2–3 → exit 1 без відкату backend (backend уже не використовує LM); повторний запуск ідемпотентний.
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\lm\Uninstall-V2LmService.ps1 [-Apply -DecisionRef '<…>'] [-RemoveFiles] [-RemoveModel]
[CmdletBinding()]
param(
  [switch] $Apply,
  [string] $DecisionRef,
  [switch] $RemoveFiles,
  [switch] $RemoveModel,
  [string] $Root = 'C:\srv\integrity-v2',
  [switch] $Simulate,
  [string[]] $SimulateFailAt = @()
)
$ErrorActionPreference = 'Stop'
$SimulateFailAt = @($SimulateFailAt | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
. (Join-Path $PSScriptRoot 'V2-lm-lib.ps1')
if ($Simulate) { . (Join-Path (Split-Path -Parent $PSScriptRoot) 'upgrade\sim\V2-upgrade-sim.ps1'); . (Join-Path $PSScriptRoot 'sim\V2-lm-sim.ps1') }
$ErrorActionPreference = 'Stop'
$Stamp = Get-Date -Format yyyyMMdd-HHmmss
$E = New-V2UpEvidence 'lm-uninstall'
$RS = @{ Phase = 'A'; Bk = $null; XmlSha = $null; BackendTouched = $false; BackendStopped = $false }
function Step([string]$__n, [scriptblock]$__b) { Invoke-V2UpStep -__StepName $__n -__StepBody $__b -__Evidence $E }
$exitCode = 0
try {
  if ($Apply -and (-not $DecisionRef -or -not $DecisionRef.Trim())) { Stop-V2 'потрібен -DecisionRef' }
  if ($RemoveModel -and -not $RemoveFiles) { Stop-V2 '-RemoveModel лише разом із -RemoveFiles' }
  Initialize-V2Up -Root $Root -Simulate:$Simulate -FailAt $SimulateFailAt
  Register-V2LmEntry
  $E.Simulated = $V2UpSim
  $E.Mode = if ($Apply) { 'apply' } else { 'report' }
  $RS.BackendXml = "$V2Root\services\backend\integrity-v2-backend.xml"
  $RS.Lm = "$V2Root\lm"; $RS.Svc = "$V2Root\services\lm"
  Step 'uninstall.preflight' {
    if (-not (Test-V2UpAdmin)) { Stop-V2 'потрібні права адміністратора' }
    Assert-V2UpHost
    $b = Assert-V2UpServiceIdentity $V2UpBackend
    if ($b.State -ne 'Running') { Stop-V2 "backend не працює ($($b.State))" }
    Test-V2WinswXml -XmlPath $RS.BackendXml -Name $V2UpBackend -WinswVersion $WinswRefVersion
    $RS.EnvNames = @(Get-V2LmBackendEnvNames $RS.BackendXml)
    $bad = @($RS.EnvNames | Where-Object { $V2LmBackendEnv -notcontains $_ })
    if ($bad.Count) { Stop-V2 "XML backend містить невідомі змінні LM: $($bad -join ', ') — перевірте вручну" }
    $s = Get-V2UpService $V2LmName
    if ($s) { $null = Assert-V2UpServiceIdentity $V2LmName }
    $RS.Service = [bool]$s
    $files = @(@($RS.Svc, "$($RS.Lm)\secrets") + @(if ($RemoveFiles) { "$($RS.Lm)\bin"; "$($RS.Lm)\LM-BIN-SHA256.txt" }) + @(if ($RemoveModel) { "$($RS.Lm)\models" }) | Where-Object { Test-Path -LiteralPath $_ })
    $RS.Files = $files
    "ПЛАН  XML backend: видалити $(if ($RS.EnvNames.Count) { $RS.EnvNames -join ', ' } else { '— (змінних LM немає)' })$(if ($RS.EnvNames.Count) { ' + перезапуск backend' })"
    "ПЛАН  служба ${V2LmName}: $(if ($s) { "$($s.State) → зупинити й видалити" } else { 'немає' })"
    "ПЛАН  файли: $(if ($files.Count) { $files -join '; ' } else { '—' })$(if (-not $RemoveFiles) { ' (lm\bin і lm\models лишаються; -RemoveFiles [-RemoveModel])' })"
  }
  if (-not $Apply) {
    $E.Result = 'REPORT_OK'
    Write-V2UpLog "ЗВІТ: нічого не змінено. Видалення: додайте -Apply -DecisionRef '<рішення>'."
    exit 0
  }
  $RS.Phase = 'B'
  Step 'uninstall.backup-dir' { $RS.Bk = "$V2Root\backups\lm-uninstall-$Stamp"; New-V2UpAdminDir -Path $RS.Bk -DecisionRef $DecisionRef }
  if ($RS.EnvNames.Count) {
    Step 'backend.xml' {
      $RS.XmlSha = Get-V2UpSha $RS.BackendXml
      $copy = "$($RS.Bk)\integrity-v2-backend.xml.orig"
      [IO.File]::WriteAllBytes($copy, [IO.File]::ReadAllBytes($RS.BackendXml))
      if ((Get-V2UpSha $copy) -ne $RS.XmlSha) { Stop-V2 'копія XML backend не підтверджена' }
      Assert-V2UpAdminOnly $copy
      "PASS  копія XML backend (SHA256 $($RS.XmlSha)) у $($RS.Bk)"
      $RS.BackendTouched = $true
      foreach ($n in $RS.EnvNames) { Remove-V2LmXmlEnv -XmlPath $RS.BackendXml -Name $n }
      Test-V2WinswXml -XmlPath $RS.BackendXml -Name $V2UpBackend -WinswVersion $WinswRefVersion
    }
    Step 'backend.restart' {
      $RS.BackendStopped = $true
      Stop-V2UpService $V2UpBackend
      Start-V2UpService $V2UpBackend
      Wait-V2LmBackendHealth
    }
  }
  $RS.Phase = 'C'
  Step 'lm.service' {
    $s = Get-V2UpService $V2LmName
    if ($s) {
      if ($s.State -ne 'Stopped') { Stop-V2UpService $V2LmName }
      Uninstall-V2LmScm
    } else { "INFO  служби $V2LmName немає" }
  }
  Step 'lm.files' {
    foreach ($p in $RS.Files) { if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force; "PASS  видалено $p" } }
    if ($RemoveModel -and (Test-Path -LiteralPath $RS.Lm) -and -not @(Get-ChildItem -LiteralPath $RS.Lm -Force).Count) { Remove-Item -LiteralPath $RS.Lm -Force; "PASS  видалено порожній $($RS.Lm)" }
    'INFO  logs\lm лишається'
  }
  $E.Result = 'PASS'
} catch {
  $E.Error = $_.Exception.Message -replace '^STOP: ', ''
  Write-V2UpLog "STOP: $($E.Error)"
  if ($RS.Phase -eq 'A') { $E.Result = 'BLOCKED'; $exitCode = 3 }
  elseif ($RS.Phase -eq 'C') { $E.Result = 'FAILED_PARTIAL'; $exitCode = 1; Write-V2UpLog 'backend уже без V2_LM_*; служба/файли LM видалені не повністю — виправте причину й повторіть (ідемпотентно)' }
  else {
    $exitCode = 1; $E.Result = 'FAILED_ROLLED_BACK'
    if ($RS.BackendTouched -or $RS.BackendStopped) {
      try {
        Invoke-V2UpStep -__StepName 'rollback.backend' -__Evidence $E -__Rollback -__StepBody {
          $s = Get-V2UpService $V2UpBackend; if ($s.State -ne 'Stopped') { Stop-V2UpService $V2UpBackend }
          if ($RS.BackendTouched) { Restore-V2UpBytes $RS.BackendXml "$($RS.Bk)\integrity-v2-backend.xml.orig" $RS.XmlSha }
          Start-V2UpService $V2UpBackend
          Wait-V2LmBackendHealth
        }
      } catch { $E.Result = 'ROLLBACK_INCOMPLETE'; $exitCode = 2 }
    }
  }
} finally {
  $E.EndedUtc = [DateTime]::UtcNow.ToString('o')
  if ($RS.Bk -and (Test-Path -LiteralPath $RS.Bk)) {
    $E.BackendXmlSha256Before = $RS.XmlSha; $E.BackendXmlSha256After = (Get-V2UpSha $RS.BackendXml)
    Save-V2UpJson (Join-Path $RS.Bk 'LM-UNINSTALL-EVIDENCE.json') $E
  }
}
Write-V2UpLog "LM UNINSTALL $($E.Result)$(if ($RS.Bk) { "; доказ $($RS.Bk)\LM-UNINSTALL-EVIDENCE.json" })"
exit $exitCode
