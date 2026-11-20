# Install-V2LmService.ps1 — встановлення служби локальної LM integrity-v2-lm (llama.cpp llama-server + Qwen3 8B) поруч із V2.
# Неінтерактивно (SSH, від адміністратора). Без -Apply — ЗВІТ: лише перевірки (адмін, служби, пам'ять, місце, SHA256 ZIP і
# моделі, склад ZIP, порт 8200 вільний, XML backend без V2_LM_*), нічого не змінюється (exit 0 — готово, 3 — блокер).
# -Apply -DecisionRef '<рішення>' — встановлення:
#   A preflight (як звіт; збій → exit 3, нічого не змінено)
#   B lm.files       lm\ (лише Administrators/SYSTEM), lm\bin ← ZIP (кожен файл звірено з архівом, маніфест LM-BIN-SHA256.txt),
#                    lm\models ← модель (SHA256 копії), logs\lm
#     lm.binary      llama-server.exe --help: потрібні прапорці; джерело ключа File (--api-key-file) або Env (LLAMA_API_KEY)
#     lm.secret      ключ API: 48 випадкових байтів → base64; File: lm\secrets\api-key.txt (служба LM — лише R); значення не виводиться
#     lm.service     services\lm\: копія WinSW 2.12.0 (SHA = еталон), XML із шаблону (Test-V2LmXml); реєстрація WinSW,
#                    перевірка NT SERVICE\integrity-v2-lm, PathName, Manual, Stopped
#     lm.acl         (після реєстрації — акаунт служби вже існує) NT SERVICE\integrity-v2-lm: RX на lm\bin, lm\models, services\lm,
#                    R на файл ключа, M на logs\lm; lm\ і lm\secrets — лише адміни; read-back кожного об'єкта
#     lm.start       старт; власники процесів; слухач ЛИШЕ 127.0.0.1:8200 (жодних інших TCP/UDP точок дерева); /health → 200;
#                    /props без ключа → 401, з ключем → 200; пріоритет llama-server BelowNormal; правил Firewall для бінарника 0
#     lm.startmode   Automatic (Delayed Start), read-back
#   C backend.xml    копія XML backend у backups\lm-install-<stamp>\ (ACL адмінів); додаються РЯДКИ V2_LM_URL і V2_LM_API_KEY
#                    (решта байтів незмінна, перевірка до запису); Test-V2WinswXml
#     backend.restart  перезапуск backend; GET /api/health → 200
# Збій у B/C → автоматичний відкат: XML backend побайтово з копії + перезапуск + /api/health; зупинка й видалення служби LM;
# видалення services\lm, lm\bin, lm\secrets (модель і logs\lm лишаються для діагностики/повтору) → exit 1; збій відкату → exit 2.
# Доказ: backups\lm-install-<stamp>\LM-INSTALL-EVIDENCE.json (кроки, SHA256, режим ключа, мережеві точки; без секретів).
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\lm\Install-V2LmService.ps1 -LlamaZip <zip> -ModelPath <gguf> [-Apply -DecisionRef '<…>']
[CmdletBinding()]
param(
  [switch] $Apply,
  [string] $DecisionRef,
  [string] $LlamaZip,
  [string] $ModelPath,
  [string] $LlamaZipSha256,
  [string] $ModelSha256,
  [string] $ApprovedSums,
  [string] $Root = 'C:\srv\integrity-v2',
  [int] $MinFreeMemoryGB = 8,
  [int] $HealthTimeoutSec = 300,
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
$E = New-V2UpEvidence 'lm-install'
$RS = @{ Phase = 'A'; Bk = $null; Key = $null; KeyMode = $null; ServiceCreated = $false; ServicesDirCreated = $false; LmRootCreated = $false
         BinCreated = $false; SecretsCreated = $false; BackendTouched = $false; BackendStopped = $false; XmlSha = $null }
function Step([string]$__n, [scriptblock]$__b) { Invoke-V2UpStep -__StepName $__n -__StepBody $__b -__Evidence $E }
$exitCode = 0
try {
  if ($Apply -and (-not $DecisionRef -or -not $DecisionRef.Trim())) { Stop-V2 'потрібен -DecisionRef' }
  if (-not $LlamaZip -or -not $ModelPath) { Stop-V2 'потрібні -LlamaZip і -ModelPath (повні шляхи до перевірених завантажень)' }
  Initialize-V2Up -Root $Root -Simulate:$Simulate -FailAt $SimulateFailAt
  Register-V2LmEntry
  $E.Simulated = $V2UpSim
  $E.Mode = if ($Apply) { 'apply' } else { 'report' }
  $RS.BackendXml = "$V2Root\services\backend\integrity-v2-backend.xml"
  $RS.Lm = "$V2Root\lm"; $RS.Svc = "$V2Root\services\lm"; $RS.Logs = "$V2Root\logs\lm"
  $RS.ModelDst = "$($RS.Lm)\models\$V2LmModelFile"

  # ------------------------------------------------------------------ A: preflight (нічого не змінює)
  Step 'lm.preflight.identity' {
    if (-not (Test-V2UpAdmin)) { Stop-V2 'потрібні права адміністратора' }
    Assert-V2UpHost
    $b = Assert-V2UpServiceIdentity $V2UpBackend
    if ($b.State -ne 'Running') { Stop-V2 "backend не працює ($($b.State))" }
    if (Get-V2UpService $V2LmName) { Stop-V2 "служба $V2LmName уже існує — спершу Uninstall-V2LmService.ps1" }
    Test-V2WinswXml -XmlPath $RS.BackendXml -Name $V2UpBackend -WinswVersion $WinswRefVersion
    $have = @(Get-V2LmBackendEnvNames $RS.BackendXml)
    if ($have.Count) { Stop-V2 "XML backend уже містить $($have -join ', ') — спершу Uninstall-V2LmService.ps1" }
    $l = @(Get-V2LmListeners)
    if ($l.Count) { Stop-V2 "порт $V2LmPort уже слухається: $($l -join '; ')" }
    Assert-V2LmWinswSource "$V2Root\services\backend\$V2UpBackend.exe"
    if (Test-Path -LiteralPath $RS.Svc) { Stop-V2 "$($RS.Svc) уже існує (залишок?) — перевірте й видаліть вручну" }
    if (Test-Path -LiteralPath $RS.Lm) {
      $extra = @(Get-ChildItem -LiteralPath $RS.Lm -Recurse -Force | Where-Object { $_.FullName -ne "$($RS.Lm)\models" -and $_.FullName -ne $RS.ModelDst })
      if ($extra.Count) { Stop-V2 "$($RS.Lm) уже містить $($extra[0].FullName) — дозволено лише models\$V2LmModelFile від попередньої спроби" }
      Assert-V2UpAdminOnly $RS.Lm
    }
    "PASS  backend працює; служби $V2LmName немає; порт $V2LmPort вільний; XML backend без V2_LM_*"
  }
  Step 'lm.preflight.inputs' {
    $zipFull = Resolve-V2Path $LlamaZip; $modelFull = Resolve-V2Path $ModelPath
    if ($modelFull -ieq $RS.ModelDst -or $zipFull.StartsWith("$V2Root\", [StringComparison]::OrdinalIgnoreCase)) { Stop-V2 "вхідні файли мають бути поза $V2Root (каталог завантажень, напр. C:\srv\V2-lm-staging)" }
    if ([IO.Path]::GetFileName($modelFull) -ne $V2LmModelFile) { Stop-V2 "очікується файл моделі $V2LmModelFile" }
    if (-not $LlamaZipSha256 -and -not $ApprovedSums) { $script:LlamaZipSha256 = $V2LmZipSha256 }
    if (-not $ModelSha256 -and -not $ApprovedSums) { $script:ModelSha256 = $V2LmModelSha256 }
    $RS.Sums = Resolve-V2LmExpectedSums -ApprovedSums $ApprovedSums -ZipSha256 $LlamaZipSha256 -ModelSha256 $ModelSha256 -ZipLeaf ([IO.Path]::GetFileName($zipFull)) -ModelLeaf $V2LmModelFile
    Assert-V2FileHash -Path $zipFull -Sha256 $RS.Sums.Zip -Label ([IO.Path]::GetFileName($zipFull))
    $RS.Layout = Get-V2LmZipLayout $zipFull
    "PASS  ZIP: $($RS.Layout.Count) файлів, $($RS.Layout.Server)"
    Assert-V2FileHash -Path $modelFull -Sha256 $RS.Sums.Model -Label $V2LmModelFile
    $RS.ModelReuse = (Test-Path -LiteralPath $RS.ModelDst -PathType Leaf) -and ((Get-V2UpSha $RS.ModelDst) -eq $RS.Sums.Model)
    if ((Test-Path -LiteralPath $RS.ModelDst) -and -not $RS.ModelReuse) { Stop-V2 "$($RS.ModelDst) існує, але SHA256 ≠ очікуваному — видаліть вручну" }
    $RS.ZipFull = $zipFull; $RS.ModelFull = $modelFull
    $E.ZipSha256 = $RS.Sums.Zip; $E.ModelSha256 = $RS.Sums.Model
    "PASS  модель: SHA256 = очікуваний$(if ($RS.ModelReuse) { '; у lm\models уже є перевірена копія — повторно не копіюється' })"
  }
  Step 'lm.preflight.resources' {
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($RS.ZipFull); try { $unz = [int64]($z.Entries | Measure-Object -Property Length -Sum).Sum } finally { $z.Dispose() }
    $model = if ($RS.ModelReuse) { 0 } else { (Get-Item -LiteralPath $RS.ModelFull).Length }
    $need = $model + $unz + 1GB
    $free = Get-V2UpFreeBytes
    if ($free -lt $need) { Stop-V2 ("вільно {0:N1} ГБ < потрібно {1:N1} ГБ (модель + бінарники + 1 ГБ)" -f ($free / 1GB), ($need / 1GB)) }
    $mem = Get-V2LmFreeMemory; $tot = Get-V2LmTotalMemory
    if ($mem -lt [int64]$MinFreeMemoryGB * 1GB) { Stop-V2 ("вільної пам'яті {0:N1} ГБ < {1} ГБ (модель ≈5 ГБ + KV-кеш 8192 ≈1,2 ГБ + буфери)" -f ($mem / 1GB), $MinFreeMemoryGB) }
    $E.Resources = [ordered]@{ FreeDiskGB = [math]::Round($free / 1GB, 1); NeedDiskGB = [math]::Round($need / 1GB, 1); FreeMemGB = [math]::Round($mem / 1GB, 1); TotalMemGB = [math]::Round($tot / 1GB, 1) }
    "PASS  диск: вільно {0:N1} ГБ ≥ {1:N1} ГБ; пам'ять: вільно {2:N1} з {3:N1} ГБ ≥ {4} ГБ" -f ($free / 1GB), ($need / 1GB), ($mem / 1GB), ($tot / 1GB), $MinFreeMemoryGB
  }
  if (-not $Apply) {
    $E.Result = 'REPORT_OK'
    Write-V2UpLog "ЗВІТ: перевірки пройдено, нічого не змінено. Встановлення: додайте -Apply -DecisionRef '<рішення>'."
    Write-V2UpLog "План: lm\bin ← ZIP; lm\models ← модель; ключ API; служба $V2LmName (NT SERVICE, 127.0.0.1:$V2LmPort, BelowNormal, Automatic (Delayed)); XML backend + V2_LM_URL, V2_LM_API_KEY; перезапуск backend."
    exit 0
  }

  # ------------------------------------------------------------------ B: файли й служба LM (відкат — видалення створеного)
  $RS.Phase = 'B'
  Step 'lm.backup-dir' {
    $RS.Bk = "$V2Root\backups\lm-install-$Stamp"
    New-V2UpAdminDir -Path $RS.Bk -DecisionRef $DecisionRef
  }
  Step 'lm.files' {
    if (-not (Test-Path -LiteralPath $RS.Lm)) { New-V2UpAdminDir -Path $RS.Lm -DecisionRef $DecisionRef; $RS.LmRootCreated = $true }
    foreach ($d in 'models') { if (-not (Test-Path -LiteralPath "$($RS.Lm)\$d")) { $null = New-Item -ItemType Directory -Path "$($RS.Lm)\$d" } }
    $null = New-Item -ItemType Directory -Path "$($RS.Lm)\bin"; $RS.BinCreated = $true
    $m = Expand-V2LmZip -Zip $RS.ZipFull -Dest "$($RS.Lm)\bin" -Prefix $RS.Layout.Prefix
    if (-not $m.Contains('llama-server.exe')) { Stop-V2 'після розпакування немає lm\bin\llama-server.exe' }
    Write-V2UpManifest "$($RS.Lm)\LM-BIN-SHA256.txt" $m
    $null = [IO.File]::Copy("$($RS.Lm)\LM-BIN-SHA256.txt", "$($RS.Bk)\LM-BIN-SHA256.txt", $false)
    $E.BinFiles = $m.Count; $E.BinManifestSha256 = Get-V2UpSha "$($RS.Lm)\LM-BIN-SHA256.txt"; $E.LlamaServerSha256 = $m['llama-server.exe']
    "PASS  lm\bin: $($m.Count) файлів = записам ZIP; маніфест lm\LM-BIN-SHA256.txt (SHA256 $($E.BinManifestSha256))"
    if (-not $RS.ModelReuse) {
      $tmp = "$($RS.ModelDst).partial"
      [IO.File]::Copy($RS.ModelFull, $tmp, $false)
      if ((Get-V2UpSha $tmp) -ne $RS.Sums.Model) { Remove-Item -LiteralPath $tmp -Force; Stop-V2 'копія моделі: SHA256 ≠ очікуваному' }
      Rename-Item -LiteralPath $tmp -NewName $V2LmModelFile
    }
    "PASS  lm\models\$V2LmModelFile — SHA256 = очікуваний"
    if (-not (Test-Path -LiteralPath $RS.Logs)) { $null = New-Item -ItemType Directory -Path $RS.Logs }
  }
  Step 'lm.binary' {
    $help = Get-V2LmHelpText "$($RS.Lm)\bin\llama-server.exe"
    $RS.KeyMode = Test-V2LmHelpFlags $help
    $E.KeyMode = $RS.KeyMode
    "PASS  llama-server --help: прапорці $($V2LmRequiredFlags -join ' ') є; ключ API — $(if ($RS.KeyMode -eq 'File') { '--api-key-file (файл)' } else { 'LLAMA_API_KEY у XML служби LM' })"
  }
  Step 'lm.secret' {
    $RS.Key = New-V2RandomKey
    if ($RS.KeyMode -eq 'File') {
      $null = New-Item -ItemType Directory -Path "$($RS.Lm)\secrets"; $RS.SecretsCreated = $true
      [IO.File]::WriteAllText("$V2Root\$V2LmKeyFileRel", $RS.Key + "`n", (New-Object Text.UTF8Encoding $false))
      "PASS  ключ API (48 випадкових байтів, base64) → $V2LmKeyFileRel; значення не виводиться"
    } else { 'PASS  ключ API (48 випадкових байтів, base64) згенеровано; буде записаний у XML служби LM; значення не виводиться' }
  }
  Step 'lm.service' {
    $null = New-Item -ItemType Directory -Path $RS.Svc; $RS.ServicesDirCreated = $true
    $src = "$V2Root\services\backend\$V2UpBackend.exe"
    Assert-V2LmWinswSource $src
    [IO.File]::Copy($src, $V2Services[$V2LmName].Exe, $false)
    Assert-V2LmWinswSource $V2Services[$V2LmName].Exe
    $xml = New-V2LmXmlText -Template (Join-Path $V2UpKit 'integrity-v2-lm.xml.template') -KeyMode $RS.KeyMode -Key $RS.Key
    $RS.LmXml = "$($RS.Svc)\$V2LmName.xml"
    [IO.File]::WriteAllText($RS.LmXml, $xml, (New-Object Text.UTF8Encoding $false)); $xml = $null
    Test-V2LmXml -XmlPath $RS.LmXml -KeyMode $RS.KeyMode
    Install-V2LmScm { param($n) $RS.ServiceCreated = $true }
    $RS.ServiceCreated = $true
    $s = Assert-V2UpServiceIdentity $V2LmName
    if ($s.State -ne 'Stopped' -or $s.StartMode -ne 'Manual') { Stop-V2 "${V2LmName}: після реєстрації $($s.State)/$($s.StartMode), очікується Stopped/Manual" }
    "PASS  служба $V2LmName зареєстрована: $($s.StartName), Manual, Stopped"
  }
  # ACL — лише після реєстрації: віртуальний акаунт NT SERVICE\integrity-v2-lm існує, коли служба є в SCM (icacls/NTAccount)
  Step 'lm.acl' {
    Grant-V2UpAcl "$($RS.Lm)\bin" $V2Services[$V2LmName].Account '(OI)(CI)RX'
    Grant-V2UpAcl "$($RS.Lm)\models" $V2Services[$V2LmName].Account '(OI)(CI)RX'
    Grant-V2UpAcl $RS.Logs $V2Services[$V2LmName].Account '(OI)(CI)M'
    if ($RS.KeyMode -eq 'File') { Grant-V2UpAcl "$V2Root\$V2LmKeyFileRel" $V2Services[$V2LmName].Account 'R'; Assert-V2UpAdminOnly "$($RS.Lm)\secrets" }
    Assert-V2UpAdminOnly $RS.Lm
    Assert-V2UpAdminOnly "$($RS.Lm)\LM-BIN-SHA256.txt"
    Assert-V2UpAclTree "$($RS.Lm)\bin" $V2LmName RX code
    Assert-V2UpAclTree "$($RS.Lm)\models" $V2LmName RX code
    Assert-V2UpAclTree $RS.Logs $V2LmName M data
    Grant-V2UpAcl $RS.Svc $V2Services[$V2LmName].Account '(OI)(CI)RX'
    Assert-V2UpAclTree $RS.Svc $V2LmName RX code
  }
  Step 'lm.start' {
    Start-V2LmService
    Wait-V2LmHealth $HealthTimeoutSec
    $anon = Get-V2LmHttpStatus '/props'
    if ($anon -ne 401) { Stop-V2 "GET /props без ключа → $anon, очікується 401 (ключ API не діє)" }
    $auth = Get-V2LmHttpStatus '/props' @{ Authorization = "Bearer $($RS.Key)" }
    if ($auth -ne 200) { Stop-V2 "GET /props з ключем → $auth, очікується 200" }
    'PASS  ключ API: /props без ключа → 401, з ключем → 200'
    $ep = @(Get-V2LmEndpoints)
    $E.Endpoints = $ep
    if (($ep -join ',') -ne "tcp 127.0.0.1:$V2LmPort") { Stop-V2 "мережеві точки служби LM: $($ep -join ', ') (очікується лише tcp 127.0.0.1:$V2LmPort)" }
    "PASS  служба LM слухає лише tcp 127.0.0.1:$V2LmPort (інших TCP/UDP точок дерева немає)"
    $pr = Get-V2LmPriority
    $E.Priority = $pr
    if ($pr -ne 'BelowNormal') { Stop-V2 "пріоритет llama-server = $pr (очікується BelowNormal; WinSW <priority> не застосовано)" }
    'PASS  пріоритет llama-server: BelowNormal'
    $fw = Get-V2LmFirewallRuleCount "$($RS.Lm)\bin\llama-server.exe"
    $E.FirewallRulesForBinary = $fw
    "INFO  правил Firewall для llama-server.exe: $(if ($fw -lt 0) { 'не вдалося перелічити' } else { $fw }) (скрипт правил не додає; доступ лише через loopback)"
  }
  Step 'lm.startmode' { Set-V2UpStartMode $V2LmName 'delayed-auto' }

  # ------------------------------------------------------------------ C: backend (живий стан; відкат — XML з копії)
  $RS.Phase = 'C'
  Step 'backend.xml' {
    $RS.XmlSha = Get-V2UpSha $RS.BackendXml
    $copy = "$($RS.Bk)\integrity-v2-backend.xml.orig"
    [IO.File]::WriteAllBytes($copy, [IO.File]::ReadAllBytes($RS.BackendXml))
    if ((Get-V2UpSha $copy) -ne $RS.XmlSha) { Stop-V2 'копія XML backend не підтверджена' }
    Assert-V2UpAdminOnly $copy
    "PASS  копія XML backend (SHA256 $($RS.XmlSha)) у $($RS.Bk)"
    $RS.BackendTouched = $true
    Add-V2LmXmlEnv -XmlPath $RS.BackendXml -Name 'V2_LM_URL' -Value $V2LmUrl
    try { Add-V2LmXmlEnv -XmlPath $RS.BackendXml -Name 'V2_LM_API_KEY' -Value $RS.Key } finally { $RS.Key = $null }
    Test-V2WinswXml -XmlPath $RS.BackendXml -Name $V2UpBackend -WinswVersion $WinswRefVersion
  }
  Step 'backend.restart' {
    $RS.BackendStopped = $true
    Stop-V2UpService $V2UpBackend
    Start-V2UpService $V2UpBackend
    Wait-V2LmBackendHealth
  }
  $E.Result = 'PASS'
} catch {
  $RS.Key = $null
  $E.Error = $_.Exception.Message -replace '^STOP: ', ''
  Write-V2UpLog "STOP: $($E.Error)"
  if ($RS.Phase -eq 'A') { $E.Result = 'BLOCKED'; $exitCode = 3 }
  else {
    $exitCode = 1; $E.Result = 'FAILED_ROLLED_BACK'
    try {
      Invoke-V2UpStep -__StepName 'rollback.backend' -__Evidence $E -__Rollback -__StepBody {
        if ($RS.BackendTouched) {
          $s = Get-V2UpService $V2UpBackend; if ($s.State -ne 'Stopped') { Stop-V2UpService $V2UpBackend }
          Restore-V2UpBytes $RS.BackendXml "$($RS.Bk)\integrity-v2-backend.xml.orig" $RS.XmlSha
          Start-V2UpService $V2UpBackend
          Wait-V2LmBackendHealth
        } elseif ($RS.BackendStopped) {
          $s = Get-V2UpService $V2UpBackend; if ($s.State -eq 'Stopped') { Start-V2UpService $V2UpBackend; Wait-V2LmBackendHealth }
        } else { 'INFO  backend не змінювався' }
      }
      Invoke-V2UpStep -__StepName 'rollback.lm' -__Evidence $E -__Rollback -__StepBody {
        $s = Get-V2UpService $V2LmName
        if ($s) {
          if ($s.State -ne 'Stopped') { Stop-V2UpService $V2LmName }
          Uninstall-V2LmScm
        }
        foreach ($p in @(@(if ($RS.ServicesDirCreated) { $RS.Svc }) + @(if ($RS.BinCreated) { "$($RS.Lm)\bin"; "$($RS.Lm)\LM-BIN-SHA256.txt" }) + @(if ($RS.SecretsCreated) { "$($RS.Lm)\secrets" }))) {
          if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force; "PASS  видалено $p" }
        }
        if (Test-Path -LiteralPath "$($RS.Lm)\models\$V2LmModelFile.partial") { Remove-Item -LiteralPath "$($RS.Lm)\models\$V2LmModelFile.partial" -Force }
        "INFO  лишаються: lm\models\$V2LmModelFile (перевірена копія для повтору), logs\lm (діагностика)"
      }
    } catch { $E.Result = 'ROLLBACK_INCOMPLETE'; $exitCode = 2 }
  }
} finally {
  $RS.Key = $null
  $E.EndedUtc = [DateTime]::UtcNow.ToString('o')
  if ($RS.Bk -and (Test-Path -LiteralPath $RS.Bk)) {
    $E.BackendXmlSha256Before = $RS.XmlSha; $E.BackendXmlSha256After = (Get-V2UpSha $RS.BackendXml)
    Save-V2UpJson (Join-Path $RS.Bk 'LM-INSTALL-EVIDENCE.json') $E
  }
}
Write-V2UpLog "LM INSTALL $($E.Result)$(if ($RS.Bk) { "; доказ $($RS.Bk)\LM-INSTALL-EVIDENCE.json" })"
exit $exitCode
