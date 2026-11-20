# Rollback-V2InPlace.ps1 — відкат оновлення V2 на місці до стану, зафіксованого Update-V2InPlace.ps1, НЕІНТЕРАКТИВНО (SSH, адміністратор).
# Джерело стану — <BackupDir>\UPGRADE-STATE.json (pre-upgrade-<stamp>): копії XML служби й Caddyfile (побайтово), dist.prev-<stamp>,
# копія venv із маніфестом, перевірені копії обох БД. Кроки: preflight (усі копії перевіряються ДО змін) → зупинка Caddy і backend →
# XML (лише байти з копії) → Caddyfile → dist → venv → БД з перевіреної копії (RESTORE-IN-PROGRESS/FAILED/OK) → старт backend + smoke →
# старт Caddy + HTTPS smoke. Дані, записані після оновлення, ВТРАЧАЮТЬСЯ (БД повертаються до копії) — тому потрібен -ConfirmRestoreFromBackup.
# Коди виходу: 0 — відкат виконано; 3 — preflight заблокував (нічого не змінено); 2 — збій під час відкату (CRITICAL, fail-closed:
# служби лишаються зупиненими, якщо стан небезпечний; RESTORE-FAILED блокує старт backend).
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\upgrade\Rollback-V2InPlace.ps1 `
#     -BackupDir C:\srv\integrity-v2\backups\pre-upgrade-<stamp> -DecisionRef '<рішення №5>' -ConfirmRestoreFromBackup
[CmdletBinding()]
param(
  [string] $BackupDir,
  [string] $DecisionRef,
  [switch] $ConfirmRestoreFromBackup,
  [switch] $RestoreStartMode,                   # повернути режим запуску служб до зафіксованого перед оновленням (за замовчуванням не змінюється)
  [switch] $RemoveNewRelease,                   # після успішного відкату видалити app\<новий реліз> і pkg\<новий реліз>-BACKEND-SHA256.txt
  [string] $Root = 'C:\srv\integrity-v2',
  [string] $BasePython = 'C:\Program Files\Python313\python.exe',
  [string] $DbTool,
  [switch] $ListSteps,
  [switch] $Simulate,
  [string[]] $SimulateFailAt = @()
)
$ErrorActionPreference = 'Stop'
$StepNames = @('rb.preflight', 'rb.stop-caddy', 'rb.stop-backend', 'rb.xml', 'rb.caddyfile', 'rb.dist', 'rb.venv', 'rb.db-restore',
               'rb.start-backend', 'rb.start-caddy', 'rb.startmode', 'rb.finalize')
if ($ListSteps) { $StepNames; exit 0 }
$SimulateFailAt = @($SimulateFailAt | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
. (Join-Path $PSScriptRoot 'V2-upgrade-lib.ps1')
if ($Simulate) { . (Join-Path $PSScriptRoot 'sim\V2-upgrade-sim.ps1') }
$ErrorActionPreference = 'Stop'

$Stamp = Get-Date -Format yyyyMMdd-HHmmss
$E = New-V2UpEvidence 'rollback'
$R = @{ Phase = 'A'; State = $null; Bk = $null; Stopped = @{} }
function Step([string]$__n, [scriptblock]$__b) { Invoke-V2UpStep -__StepName $__n -__StepBody $__b -__Evidence $E }
$exitCode = 0
try {
  if (-not $BackupDir -or -not $DecisionRef) { Stop-V2 'потрібні -BackupDir і -DecisionRef' }
  Initialize-V2Up -Root $Root -Simulate:$Simulate -FailAt $SimulateFailAt
  $E.Simulated = $V2UpSim
  if (-not $DbTool) { $DbTool = Join-Path $V2UpKit 'v2_db_tool.py' }
  $script:V2UpDbTool = [IO.Path]::GetFullPath($DbTool); $script:V2UpBasePython = $BasePython

  Step 'rb.preflight' {
    if (-not $ConfirmRestoreFromBackup) { Stop-V2 'потрібен ключ -ConfirmRestoreFromBackup (БД повертаються до копії перед оновленням; пізніші дані втрачаються)' }
    if (-not $DecisionRef.Trim()) { Stop-V2 'потрібен -DecisionRef' }
    if (-not (Test-V2UpAdmin)) { Stop-V2 'потрібні права адміністратора' }
    Assert-V2UpHost
    if (-not $V2UpSim) { Assert-V2Root }
    $bk = [IO.Path]::GetFullPath($BackupDir).TrimEnd('\')
    if ($bk -notmatch ('^' + [regex]::Escape("$V2Root\backups\") + 'pre-upgrade-[0-9]{8}-[0-9]{6}$')) { Stop-V2 "BackupDir має бути $V2Root\backups\pre-upgrade-<stamp>: $bk" }
    Assert-V2UpAdminOnly $bk
    $R.Bk = $bk
    $st = Get-Content -LiteralPath "$bk\UPGRADE-STATE.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($st.Schema -ne 'integrity-v2-upgrade-state/1') { Stop-V2 'UPGRADE-STATE.json: невідома схема' }
    if ([bool]$st.Simulated -ne $V2UpSim) { Stop-V2 'UPGRADE-STATE.json створено в іншому режимі (симуляція/реальний)' }
    $R.State = $st
    $xml = "$V2Root\services\backend\integrity-v2-backend.xml"
    if ((Get-V2UpSha "$bk\$($st.XmlCopy)") -ne $st.XmlSha256) { Stop-V2 'копія XML пошкоджена' }
    if ((Get-V2UpSha "$bk\$($st.CaddyfileCopy)") -ne $st.CaddyfileSha256) { Stop-V2 'копія Caddyfile пошкоджена' }
    $wd = Get-V2UpXmlWorkdir $xml
    if ($wd -ne $st.OldWorkdir -and $wd -ne $st.NewWorkdir) { Stop-V2 "живий XML вказує на $wd — не на старий/новий реліз цього оновлення" }
    if (-not (Test-Path -LiteralPath (Join-Path $st.OldWorkdir 'app\main.py'))) { Stop-V2 "немає коду попереднього релізу $($st.OldWorkdir)" }
    if ($st.DistPrev -and -not (Test-Path -LiteralPath "$V2Root\app\frontend\$($st.DistPrev)\index.html")) { Stop-V2 "немає $($st.DistPrev)" }
    if ($st.VenvCopy) {
      $diff = @(Compare-V2UpManifest (Read-V2UpSums "$bk\$($st.VenvManifest)") (Get-V2UpZipManifest "$bk\$($st.VenvCopy)"))
      if ($diff.Count) { Stop-V2 "копія venv ≠ маніфесту: $($diff | Select-Object -First 5)" }
      'PASS  копія venv = маніфест'
    }
    $items = @($st.DbBackups | ForEach-Object { [ordered]@{ Db = $_.Db; Kind = $_.Kind; Version = [int]$_.Version; File = $_.File; Sha256 = $_.Sha256; Rows = [int]$_.Rows; Fingerprint = $_.Fingerprint } })
    if ($items.Count -ne 2) { Stop-V2 'у стані немає двох перевірених копій БД' }
    $R.Items = $items
    Assert-V2UpBackupItems -Dir $bk -Items $items
    foreach ($n in $V2UpBackend, $V2UpCaddy) { $s = Assert-V2UpServiceIdentity $n; "PASS  ${n}: $($s.State), $($s.StartMode)" }
    "PASS  стан оновлення $($st.Stamp): $($st.ReleaseNew) → $($st.ReleaseOld); живий XML → $wd; рішення $DecisionRef"
  }
  $R.Phase = 'C'
  Step 'rb.stop-caddy' { Stop-V2UpService $V2UpCaddy }
  Step 'rb.stop-backend' { Stop-V2UpService $V2UpBackend }
  Step 'rb.xml' {
    $xml = "$V2Root\services\backend\integrity-v2-backend.xml"
    if ((Get-V2UpSha $xml) -eq $R.State.XmlSha256) { 'INFO  XML уже збігається з копією' } else { Restore-V2UpBytes $xml "$($R.Bk)\$($R.State.XmlCopy)" $R.State.XmlSha256 }
    Test-V2WinswXml -XmlPath $xml -Name $V2UpBackend -WinswVersion $WinswRefVersion
  }
  Step 'rb.caddyfile' {
    $cf = "$V2Root\caddy\Caddyfile"
    if ((Get-V2UpSha $cf) -eq $R.State.CaddyfileSha256) { 'INFO  Caddyfile уже збігається з копією' } else { Restore-V2UpBytes $cf "$($R.Bk)\$($R.State.CaddyfileCopy)" $R.State.CaddyfileSha256; Assert-V2UpCaddyfileAcl $cf }
  }
  Step 'rb.dist' {
    if (-not $R.State.DistPrev) { return 'INFO  dist не змінювався' }
    Restore-V2UpDist $R.State.Stamp
  }
  Step 'rb.venv' {
    if (-not $R.State.VenvCopy) { return 'INFO  venv не змінювався' }
    Restore-V2UpVenv "$($R.Bk)\$($R.State.VenvCopy)" "$($R.Bk)\$($R.State.VenvManifest)" $Stamp
  }
  Step 'rb.db-restore' { Restore-V2UpDatabases -Dir $R.Bk -Items $R.Items -Stamp $Stamp -AsideDir "$($R.Bk)\rolled-back-db-$Stamp" }
  Step 'rb.start-backend' {
    Start-V2UpService $V2UpBackend
    Invoke-V2UpLocalSmoke @{ integrity = [int]$R.State.VersionsFrom.integrity; auth = [int]$R.State.VersionsFrom.auth }
  }
  Step 'rb.start-caddy' { Start-V2UpService $V2UpCaddy; Invoke-V2UpHttpsSmoke }
  Step 'rb.startmode' {
    if (-not $RestoreStartMode) { return 'INFO  режим запуску служб не змінюється (-RestoreStartMode не задано)' }
    foreach ($n in $V2UpBackend, $V2UpCaddy) { Set-V2UpStartMode $n $(if ($R.State.ModesBefore.$n.StartMode -eq 'Auto') { 'delayed-auto' } else { 'demand' }) }
  }
  Step 'rb.finalize' {
    if ($RemoveNewRelease) {
      $na = Split-Path -Parent $R.State.NewWorkdir
      if ((Get-V2UpXmlWorkdir "$V2Root\services\backend\integrity-v2-backend.xml") -like "$na*") { Stop-V2 'XML досі вказує на новий реліз' }
      if (Test-Path -LiteralPath $na) { Remove-Item -LiteralPath $na -Recurse -Force; "PASS  видалено $na" }
      $pm = "$V2Root\pkg\$($R.State.ReleaseNew)-BACKEND-SHA256.txt"; if (Test-Path -LiteralPath $pm) { Remove-Item -LiteralPath $pm -Force; "PASS  видалено $pm" }
      $df = "$V2Root\app\frontend\dist.failed-$($R.State.Stamp)"; if (Test-Path -LiteralPath $df) { Remove-Item -LiteralPath $df -Recurse -Force; "PASS  видалено $df (dist нового релізу)" }
    }
    "PASS  відкат до $($R.State.ReleaseOld) завершено"
  }
  $E.Result = 'PASS'
} catch {
  $why = $_.Exception.Message -replace '^STOP: ', ''
  $E.Error = $why
  Write-V2UpLog "STOP: $why"
  if ($R.Phase -eq 'A') { $E.Result = 'BLOCKED'; $exitCode = 3 } else { $E.Result = 'ROLLBACK_FAILED'; $exitCode = 2 }
} finally {
  $E.EndedUtc = [DateTime]::UtcNow.ToString('o')
  if ($R.Bk -and (Test-Path -LiteralPath $R.Bk)) { Save-V2UpJson (Join-Path $R.Bk "ROLLBACK-EVIDENCE-$Stamp.json") $E }
}
$summary = switch ($exitCode) { 0 { 'ROLLBACK PASS' } 2 { 'ROLLBACK FAILED (CRITICAL): служби не стартували там, де стан небезпечний; див. ROLLBACK-EVIDENCE і docs\UPGRADE_IN_PLACE.md' } 3 { 'ROLLBACK BLOCKED — нічого не змінено' } }
Write-V2UpLog "$summary; результат $($E.Result)"
exit $exitCode
