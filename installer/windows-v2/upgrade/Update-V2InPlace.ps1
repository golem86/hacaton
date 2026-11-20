# Update-V2InPlace.ps1 — оновлення Integrity Management Dashboard V2 на місці (C:\srv\integrity-v2), НЕІНТЕРАКТИВНО
# (придатно для SSH від адміністратора; жодних запитів). Документація: ..\docs\UPGRADE_IN_PLACE.md.
#
# Пакет оновлення (-PackageDir; усі файли — у сумах з окремого каналу -ApprovedSums, рядки "<sha256>  <ім'я>"):
#   backend-src.zip          записи <ReleaseId>/backend/…   (модулі bootstrap не розгортаються)
#   BACKEND-SHA256.txt       "<sha256>  backend/<шлях>" для КОЖНОГО файлу ZIP (маніфест релізу; ним же користується bind-check)
#   dist.zip + DIST-SHA256.txt   (необов'язково) записи dist/…; "<sha256>  dist/<шлях>"
#   Caddyfile                (необов'язково) ШАБЛОН deploy\Caddyfile; цільова форма TLSFIX5 генерується New-V2TargetConfig
#   requirements-hashed.txt  (необов'язково) "ім'я==версія --hash=sha256:…" для НОВИХ коліс; колеса — у -WheelDir
#
# Фази й коди виходу:
#   A preflight (лише читання)                      → збій: exit 3, нічого не змінено
#   B підготовка (нові каталоги, копії; живе не змінюється) → збій: створене цим запуском прибирається, exit 1
#   C простій (зупинка → копія БД → XML → venv → міграція → перевірки → старт → dist/Caddyfile → старт → режим запуску)
#     → збій на будь-якому кроці: автоматичний відкат (код, XML, venv, БД з перевіреної копії, dist, Caddyfile, старт, smoke);
#       exit 1 — відкат успішний; exit 2 — відкат неповний (CRITICAL; служби лишаються зупиненими там, де небезпечно стартувати)
#   exit 0 — оновлено; доказ: backups\pre-upgrade-<stamp>\UPGRADE-EVIDENCE.json і UPGRADE-STATE.json (для Rollback-V2InPlace.ps1)
#
# Приклад (SSH, адміністратор):
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-release-<id>\installer\windows-v2\upgrade\Update-V2InPlace.ps1 `
#     -PackageDir C:\srv\V2-release-<id>\package -ApprovedSums C:\srv\V2-release-<id>\APPROVED-SHA256.txt -ReleaseId integrity-v2-<sha7> `
#     -WheelDir C:\srv\V2-release-<id>\package\wheels -Requirements C:\srv\V2-release-<id>\package\requirements-hashed.txt `
#     -DecisionRef '<рішення №5>' -ConfirmVerifiedBackup
[CmdletBinding()]
param(
  [string] $PackageDir,
  [string] $ApprovedSums,
  [string] $ReleaseId,
  [string] $DecisionRef,
  [switch] $ConfirmVerifiedBackup,              # підтвердження: міграція дозволена після перевіреної копії, яку робить цей скрипт
  [string] $WheelDir,
  [string] $Requirements,
  [string] $CurrentManifest,                    # маніфест поточного коду; за замовчуванням pkg\<реліз>-BACKEND-SHA256.txt або pkg\<реліз>-backend-src.zip
  [ValidateRange(0, 99)] [int] $FromIntegrityVersion = 3,
  [ValidateRange(0, 99)] [int] $FromAuthVersion = 1,
  [ValidateRange(0, 99)] [int] $ToIntegrityVersion = 5,
  [ValidateRange(0, 99)] [int] $ToAuthVersion = 2,
  [switch] $KeepManualStart,                    # за замовчуванням обидві служби → delayed-auto (сайт піднімається після перезавантаження)
  [switch] $SkipCaddyfile,                      # не застосовувати Caddyfile пакета
  [string] $Root = 'C:\srv\integrity-v2',
  [string] $BasePython = 'C:\Program Files\Python313\python.exe',   # для v2_db_tool (stdlib, -I)
  [string] $ReleasePython,                      # python із SQLAlchemy для bind-check integrity (за замовчуванням venv служби)
  [string] $DbTool,
  [long] $MinFreeBytes = 3GB,
  [switch] $ListSteps,
  [switch] $Simulate,                           # ЛИШЕ тести: -Root у %TEMP%, адаптери sim\V2-upgrade-sim.ps1
  [string[]] $SimulateFailAt = @()
)
$ErrorActionPreference = 'Stop'
$StepNames = @('preflight.identity', 'preflight.package', 'preflight.current-code', 'preflight.db', 'preflight.env', 'preflight.space',
               'stage.backup-dir', 'stage.code', 'stage.bind-check', 'stage.dist', 'stage.caddyfile', 'stage.venv-copy', 'stage.config-copies',
               'stop.caddy', 'stop.backend', 'backup.db', 'xml.workdir', 'venv.pip', 'db.migrate', 'db.verify', 'start.backend',
               'swap.dist', 'caddyfile.replace', 'start.caddy', 'startmode', 'finalize')
$RollbackNames = @('rollback.startmode', 'rollback.stop-caddy', 'rollback.stop-backend', 'rollback.caddyfile', 'rollback.dist', 'rollback.db-restore',
                   'rollback.venv', 'rollback.xml', 'rollback.start-backend', 'rollback.start-caddy', 'rollback.cleanup', 'cleanup.staged')
if ($ListSteps) { $StepNames; $RollbackNames; exit 0 }
$SimulateFailAt = @($SimulateFailAt | ForEach-Object { $_ -split ',' } | Where-Object { $_ })

. (Join-Path $PSScriptRoot 'V2-upgrade-lib.ps1')
if ($Simulate) { . (Join-Path $PSScriptRoot 'sim\V2-upgrade-sim.ps1') }
$ErrorActionPreference = 'Stop'

$Stamp = Get-Date -Format yyyyMMdd-HHmmss
$E = New-V2UpEvidence 'upgrade'
$U = @{ Phase = 'A'; ModesBefore = @{}; Bk = $null; NewAppCreated = $false; DistNewCreated = $false; PkgManifestCreated = $false
        CaddyStopped = $false; BackendStopped = $false; XmlTouched = $false; VenvTouched = $false; MigrationStarted = $false
        DistPrevMoved = $false; DistSwapped = $false; CaddyfileTouched = $false; StartModeChanged = $false; DbBackups = @(); NewCaddyfile = $null
        HasDist = $false; HasReq = $false; VenvCopy = $null }
function Step([string]$__n, [scriptblock]$__b) { Invoke-V2UpStep -__StepName $__n -__StepBody $__b -__Evidence $E }
function RStep([string]$__n, [scriptblock]$__b) {
  try { Invoke-V2UpStep -__StepName $__n -__StepBody $__b -__Evidence $E -__Rollback; $true } catch { $script:RollbackFailures++; $false }
}
function Save-V2UpState([bool]$Completed) {
  if (-not $U.Bk) { return }
  Save-V2UpJson (Join-Path $U.Bk 'UPGRADE-STATE.json') ([ordered]@{
      Schema = 'integrity-v2-upgrade-state/1'; Stamp = $Stamp; Completed = $Completed; Simulated = $V2UpSim; DecisionRef = $DecisionRef
      ReleaseOld = $U.CurRelease; ReleaseNew = $ReleaseId; OldWorkdir = $U.OldWorkdir; NewWorkdir = $U.NewWorkdir
      XmlCopy = 'integrity-v2-backend.xml.orig'; XmlSha256 = $U.XmlSha; CaddyfileCopy = 'Caddyfile.orig'; CaddyfileSha256 = $U.CaddyfileSha
      NewCaddyfileSha256 = $(if ($U.CaddyfileTouched) { $U.NewCaddyfileSha } else { $null }); DistPrev = $(if ($U.DistSwapped) { "dist.prev-$Stamp" } else { $null })
      VenvCopy = $(if ($U.VenvTouched) { 'venv.zip' } else { $null }); VenvManifest = $(if ($U.VenvTouched) { 'venv-SHA256.txt' } else { $null })
      DbBackups = @($U.DbBackups); VersionsFrom = @{ integrity = $FromIntegrityVersion; auth = $FromAuthVersion }
      VersionsTo = @{ integrity = $ToIntegrityVersion; auth = $ToAuthVersion }; ModesBefore = $U.ModesBefore })
}
$RollbackFailures = 0
$exitCode = 0
try {
  if (-not $PackageDir -or -not $ApprovedSums -or -not $ReleaseId -or -not $DecisionRef) { Stop-V2 'потрібні -PackageDir, -ApprovedSums, -ReleaseId, -DecisionRef' }
  Initialize-V2Up -Root $Root -Simulate:$Simulate -FailAt $SimulateFailAt
  $E.Simulated = $V2UpSim
  if (-not $DbTool) { $DbTool = Join-Path $V2UpKit 'v2_db_tool.py' }
  $script:V2UpDbTool = [IO.Path]::GetFullPath($DbTool); $script:V2UpBasePython = $BasePython
  if (-not $ReleasePython) { $ReleasePython = Get-V2UpVenvPython }
  $E.Release = [ordered]@{ New = $ReleaseId; DecisionRef = $DecisionRef; From = @{ integrity = $FromIntegrityVersion; auth = $FromAuthVersion }; To = @{ integrity = $ToIntegrityVersion; auth = $ToAuthVersion } }

  # ============================================================== A. PREFLIGHT (лише читання)
  Step 'preflight.identity' {
    if (-not $ConfirmVerifiedBackup) { Stop-V2 'потрібен ключ -ConfirmVerifiedBackup (міграція лише після перевіреної резервної копії, яку робить цей скрипт)' }
    if (-not $DecisionRef.Trim()) { Stop-V2 'потрібен -DecisionRef' }
    if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') { Stop-V2 "ReleaseId поза дозволеною формою: $ReleaseId" }
    if ($ToIntegrityVersion -lt $FromIntegrityVersion -or $ToAuthVersion -lt $FromAuthVersion) { Stop-V2 'версії схем після оновлення не можуть бути нижчими' }
    if (-not (Test-V2UpAdmin)) { Stop-V2 'потрібні права адміністратора' }
    Assert-V2UpHost
    if (-not $V2UpSim) { Assert-V2Root }
    foreach ($n in $V2UpBackend, $V2UpCaddy) {
      $s = Assert-V2UpServiceIdentity $n
      if ($s.State -ne 'Running') { Stop-V2 "$n не працює ($($s.State)) — оновлення лише з робочого стану" }
      $U.ModesBefore[$n] = @{ StartMode = $s.StartMode; Delayed = $s.DelayedAutoStart }
      "PASS  ${n}: Running, $($s.StartName), StartMode $($s.StartMode)$(if ($s.DelayedAutoStart) { ' (delayed)' })"
    }
    if (@((Get-V2UpService $V2UpCaddy).DependsOn) -notcontains 'Tailscale') { Stop-V2 'служба Caddy має залежати від Tailscale' }
    $U.Xml = "$V2Root\services\backend\integrity-v2-backend.xml"
    Test-V2WinswXml -XmlPath $U.Xml -Name $V2UpBackend -WinswVersion $WinswRefVersion
    $wd = Get-V2UpXmlWorkdir $U.Xml
    if ($wd -notmatch ('^' + [regex]::Escape("$V2Root\app\") + '([A-Za-z0-9][A-Za-z0-9._-]{2,63})\\backend$')) { Stop-V2 "workingdirectory поза $V2Root\app\<реліз>\backend: $wd" }
    $U.CurRelease = $Matches[1]; $U.OldWorkdir = $wd
    if ($U.CurRelease -eq $ReleaseId) { Stop-V2 "реліз $ReleaseId уже розгорнуто" }
    $U.NewApp = "$V2Root\app\$ReleaseId"; $U.NewWorkdir = "$($U.NewApp)\backend"
    if (Test-Path -LiteralPath $U.NewApp) { Stop-V2 "$($U.NewApp) уже існує" }
    if (Test-Path -LiteralPath "$V2Root\venv.old") { Stop-V2 "$V2Root\venv.old уже існує (залишок попереднього відкату venv) — видаліть вручну" }
    foreach ($p in "$V2Root\caddy\Caddyfile", "$V2Root\app\frontend\dist\index.html", (Get-V2UpVenvPython), $script:V2UpBasePython, $script:V2UpDbTool, (Get-V2UpCaddyExe)) {
      if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { Stop-V2 "немає $p" }
    }
    if (-not $V2UpSim) { Assert-V2FileHash -Path (Get-V2UpCaddyExe) -Sha256 $CaddyRefSha256 -Label 'caddy.exe' }
    $E.Release.Old = $U.CurRelease
    "PASS  XML служби: workingdirectory $wd (поточний реліз $($U.CurRelease)); новий реліз $ReleaseId; рішення $DecisionRef"
  }
  Step 'preflight.package' {
    $pkg = [IO.Path]::GetFullPath($PackageDir)
    $sums = Read-V2UpSums $ApprovedSums
    $need = @('backend-src.zip', 'BACKEND-SHA256.txt')
    $U.HasDist = Test-Path -LiteralPath (Join-Path $pkg 'dist.zip')
    if ($U.HasDist -ne (Test-Path -LiteralPath (Join-Path $pkg 'DIST-SHA256.txt'))) { Stop-V2 'dist.zip і DIST-SHA256.txt — лише разом' }
    if ($U.HasDist) { $need += 'dist.zip', 'DIST-SHA256.txt' }
    $U.PkgCaddyfile = $null
    if ((Test-Path -LiteralPath (Join-Path $pkg 'Caddyfile')) -and -not $SkipCaddyfile) { $need += 'Caddyfile'; $U.PkgCaddyfile = Join-Path $pkg 'Caddyfile' }
    foreach ($n in $need) {
      $p = Join-Path $pkg $n
      if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { Stop-V2 "у пакеті немає $n" }
      if (-not $sums.Contains($n)) { Stop-V2 "у сумах з окремого каналу немає $n" }
      if ((Get-V2UpSha $p) -ne $sums[$n]) { Stop-V2 "SHA256 $n ≠ сумі з окремого каналу" }
    }
    "PASS  пакет: $($need -join ', ') = суми з окремого каналу"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $U.BackendZip = Join-Path $pkg 'backend-src.zip'; $U.PkgManifest = Join-Path $pkg 'BACKEND-SHA256.txt'
    $man = Read-V2UpSums $U.PkgManifest
    $z = [IO.Compression.ZipFile]::OpenRead($U.BackendZip)
    try {
      $seen = @{}
      foreach ($ze in $z.Entries) {
        if ($ze.FullName.EndsWith('/')) { continue }
        if (-not $ze.FullName.StartsWith("$ReleaseId/backend/") -or $ze.FullName.Contains('\') -or ($ze.FullName -split '/') -contains '..' -or $ze.FullName.Contains(':')) { Stop-V2 "ZIP: запис поза $ReleaseId/backend/: $($ze.FullName)" }
        $rel = $ze.FullName.Substring($ReleaseId.Length + 1)
        if (-not $man.Contains($rel)) { Stop-V2 "ZIP: $rel немає в BACKEND-SHA256.txt" }
        if ((Get-V2UpStreamSha $ze.Open()) -ne $man[$rel]) { Stop-V2 "ZIP: SHA256 $rel ≠ маніфесту" }
        $seen[$rel] = $true
      }
      foreach ($k in $man.Keys) { if (-not $seen.ContainsKey($k)) { Stop-V2 "маніфест: $k немає в ZIP" } }
    } finally { $z.Dispose() }
    foreach ($k in 'backend/app/main.py', 'backend/app/migrations.py', 'backend/requirements.txt') { if (-not $man.Contains($k)) { Stop-V2 "у релізі немає $k" } }
    $U.BackendManifest = $man
    $U.Skipped = @($man.Keys | Where-Object { $_ -match $V2UpBootstrapRx })
    "PASS  backend-src.zip: $($man.Count) файлів = BACKEND-SHA256.txt; не розгортаються (bootstrap): $(if ($U.Skipped.Count) { $U.Skipped -join ', ' } else { 'немає' })"
    if ($U.HasDist) {
      $dm = Read-V2UpSums (Join-Path $pkg 'DIST-SHA256.txt')
      $z = [IO.Compression.ZipFile]::OpenRead((Join-Path $pkg 'dist.zip'))
      try {
        $seen = @{}
        foreach ($ze in $z.Entries) {
          if ($ze.FullName.EndsWith('/')) { continue }
          if (-not $ze.FullName.StartsWith('dist/') -or $ze.FullName.Contains('\') -or ($ze.FullName -split '/') -contains '..' -or $ze.FullName.Contains(':')) { Stop-V2 "dist.zip: запис поза dist/: $($ze.FullName)" }
          if (-not $dm.Contains($ze.FullName) -or (Get-V2UpStreamSha $ze.Open()) -ne $dm[$ze.FullName]) { Stop-V2 "dist.zip: $($ze.FullName) ≠ DIST-SHA256.txt" }
          $seen[$ze.FullName] = $true
        }
        foreach ($k in $dm.Keys) { if (-not $seen.ContainsKey($k)) { Stop-V2 "DIST-SHA256.txt: $k немає в ZIP" } }
      } finally { $z.Dispose() }
      if (-not $dm.Contains('dist/index.html')) { Stop-V2 'dist: немає index.html' }
      $U.DistManifest = $dm
      "PASS  dist.zip: $($dm.Count) файлів = DIST-SHA256.txt"
    }
    $U.DistBefore = Get-V2UpTreeManifest "$V2Root\app\frontend\dist"
    if ($Requirements -or $WheelDir) {
      if (-not $Requirements -or -not $WheelDir) { Stop-V2 '-Requirements і -WheelDir — лише разом' }
      $rn = Split-Path $Requirements -Leaf
      if (-not $sums.Contains($rn) -or (Get-V2UpSha $Requirements) -ne $sums[$rn]) { Stop-V2 "SHA256 $rn ≠ сумі з окремого каналу" }
      $reqLines = @([IO.File]::ReadAllLines($Requirements) | Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith('#') })
      if (-not $reqLines.Count) { Stop-V2 'файл вимог порожній' }
      $U.ReqPins = [ordered]@{}
      foreach ($l in $reqLines) {
        if ($l.Trim() -notmatch '^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.+!_-]+)(\s+--hash=sha256:[0-9a-f]{64})+$') { Stop-V2 "рядок вимог без точної версії й sha256: $l" }
        $U.ReqPins[$Matches[1]] = $Matches[2]
      }
      $whl = @(Get-ChildItem -LiteralPath $WheelDir -Force)
      if (-not $whl.Count -or @($whl | Where-Object { $_.PSIsContainer -or $_.Extension -ne '.whl' }).Count) { Stop-V2 "$WheelDir має містити лише файли .whl" }
      $U.HasReq = $true
      "PASS  вимоги: $(@($U.ReqPins.Keys | ForEach-Object { "$_==$($U.ReqPins[$_])" }) -join ', '); коліс $($whl.Count) (хеші перевіряє pip --require-hashes)"
    }
  }
  Step 'preflight.current-code' {
    $cur = $U.CurRelease
    $man = $null; $src = $null
    if ($CurrentManifest) { $man = Read-V2UpSums $CurrentManifest; $src = $CurrentManifest }
    elseif (Test-Path -LiteralPath "$V2Root\pkg\$cur-BACKEND-SHA256.txt") { $src = "$V2Root\pkg\$cur-BACKEND-SHA256.txt"; $man = Read-V2UpSums $src }
    elseif (Test-Path -LiteralPath "$V2Root\pkg\$cur-backend-src.zip") {
      $src = "$V2Root\pkg\$cur-backend-src.zip"; $man = [ordered]@{}
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      $z = [IO.Compression.ZipFile]::OpenRead($src)
      try { foreach ($ze in $z.Entries) { if (-not $ze.FullName.EndsWith('/') -and $ze.FullName.StartsWith("$cur/backend/")) { $man[$ze.FullName.Substring($cur.Length + 1)] = Get-V2UpStreamSha $ze.Open() } } } finally { $z.Dispose() }
    } else { Stop-V2 "немає маніфесту поточного коду (pkg\$cur-BACKEND-SHA256.txt або pkg\$cur-backend-src.zip); задайте -CurrentManifest" }
    # модулі bootstrap є в маніфесті релізу, але stage.code їх не розгортає — їхня відсутність у живому коді не розбіжність
    $notDeployed = @($man.Keys | Where-Object { $_ -match $V2UpBootstrapRx })
    foreach ($k in $notDeployed) { $man.Remove($k) }
    $live = [ordered]@{}
    $m = Get-V2UpTreeManifest $U.OldWorkdir -Exclude '(^|/)__pycache__/'
    foreach ($k in $m.Keys) { $live["backend/$k"] = $m[$k] }
    $bad = @(Compare-V2UpManifest $man $live | Where-Object { $_ -notmatch '^зайвий backend/app/v2_clean_bootstrap_admin\.py$' })
    if ($bad.Count) { Stop-V2 "поточний код ≠ маніфесту ($src): $($bad | Select-Object -First 8)" }
    $extra = @($live.Keys | Where-Object { -not $man.Contains($_) })
    "PASS  поточний код $($U.OldWorkdir): $($man.Count) файлів = маніфест ($src)$(if ($extra.Count) { "; зайві (не переносяться): $($extra -join ', ')" })"
  }
  Step 'preflight.db' {
    $ver = @{ integrity = $FromIntegrityVersion; auth = $FromAuthVersion }
    foreach ($d in $V2UpDbs) {
      $p = Join-Path "$V2Root\data" $d.Db
      $v = Invoke-V2UpDbTool @('verify', $p, '--expect-version', "$($ver[$d.Kind])"); if ($v -notlike 'VERIFY OK*') { Stop-V2 "$($d.Db): $v" }
      $s = Invoke-V2UpDbTool @('schema', $p, '--kind', $d.Kind, '--expect-version', "$($ver[$d.Kind])"); if ($s -notlike '* SCHEMA OK*') { Stop-V2 "$($d.Db): $s" }
      "PASS  $($d.Db): $v; $s"
    }
    $U.UsersBefore = Invoke-V2UpDbTool @('users', "$V2Root\data\v2_auth.db")
    $U.FpBefore = Invoke-V2UpDbTool @('fingerprint', "$V2Root\data\integrity_v2.db")
    $null = Assert-V2NoRestoreBlock -DataDir "$V2Root\data"
    "PASS  облікові записи: $($U.UsersBefore); відбиток seed-таблиць $($U.FpBefore.Substring(0, 16))…"
  }
  Step 'preflight.env' {
    $names = @(Get-V2UpMachineEnvNames)
    if ($names.Count) { Stop-V2 "Machine-змінні, що впливають на V2 (лише імена): $($names -join ', ')" }
    'PASS  Machine-змінних UVICORN_*/V2_*/INTEGRITY_*/APP_ENV/TRUSTED_PROXIES/FRONTEND_ORIGINS/FORWARDED_ALLOW_IPS немає'
  }
  Step 'preflight.space' {
    $venvBytes = [int64](@(Get-ChildItem -LiteralPath "$V2Root\venv" -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum)
    $dbBytes = [int64](@(Get-ChildItem -LiteralPath "$V2Root\data" -File -Filter '*.db' | Measure-Object -Property Length -Sum).Sum)
    $pkgBytes = [int64](@(Get-ChildItem -LiteralPath $PackageDir -Recurse -File | Measure-Object -Property Length -Sum).Sum)
    $need = [Math]::Max($MinFreeBytes, 2 * ($venvBytes + 4 * $dbBytes + 2 * $pkgBytes))
    $free = Get-V2UpFreeBytes
    if ($free -lt $need) { Stop-V2 "вільно $([math]::Round($free / 1MB)) МБ, потрібно ≥ $([math]::Round($need / 1MB)) МБ" }
    "PASS  вільно $([math]::Round($free / 1GB, 1)) ГБ (потрібно ≥ $([math]::Round($need / 1MB)) МБ)"
  }

  # ============================================================== B. ПІДГОТОВКА (живий стан не змінюється)
  $U.Phase = 'B'
  Step 'stage.backup-dir' {
    $U.Bk = "$V2Root\backups\pre-upgrade-$Stamp"
    New-V2UpAdminDir -Path $U.Bk -DecisionRef $DecisionRef
    $null = New-Item -ItemType Directory -Path "$($U.Bk)\tmp"
    $env:TEMP = "$($U.Bk)\tmp"; $env:TMP = "$($U.Bk)\tmp"          # тимчасові файли дочірніх процесів (копії БД) — лише в каталозі копії
    "PASS  каталог копії $($U.Bk) (Administrators/SYSTEM)"
  }
  Step 'stage.code' {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $U.NewAppCreated = $true
    $null = New-Item -ItemType Directory -Path $U.NewApp
    $base = [IO.Path]::GetFullPath($U.NewApp).TrimEnd('\') + '\'
    $z = [IO.Compression.ZipFile]::OpenRead($U.BackendZip)
    try {
      foreach ($ze in $z.Entries) {
        if ($ze.FullName.EndsWith('/')) { continue }
        $rel = $ze.FullName.Substring($ReleaseId.Length + 1)
        if ($rel -match $V2UpBootstrapRx) { continue }
        $dst = [IO.Path]::GetFullPath((Join-Path $U.NewApp ($rel -replace '/', '\')))
        if (-not $dst.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "запис поза каталогом релізу: $rel" }
        $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $dst))
        [IO.Compression.ZipFileExtensions]::ExtractToFile($ze, $dst, $false)
      }
    } finally { $z.Dispose() }
    $want = [ordered]@{}; foreach ($k in $U.BackendManifest.Keys) { if ($k -notmatch $V2UpBootstrapRx) { $want[$k] = $U.BackendManifest[$k] } }
    $diff = @(Compare-V2UpManifest $want (Get-V2UpTreeManifest $U.NewApp))
    if ($diff.Count) { Stop-V2 "розгорнутий код ≠ маніфесту: $($diff | Select-Object -First 5)" }
    if (@(Get-ChildItem -LiteralPath $U.NewApp -Recurse -File | Where-Object { $_.Name -match '(?i)bootstrap' }).Count) { Stop-V2 'у новому каталозі є модуль bootstrap' }
    Grant-V2UpAcl $U.NewApp $V2Services[$V2UpBackend].Account '(OI)(CI)RX'
    Assert-V2UpAclTree $U.NewApp $V2UpBackend RX code
    $pm = "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt"
    if (Test-Path -LiteralPath $pm) { Stop-V2 "$pm уже існує" }
    $U.PkgManifestCreated = $true
    [IO.File]::Copy($U.PkgManifest, $pm, $false)
    "PASS  код $($U.NewApp): $($want.Count) файлів = маніфест; маніфест релізу → $pm"
  }
  Step 'stage.bind-check' {
    $r = Invoke-V2UpDbToolAll @('bind-check', '--kind', 'auth', '--expect-version', "$ToAuthVersion", '--release-backend', $U.NewWorkdir, '--release-manifest', $U.PkgManifest)
    if ($r[-1] -ne "BIND OK kind=auth version=$ToAuthVersion") { Stop-V2 "bind-check auth: $($r[-1])" }
    $r
    $r = Invoke-V2UpDbToolAll @('bind-check', '--kind', 'integrity', '--expect-version', "$ToIntegrityVersion", '--release-backend', $U.NewWorkdir, '--release-manifest', $U.PkgManifest, '--release-py', $ReleasePython)
    if ($r[-1] -ne "BIND OK kind=integrity version=$ToIntegrityVersion") { Stop-V2 "bind-check integrity: $($r[-1])" }
    $r
  }
  Step 'stage.dist' {
    if (-not $U.HasDist) { return 'INFO  dist у пакеті немає — frontend не змінюється' }
    $U.DistNew = "$V2Root\app\frontend\dist.new-$Stamp"
    $U.DistNewCreated = $true
    $null = New-Item -ItemType Directory -Path $U.DistNew
    $base = [IO.Path]::GetFullPath($U.DistNew).TrimEnd('\') + '\'
    $z = [IO.Compression.ZipFile]::OpenRead((Join-Path $PackageDir 'dist.zip'))
    try {
      foreach ($ze in $z.Entries) {
        if ($ze.FullName.EndsWith('/')) { continue }
        $dst = [IO.Path]::GetFullPath((Join-Path $U.DistNew ($ze.FullName.Substring(5) -replace '/', '\')))
        if (-not $dst.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "dist: запис поза каталогом: $($ze.FullName)" }
        $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $dst))
        [IO.Compression.ZipFileExtensions]::ExtractToFile($ze, $dst, $false)
      }
    } finally { $z.Dispose() }
    $want = [ordered]@{}; foreach ($k in $U.DistManifest.Keys) { $want[$k.Substring(5)] = $U.DistManifest[$k] }
    $diff = @(Compare-V2UpManifest $want (Get-V2UpTreeManifest $U.DistNew))
    if ($diff.Count) { Stop-V2 "розгорнутий dist ≠ маніфесту: $($diff | Select-Object -First 5)" }
    Grant-V2UpAcl $U.DistNew $V2Services[$V2UpCaddy].Account '(OI)(CI)RX'
    Assert-V2UpAclTree $U.DistNew $V2UpCaddy RX code
    "PASS  dist → $($U.DistNew): $($want.Count) файлів = DIST-SHA256.txt; ACL Caddy RX"
  }
  Step 'stage.caddyfile' {
    if (-not $U.PkgCaddyfile) { return 'INFO  Caddyfile не змінюється' }
    $tc = "$($U.Bk)\target-config"
    New-V2TargetConfig -CaddySource $U.PkgCaddyfile -BackendSource (Join-Path $V2UpKit 'integrity-v2-backend.xml.template') -Destination $tc -HostName $V2UpHostName -Addresses @($V2UpAddress) -UseFileTls
    Assert-V2TargetConfigManifest -Directory $tc -HostName $V2UpHostName -Addresses @($V2UpAddress)
    $U.NewCaddyfile = "$tc\Caddyfile"
    $txt = [IO.File]::ReadAllText($U.NewCaddyfile)
    if ([regex]::Matches($txt, '(?m)^\s*tls\s+C:/srv/integrity-v2/caddy/tls/site\.crt\s+C:/srv/integrity-v2/caddy/tls/site\.key\s*$').Count -ne 1) { Stop-V2 'Caddyfile: рядок tls файлової пари не рівно один (його вимагає завдання TLS-поновлення)' }
    Invoke-V2UpCaddyValidate $U.NewCaddyfile
    $U.NewCaddyfileSha = Get-V2UpSha $U.NewCaddyfile
    "PASS  цільовий Caddyfile SHA256 $($U.NewCaddyfileSha)"
  }
  Step 'stage.venv-copy' {
    if (-not $U.HasReq) { return 'INFO  нових залежностей немає — venv не змінюється' }
    $U.VenvCopy = "$($U.Bk)\venv.zip"
    Save-V2UpVenvZip "$V2Root\venv" $U.VenvCopy "$($U.Bk)\venv-SHA256.txt"
    $U.FreezeBefore = @(Invoke-V2Native -Exe (Get-V2UpVenvPython) -ArgList @('-E', '-s', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'freeze', '--all') -Utf8 -What 'pip freeze')
    $E.FreezeBefore = $U.FreezeBefore
  }
  Step 'stage.config-copies' {
    $U.XmlSha = Get-V2UpSha $U.Xml
    [IO.File]::WriteAllBytes("$($U.Bk)\integrity-v2-backend.xml.orig", [IO.File]::ReadAllBytes($U.Xml))
    if ((Get-V2UpSha "$($U.Bk)\integrity-v2-backend.xml.orig") -ne $U.XmlSha) { Stop-V2 'копія XML не підтверджена' }
    Assert-V2UpAdminOnly "$($U.Bk)\integrity-v2-backend.xml.orig"
    $U.CaddyfileSha = Get-V2UpSha "$V2Root\caddy\Caddyfile"
    [IO.File]::WriteAllBytes("$($U.Bk)\Caddyfile.orig", [IO.File]::ReadAllBytes("$V2Root\caddy\Caddyfile"))
    if ((Get-V2UpSha "$($U.Bk)\Caddyfile.orig") -ne $U.CaddyfileSha) { Stop-V2 'копія Caddyfile не підтверджена' }
    Save-V2UpState $false
    "PASS  копії XML служби (SHA256 $($U.XmlSha), значення не виводяться) і Caddyfile (SHA256 $($U.CaddyfileSha)) у $($U.Bk)"
  }

  # ============================================================== C. ПРОСТІЙ (відкат на будь-якому збої)
  $U.Phase = 'C'
  Step 'stop.caddy' { $U.CaddyStopped = $true; Stop-V2UpService $V2UpCaddy }
  Step 'stop.backend' { $U.BackendStopped = $true; Stop-V2UpService $V2UpBackend }
  Step 'backup.db' {
    $U.DbBackups = @(Backup-V2UpDatabases -Dir $U.Bk -Versions @{ integrity = $FromIntegrityVersion; auth = $FromAuthVersion } -Strict)
    Save-V2UpState $false
    foreach ($it in $U.DbBackups) { "PASS  $($it.Db) → $($it.File): user_version $($it.Version), рядків $($it.Rows), restore-test ok, строга схема, SHA256 $($it.Sha256)" }
  }
  Step 'xml.workdir' {
    $U.XmlTouched = $true
    Set-V2UpXmlWorkdir -XmlPath $U.Xml -Old $U.OldWorkdir -New $U.NewWorkdir
    Test-V2WinswXml -XmlPath $U.Xml -Name $V2UpBackend -WinswVersion $WinswRefVersion
  }
  Step 'venv.pip' {
    $py = Get-V2UpVenvPython
    if (-not $U.HasReq) { 'INFO  нових залежностей немає — venv не змінюється' } else {
    $U.VenvTouched = $true
    Invoke-V2Native -Exe $py -What 'pip install' -Utf8 -ArgList @('-E', '-s', '-m', 'pip', '--isolated', '--disable-pip-version-check', '--no-input', 'install', '--no-index', '--no-cache-dir',
      '--find-links', $WheelDir, '--require-hashes', '--only-binary', ':all:', '-r', $Requirements) | Select-Object -Last 2
    Invoke-V2Native -Exe $py -ArgList @('-E', '-s', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'check') -Utf8 -What 'pip check' | Select-Object -Last 1
    $pins = @($U.ReqPins.Keys | ForEach-Object { "$_==$($U.ReqPins[$_])" })
    Invoke-V2Native -Exe $py -What 'версії встановлених пакетів' -Utf8 -ArgList (@('-I', '-B', '-c', 'import sys, importlib.metadata as m; bad = [p for p in sys.argv[1:] if m.version(p.split("==")[0]) != p.split("==")[1]]; sys.exit("STOP: версії: " + ", ".join(bad)) if bad else print("PASS  встановлено:", ", ".join(sys.argv[1:]))') + $pins)
    }
    # імпорт усіх модулів app нового релізу (крім main/seed/bootstrap) у середовищі release без секрету й без доступу до живих БД
    $mods = @(Get-ChildItem -LiteralPath "$($U.NewWorkdir)\app" -Recurse -File -Filter '*.py' | ForEach-Object { ($_.FullName.Substring($U.NewWorkdir.Length + 1) -replace '\.py$', '' -replace '\\', '.') -replace '\.__init__$', '' } |
              Where-Object { $_ -notmatch '^app\.(main|seed)$' -and $_ -notmatch '(?i)bootstrap' } | Sort-Object)
    $ic = Join-Path $env:TEMP 'import-check'; $null = New-Item -ItemType Directory -Path $ic -Force
    Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$ic\i.db"; V2_AUTH_DB = "$ic\a.db"; V2_SECRET_KEY = $null } -Body {
      Invoke-V2Native -Exe $py -What 'імпорт модулів app' -Utf8 -ArgList (@('-I', '-B', '-c', 'import sys, importlib; sys.path.insert(0, sys.argv[1]); [importlib.import_module(x) for x in sys.argv[2:]]; print("PASS  імпорт app:", len(sys.argv) - 2, "модулів")', $U.NewWorkdir) + $mods)
    }
    if (@(Get-ChildItem -LiteralPath $ic -Force).Count) { Stop-V2 'імпорт модулів створив файли БД — імпорт має бути без побічних дій' }
    Remove-Item -LiteralPath $ic -Recurse -Force
  }
  Step 'db.migrate' {
    $U.DataBefore = @(Get-ChildItem -LiteralPath "$V2Root\data" -File -Force | ForEach-Object Name)
    $U.MigrationStarted = $true
    # Секрет служби міграції не потрібен (app.migrations не викликає settings.secret_key); V2_SECRET_KEY навмисно відсутній,
    # щоб будь-яка майбутня залежність міграції від секрету впала голосно, а не мовчки використала інший ключ.
    $out = @(Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$V2Root\data\integrity_v2.db"; V2_AUTH_DB = "$V2Root\data\v2_auth.db"; V2_SECRET_KEY = $null
                                 INTEGRITY_DEMO_XROLE = $null; V2_AUTH_DEV_MAIL = $null } -Body {
      Invoke-V2Native -Exe (Get-V2UpVenvPython) -ArgList @('-B', '-E', '-s', '-X', 'utf8', '-m', 'app.migrations', '--apply', '--confirm-verified-backup') -WorkingDirectory $U.NewWorkdir -Utf8 -What 'app.migrations --apply'
    })
    $out | ForEach-Object { "      $_" }
    Move-V2UpNewDataFiles -Before $U.DataBefore -Dest "$($U.Bk)\mig"     # власні копії міграції — з data\ (Modify для служби)
  }
  Step 'db.verify' {
    $ver = @{ integrity = $ToIntegrityVersion; auth = $ToAuthVersion }
    foreach ($d in $V2UpDbs) {
      $p = Join-Path "$V2Root\data" $d.Db
      $v = Invoke-V2UpDbTool @('verify', $p, '--expect-version', "$($ver[$d.Kind])"); if ($v -notlike 'VERIFY OK*') { Stop-V2 "$($d.Db): $v" }
      $s = Invoke-V2UpDbTool @('schema', $p, '--kind', $d.Kind, '--expect-version', "$($ver[$d.Kind])"); if ($s -notlike '* SCHEMA OK*') { Stop-V2 "$($d.Db) після міграції: $s" }
      "PASS  $($d.Db): $v; $s"
    }
    $fp = Invoke-V2UpDbTool @('fingerprint', "$V2Root\data\integrity_v2.db")
    $fpBk = @($U.DbBackups | Where-Object { $_.Kind -eq 'integrity' })[0].Fingerprint
    if ($fp -ne $fpBk) { Stop-V2 'міграція змінила детерміновані таблиці (відбиток ≠ копії)' }
    $users = Invoke-V2UpDbTool @('users', "$V2Root\data\v2_auth.db")
    if ($users -ne $U.UsersBefore) { Stop-V2 "міграція змінила ролі облікових записів: $($U.UsersBefore) → $users" }
    $null = Assert-V2NoRestoreBlock -DataDir "$V2Root\data"
    "PASS  відбиток seed-таблиць незмінний; $users"
  }
  Step 'start.backend' {
    Start-V2UpService $V2UpBackend
    Invoke-V2UpLocalSmoke @{ integrity = $ToIntegrityVersion; auth = $ToAuthVersion }
  }
  Step 'swap.dist' {
    if (-not $U.HasDist) { return 'INFO  dist не змінюється' }
    $fe = "$V2Root\app\frontend"
    if (Test-Path -LiteralPath "$fe\dist.prev-$Stamp") { Stop-V2 "$fe\dist.prev-$Stamp уже існує" }
    Rename-Item -LiteralPath "$fe\dist" -NewName "dist.prev-$Stamp" -ErrorAction Stop; $U.DistPrevMoved = $true
    Rename-Item -LiteralPath $U.DistNew -NewName 'dist' -ErrorAction Stop; $U.DistSwapped = $true
    $want = [ordered]@{}; foreach ($k in $U.DistManifest.Keys) { $want[$k.Substring(5)] = $U.DistManifest[$k] }
    $diff = @(Compare-V2UpManifest $want (Get-V2UpTreeManifest "$fe\dist"))
    if ($diff.Count) { Stop-V2 "живий dist ≠ маніфесту: $($diff | Select-Object -First 5)" }
    Save-V2UpState $false
    "PASS  dist замінено (попередній → dist.prev-$Stamp)"
  }
  Step 'caddyfile.replace' {
    if (-not $U.NewCaddyfile) { return 'INFO  Caddyfile не змінюється' }
    $live = "$V2Root\caddy\Caddyfile"
    $U.CaddyfileTouched = $true
    [IO.File]::WriteAllBytes($live, [IO.File]::ReadAllBytes($U.NewCaddyfile))     # на місці: ACL файла (Caddy R) зберігається
    if ((Get-V2UpSha $live) -ne $U.NewCaddyfileSha) { Stop-V2 'живий Caddyfile ≠ перевіреному' }
    Assert-V2UpCaddyfileAcl $live
    Save-V2UpState $false
    "PASS  Caddyfile замінено на місці (SHA256 $($U.NewCaddyfileSha)); ACL збережено"
  }
  Step 'start.caddy' {
    Start-V2UpService $V2UpCaddy
    Invoke-V2UpHttpsSmoke -Headers:([bool]$U.NewCaddyfile)
  }
  Step 'startmode' {
    if ($KeepManualStart) { return 'INFO  -KeepManualStart: режим запуску служб не змінюється' }
    $U.StartModeChanged = $true
    foreach ($n in $V2UpBackend, $V2UpCaddy) { Set-V2UpStartMode $n 'delayed-auto' }
    if (@((Get-V2UpService $V2UpCaddy).DependsOn) -notcontains 'Tailscale') { Stop-V2 'залежність Caddy від Tailscale зникла' }
    'PASS  обидві служби: Automatic (Delayed Start); залежність Caddy → Tailscale збережено'
  }
  Step 'finalize' {
    Save-V2UpState $true
    if (Test-Path -LiteralPath "$($U.Bk)\tmp") { Remove-Item -LiteralPath "$($U.Bk)\tmp" -Recurse -Force }
    "PASS  оновлено до $ReleaseId; відкат: Rollback-V2InPlace.ps1 -BackupDir $($U.Bk)"
  }
  $E.Result = 'PASS'
} catch {
  $why = $_.Exception.Message -replace '^STOP: ', ''
  $E.Error = $why
  Write-V2UpLog "STOP: $why"
  if ($U.Phase -eq 'A') {
    $E.Result = 'BLOCKED'; $exitCode = 3
  } else {
    if ($U.Phase -eq 'C') {
      # ---------------------------------------------------- автоматичний відкат (зворотний порядок; fail-closed)
      $okXml = $true; $okDb = $true; $okVenv = $true; $okCaddyCfg = $true
      if ($U.StartModeChanged) { $null = RStep 'rollback.startmode' { foreach ($n in $V2UpBackend, $V2UpCaddy) { Set-V2UpStartMode $n $(if ($U.ModesBefore[$n].StartMode -eq 'Auto') { 'delayed-auto' } else { 'demand' }) } } }
      $stopC = RStep 'rollback.stop-caddy' { $s = Get-V2UpService $V2UpCaddy; if ($s -and $s.State -ne 'Stopped') { Stop-V2UpService $V2UpCaddy } else { 'INFO  Caddy зупинено' } }
      $stopB = RStep 'rollback.stop-backend' { $s = Get-V2UpService $V2UpBackend; if ($s -and $s.State -ne 'Stopped') { Stop-V2UpService $V2UpBackend } else { 'INFO  backend зупинено' } }
      if ($U.CaddyfileTouched) { $okCaddyCfg = RStep 'rollback.caddyfile' { Restore-V2UpBytes "$V2Root\caddy\Caddyfile" "$($U.Bk)\Caddyfile.orig" $U.CaddyfileSha } }
      if ($U.DistPrevMoved) {
        $okCaddyCfg = (RStep 'rollback.dist' {
            $fe = "$V2Root\app\frontend"
            if ($U.DistSwapped) { Restore-V2UpDist $Stamp } else { Rename-Item -LiteralPath "$fe\dist.prev-$Stamp" -NewName 'dist' -ErrorAction Stop; 'PASS  dist повернуто' }
            $diff = @(Compare-V2UpManifest $U.DistBefore (Get-V2UpTreeManifest "$fe\dist")); if ($diff.Count) { Stop-V2 "dist після відкату ≠ початковому: $($diff | Select-Object -First 3)" }
          }) -and $okCaddyCfg
      }
      if ($U.MigrationStarted) {
        if (-not $stopB) { $okDb = $false; Write-V2UpLog 'ВІДКАТ БД пропущено: зупинку backend не підтверджено' }
        else { $okDb = RStep 'rollback.db-restore' { Restore-V2UpDatabases -Dir $U.Bk -Items $U.DbBackups -Stamp $Stamp -AsideDir "$($U.Bk)\db-old"; Move-V2UpNewDataFiles -Before $U.DataBefore -Dest "$($U.Bk)\mig" } }
      }
      if ($U.VenvTouched) { $okVenv = $stopB -and (RStep 'rollback.venv' { Restore-V2UpVenv "$($U.Bk)\venv.zip" "$($U.Bk)\venv-SHA256.txt" $Stamp }) }
      if ($U.XmlTouched) { $okXml = RStep 'rollback.xml' { Restore-V2UpBytes $U.Xml "$($U.Bk)\integrity-v2-backend.xml.orig" $U.XmlSha; Test-V2WinswXml -XmlPath $U.Xml -Name $V2UpBackend -WinswVersion $WinswRefVersion } }
      # Перед оновленням обидві служби працювали (preflight) — після відкату обидві мають працювати, якщо стан безпечний
      $startedB = $false
      if ($okXml -and $okDb -and $okVenv -and $stopB) {
        $startedB = RStep 'rollback.start-backend' { Start-V2UpService $V2UpBackend; Invoke-V2UpLocalSmoke @{ integrity = $FromIntegrityVersion; auth = $FromAuthVersion } }
      } else { $RollbackFailures++; Write-V2UpLog 'ВІДКАТ: backend НЕ стартує (XML/БД/venv не відновлено або зупинку не підтверджено) — fail-closed' }
      if ($okCaddyCfg -and $stopC) { $null = RStep 'rollback.start-caddy' { Start-V2UpService $V2UpCaddy; if ($startedB) { Invoke-V2UpHttpsSmoke } else { 'INFO  backend не працює — HTTPS smoke пропущено' } } }
      else { $RollbackFailures++; Write-V2UpLog 'ВІДКАТ: Caddy НЕ стартує (Caddyfile/dist не відновлено або зупинку не підтверджено)' }
    }
    $null = RStep 'cleanup.staged' {
      $wdNow = if (Test-Path -LiteralPath $U.Xml) { Get-V2UpXmlWorkdir $U.Xml } else { '' }
      if ($U.NewAppCreated -and (Test-Path -LiteralPath $U.NewApp)) {
        if ($wdNow -like "$($U.NewApp)*") { Stop-V2 "XML досі вказує на $($U.NewApp) — каталог не видаляється" }
        Remove-Item -LiteralPath $U.NewApp -Recurse -Force; "PASS  видалено $($U.NewApp)"
      }
      foreach ($p in @("$V2Root\app\frontend\dist.new-$Stamp", "$V2Root\app\frontend\dist.failed-$Stamp")) { if ($U.DistNewCreated -and (Test-Path -LiteralPath $p)) { Remove-Item -LiteralPath $p -Recurse -Force; "PASS  видалено $p" } }
      if ($U.PkgManifestCreated -and (Test-Path -LiteralPath "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt")) { Remove-Item -LiteralPath "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt" -Force; "PASS  видалено pkg\$ReleaseId-BACKEND-SHA256.txt" }
    }
    if ($RollbackFailures) { $E.Result = 'ROLLBACK_INCOMPLETE'; $exitCode = 2 }
    else { $E.Result = $(if ($U.Phase -eq 'C') { 'FAILED_ROLLED_BACK' } else { 'FAILED_NOTHING_CHANGED' }); $exitCode = 1 }
  }
} finally {
  $E.EndedUtc = [DateTime]::UtcNow.ToString('o')
  $E.Phase = $U.Phase
  if ($U.Bk -and (Test-Path -LiteralPath $U.Bk)) { Save-V2UpJson (Join-Path $U.Bk 'UPGRADE-EVIDENCE.json') $E; $E.EvidencePath = (Join-Path $U.Bk 'UPGRADE-EVIDENCE.json') }
}
$summary = switch ($exitCode) { 0 { 'UPGRADE PASS' } 1 { 'UPGRADE FAILED — ВІДКАТ ВИКОНАНО (стан до оновлення)' } 2 { 'UPGRADE FAILED — ВІДКАТ НЕПОВНИЙ (CRITICAL): див. UPGRADE-EVIDENCE.json і docs\UPGRADE_IN_PLACE.md' } 3 { 'UPGRADE BLOCKED — нічого не змінено' } }
Write-V2UpLog "$summary; результат $($E.Result)$(if ($U.Bk) { "; доказ $($U.Bk)\UPGRADE-EVIDENCE.json" })"
if ($exitCode -eq 3) { Write-V2UpLog (ConvertTo-Json -InputObject $E -Depth 6 -Compress) }
exit $exitCode
