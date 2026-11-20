# test-lm-service.ps1 — локальні тести служби LM (лише тимчасовий каталог; служби, ACL, мережа, C:\srv не змінюються):
#   L0 розбір усіх .ps1 у lm\ (PowerShell Parser, 0 помилок);
#   L1 статичні перевірки шаблону integrity-v2-lm.xml.template (Test-V2LmXml, loopback, NT SERVICE, без секретів, без «--» у коментарі);
#   L2–L13 сухі прогони Install/Uninstall-V2LmService з -Simulate на підставному корені: звіт, успіх, видалення, невірний SHA моделі,
#   збій /health, збій перезапуску backend, режим ключа Env, відсутній прапорець, порт зайнятий, зайва мережева точка, без -DecisionRef.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-lm-service.ps1 [-WorkDir <тимчасовий каталог>] [-RealBin <каталог llama-bin>]
#   -RealBin: довідка `llama-server.exe --help` справжньої збірки (лише --help; модель не запускається) — для L3 замість синтетичної.
param([string] $WorkDir, [string] $RealBin)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $PSScriptRoot                                  # installer\windows-v2
$PSX = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$res = New-Object System.Collections.Generic.List[string]
$fail = $false
function Add-Res([string]$id, [bool]$ok, [string]$d) { if (-not $ok) { $script:fail = $true }; $res.Add(('{0,-18} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
if (-not $WorkDir) { $WorkDir = $env:TEMP }
$W = Join-Path ([IO.Path]::GetFullPath($WorkDir)) ('lm' + [guid]::NewGuid().ToString('N').Substring(0, 6)); $null = New-Item -ItemType Directory $W
$utf8 = New-Object Text.UTF8Encoding $false
$Secret = 'SIM-LM-SECRET-' + [guid]::NewGuid().ToString('N').Substring(0, 12)

function Invoke-Child([string]$Script, [string[]]$A) {
  $all = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $Script) + $A
  $psi = New-Object Diagnostics.ProcessStartInfo $PSX, ((@($all | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } })) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $psi.EnvironmentVariables['TEMP'] = $W; $psi.EnvironmentVariables['TMP'] = $W
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(600000)) { $p.Kill(); throw "тайм-аут $Script" }
  [pscustomobject]@{ Code = $p.ExitCode; Out = $o.Result + $e.Result }
}
# Синтетична довідка (формат рядків як у llama-server b12180)
$HelpFull = @'
-m,    --model FNAME                    model path to load
--host HOST                             IP addresses to listen on
--port PORT                             port to listen (default: 9931)
-c,    --ctx-size N                     size of the prompt context
-t,    --threads N                      number of CPU threads
-np,   --parallel N                     number of server slots
--ui,  --webui, --no-ui, --no-webui     whether to enable the Web UI (default: enabled)
--slots, --no-slots                     expose slots monitoring endpoint (default: enabled)
--jinja, --no-jinja                     whether to use jinja template engine for chat (default: enabled)
-rea,  --reasoning [on|off|auto]        Use reasoning/thinking in the chat
-cram, --cache-ram N                    set the maximum cache size in MiB (default: 8192)
--prio N                                set process/thread priority : low(-1), normal(0)
--api-key KEY                           API key to use for authentication (env: LLAMA_API_KEY)
--api-key-file FNAME                    path to file containing API keys, one per line
'@
$HelpReal = $null
if ($RealBin) {
  $exe = Join-Path $RealBin 'llama-server.exe'
  $psi = New-Object Diagnostics.ProcessStartInfo $exe, '--help'
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync(); $null = $p.WaitForExit(60000)
  $HelpReal = $o.Result + "`n" + $e.Result
}
# Артефакти: ZIP (llama-server.exe + DLL у корені) і «модель»
$Art = Join-Path $W 'art'; $null = New-Item -ItemType Directory $Art
$zsrc = Join-Path $Art 'zsrc'; $null = New-Item -ItemType Directory $zsrc
[IO.File]::WriteAllBytes("$zsrc\llama-server.exe", [byte[]](77, 90) + [byte[]](1..200))
[IO.File]::WriteAllBytes("$zsrc\ggml-base.dll", [byte[]](77, 90) + [byte[]](50..120))
[IO.File]::WriteAllBytes("$zsrc\ggml-cpu-haswell.dll", [byte[]](77, 90) + [byte[]](3..90))
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Zip = Join-Path $Art 'llama-b12180-bin-win-cpu-x64.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($zsrc, $Zip)
$Model = Join-Path $Art 'Qwen3-8B-Q4_K_M.gguf'
[IO.File]::WriteAllBytes($Model, [Text.Encoding]::ASCII.GetBytes('GGUF' + ('x' * 4096)))
$ZipSha = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower(); $ModelSha = (Get-FileHash $Model -Algorithm SHA256).Hash.ToLower()

function New-Root([string]$Name, [hashtable]$Cfg = @{}) {
  $r = Join-Path $W "$Name\v2"
  foreach ($d in 'data', 'backups', 'services\backend', 'logs\backend', 'app') { $null = New-Item -ItemType Directory -Path (Join-Path $r $d) -Force }
  $xml = [IO.File]::ReadAllText((Join-Path $Kit 'integrity-v2-backend.xml.template')).Replace('C:\srv\integrity-v2', $r)
  foreach ($ph in '__V2_SECRET_KEY__', '__V2_SMTP_HOST__', '__V2_SMTP_USER__', '__V2_SMTP_PASSWORD__', '__V2_SMTP_FROM__') { $xml = $xml.Replace($ph, "$Secret$($ph.Trim('_'))-0123456789abcdef0123456789abcdef") }
  [IO.File]::WriteAllText("$r\services\backend\integrity-v2-backend.xml", $xml, $utf8)
  [IO.File]::WriteAllBytes("$r\services\backend\integrity-v2-backend.exe", [byte[]](77, 90, 0, 1, 2, 3))
  $sim = Join-Path $W "$Name\sim"; $null = New-Item -ItemType Directory -Path $sim -Force
  [IO.File]::WriteAllText("$sim\state.json", '{"Services":{"integrity-v2-backend":{"State":"Running","StartMode":"Auto","Delayed":true,"DependsOn":[]},"integrity-v2-caddy":{"State":"Running","StartMode":"Auto","Delayed":true,"DependsOn":["Tailscale"]}},"Events":[]}', $utf8)
  $c = [ordered]@{ Caddy = 'none'; MachineEnv = @(); FreeBytes = 500000000000; LmHelp = $(if ($HelpReal) { $HelpReal } else { $HelpFull }) }
  foreach ($k in $Cfg.Keys) { $c[$k] = $Cfg[$k] }
  [IO.File]::WriteAllText("$sim\config.json", (ConvertTo-Json $c -Depth 4), $utf8)
  $r
}
function Get-State([string]$r) { Get-Content (Join-Path (Split-Path -Parent $r) 'sim\state.json') -Raw | ConvertFrom-Json }
function Get-Listing([string]$r) { @(Get-ChildItem -LiteralPath $r -Recurse -Force | ForEach-Object { if ($_.PSIsContainer) { $_.FullName } else { "$($_.FullName) $((Get-FileHash -LiteralPath $_.FullName).Hash)" } } | Sort-Object) -join "`n" }
function Get-Evidence([string]$r, [string]$Kind) { $f = @(Get-ChildItem "$r\backups" -Recurse -Filter "LM-$Kind-EVIDENCE.json"); if ($f.Count) { Get-Content $f[-1].FullName -Raw | ConvertFrom-Json } else { $null } }
function Install([string]$r, [string[]]$Extra = @()) { Invoke-Child (Join-Path $PSScriptRoot 'Install-V2LmService.ps1') (@('-Simulate', '-Root', $r, '-LlamaZip', $Zip, '-ModelPath', $Model, '-LlamaZipSha256', $ZipSha, '-ModelSha256', $ModelSha) + $Extra) }
function Uninstall([string]$r, [string[]]$Extra = @()) { Invoke-Child (Join-Path $PSScriptRoot 'Uninstall-V2LmService.ps1') (@('-Simulate', '-Root', $r) + $Extra) }
$Apply = @('-Apply', '-DecisionRef', 'TEST-LM')

try {
  # ------------------------------------------------------------------ L0: розбір
  $errs = @(); $files = @(Get-ChildItem $PSScriptRoot -Recurse -Filter *.ps1)
  foreach ($f in $files) { $t = $null; $e = $null; $null = [Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t, [ref]$e); if ($e) { $errs += "$($f.Name): $($e[0].Message)" } }
  $bomless = @($files | Where-Object { $b = [IO.File]::ReadAllBytes($_.FullName); -not ($b[0] -eq 0xEF -and $b[1] -eq 0xBB) } | ForEach-Object Name)
  Add-Res 'L0.parse' ($errs.Count -eq 0 -and $bomless.Count -eq 0) "$($files.Count) файлів .ps1: помилок розбору $($errs.Count)$(if ($errs) { ': ' + ($errs -join '; ') }); без BOM: $($bomless.Count) (PS 5.1 читає кирилицю лише з BOM)"

  # ------------------------------------------------------------------ L1: шаблон
  $tpl = Join-Path $Kit 'integrity-v2-lm.xml.template'
  $tt = [IO.File]::ReadAllText($tpl)
  [IO.File]::WriteAllText((Join-Path $W 'chk.ps1'), "`$ErrorActionPreference='Stop'; . '$PSScriptRoot\V2-lm-lib.ps1'; Test-V2LmXml -XmlPath '$tpl' -KeyMode File -Root 'C:\srv\integrity-v2'", (New-Object Text.UTF8Encoding $true))
  $chk = Invoke-Child (Join-Path $W 'chk.ps1') @()
  $comment = [regex]::Match($tt, '(?s)<!--(.*?)-->').Groups[1].Value
  $ok = $chk.Code -eq 0 -and $chk.Out -match 'PASS  XML integrity-v2-lm' -and $tt -match '--host 127\.0\.0\.1 --port 8200' -and $tt -notmatch '0\.0\.0\.0' -and
        $tt -match '<domain>NT SERVICE</domain>\s*<user>integrity-v2-lm</user>' -and $tt -notmatch '<env ' -and $tt -notmatch '--api-key ' -and $tt -notmatch '__[A-Z0-9_]+__' -and
        $tt -notmatch '[A-Za-z0-9+/]{40,}={0,2}' -and -not $comment.Contains('--') -and $tt -match '<priority>BelowNormal</priority>' -and $tt -match '<startmode>Manual</startmode>'
  try { [xml]$null = $tt; $xmlOk = $true } catch { $xmlOk = $false }
  Add-Res 'L1.template' ($ok -and $xmlOk) "Test-V2LmXml PASS; loopback 127.0.0.1:8200; NT SERVICE\integrity-v2-lm; Manual; BelowNormal; без <env>, --api-key, плейсхолдерів і довгих base64; коментар без «--»; валідний XML"

  # ------------------------------------------------------------------ L2: звіт
  $r = New-Root 'report'
  $before = Get-Listing $r
  $x = Install $r
  Add-Res 'L2.report' ($x.Code -eq 0 -and $x.Out -match 'ЗВІТ' -and (Get-Listing $r) -eq $before -and -not (Get-State $r).Services.PSObject.Properties['integrity-v2-lm']) "без -Apply: exit $($x.Code), корінь незмінний, служби немає"

  # ------------------------------------------------------------------ L3: успіх
  $r = New-Root 'ok'
  $xmlB = "$r\services\backend\integrity-v2-backend.xml"
  $orig = [IO.File]::ReadAllBytes($xmlB)
  $x = Install $r $Apply
  $ev = Get-Evidence $r 'INSTALL'
  $st = Get-State $r
  $lm = $st.Services.'integrity-v2-lm'
  [xml]$bx = Get-Content $xmlB -Raw -Encoding UTF8
  $url = @($bx.service.env | Where-Object { $_.name -eq 'V2_LM_URL' }); $key = @($bx.service.env | Where-Object { $_.name -eq 'V2_LM_API_KEY' })
  $keyFile = if (Test-Path "$r\lm\secrets\api-key.txt") { ([IO.File]::ReadAllText("$r\lm\secrets\api-key.txt")).Trim() } else { '' }
  $stripped = [regex]::Replace([IO.File]::ReadAllText($xmlB), '(?m)^[ \t]*<env name="V2_LM_(URL|API_KEY)" value="[^"]*"/>\r?\n', '')
  $sameRest = $stripped -ceq $utf8.GetString($orig)
  $evText = Get-Content (Get-ChildItem "$r\backups" -Recurse -Filter 'LM-INSTALL-EVIDENCE.json')[0].FullName -Raw
  $lmXml = [IO.File]::ReadAllText("$r\services\lm\integrity-v2-lm.xml")
  $k = if ($key.Count) { $key[0].value } else { 'none' }
  Add-Res 'L3.install' ($x.Code -eq 0 -and $ev.Result -eq 'PASS' -and $lm.State -eq 'Running' -and $lm.StartMode -eq 'Auto' -and $lm.Delayed -and $st.Services.'integrity-v2-backend'.State -eq 'Running' -and
                        $url.Count -eq 1 -and $url[0].value -eq 'http://127.0.0.1:8200' -and $key.Count -eq 1 -and $k.Length -eq 64 -and $keyFile -ceq $k -and $sameRest -and $ev.KeyMode -eq 'File' -and
                        @(Get-Content "$r\lm\LM-BIN-SHA256.txt").Count -eq 3 -and $ev.Endpoints -eq 'tcp 127.0.0.1:8200' -and $ev.Priority -eq 'BelowNormal' -and $lmXml -notmatch '<env name="LLAMA_API_KEY"' -and $lmXml -match '--api-key-file ') "exit $($x.Code); LM Running, Automatic (Delayed); backend Running; V2_LM_URL/V2_LM_API_KEY додано, решта байтів XML незмінна; ключ у файлі = ключу backend; маніфест 3 файлів; $(if ($HelpReal) { 'довідка справжнього b12180' } else { 'синтетична довідка' })$(if (-not $sameRest) { '; DIAG: XML поза V2_LM змінено' })$(if (@(Get-Content "$r\lm\LM-BIN-SHA256.txt").Count -ne 3) { '; DIAG: маніфест' })$(if ($keyFile -cne $k) { '; DIAG: ключ' })"
  Add-Res 'L3.no-secret' (-not $x.Out.Contains($k) -and -not $evText.Contains($k) -and -not $x.Out.Contains($Secret) -and -not $lmXml.Contains($k)) 'ключ не у виводі, доказі й XML служби LM; секрети backend не у виводі'
  $bk = @(Get-ChildItem "$r\backups" -Directory -Filter 'lm-install-*')
  Add-Res 'L3.backup' ($bk.Count -eq 1 -and [IO.File]::ReadAllBytes("$($bk[0].FullName)\integrity-v2-backend.xml.orig").Length -eq $orig.Length) 'копія XML backend до змін у backups\lm-install-*'
  $x2 = Install $r $Apply
  Add-Res 'L3.rerun' ($x2.Code -eq 3 -and $x2.Out -match 'уже існує') "повторне встановлення → exit $($x2.Code) (служба вже існує), нічого не змінено"

  # ------------------------------------------------------------------ L4–L5: видалення
  $before = Get-Listing $r
  $x = Uninstall $r
  Add-Res 'L4.uninst-report' ($x.Code -eq 0 -and $x.Out -match 'ПЛАН' -and (Get-Listing $r) -eq $before) "звіт: exit $($x.Code), нічого не змінено"
  $x = Uninstall $r $Apply
  $st = Get-State $r
  Add-Res 'L5.uninstall' ($x.Code -eq 0 -and -not $st.Services.PSObject.Properties['integrity-v2-lm'] -and $st.Services.'integrity-v2-backend'.State -eq 'Running' -and
                          ([IO.File]::ReadAllBytes($xmlB) -join ',') -eq ($orig -join ',') -and -not (Test-Path "$r\services\lm") -and -not (Test-Path "$r\lm\secrets") -and (Test-Path "$r\lm\bin\llama-server.exe") -and (Test-Path "$r\lm\models")) "exit $($x.Code); служби немає; XML backend = оригінал побайтово; services\lm і ключ видалено; bin/models лишились (без -RemoveFiles)"
  $x = Uninstall $r ($Apply + @('-RemoveFiles', '-RemoveModel'))
  Add-Res 'L5.remove-files' ($x.Code -eq 0 -and -not (Test-Path "$r\lm") -and (Test-Path "$r\logs\lm")) "повторно з -RemoveFiles -RemoveModel: exit $($x.Code), lm\ видалено, logs\lm лишився (ідемпотентно)"

  # ------------------------------------------------------------------ L6: невірний SHA моделі → STOP без змін
  $r = New-Root 'badsha'
  $before = Get-Listing $r
  $x = Invoke-Child (Join-Path $PSScriptRoot 'Install-V2LmService.ps1') (@('-Simulate', '-Root', $r, '-LlamaZip', $Zip, '-ModelPath', $Model, '-LlamaZipSha256', $ZipSha, '-ModelSha256', ('0' * 64)) + $Apply)
  Add-Res 'L6.bad-model-sha' ($x.Code -eq 3 -and $x.Out -match 'SHA256' -and (Get-Listing $r) -eq $before -and -not (Get-State $r).Services.PSObject.Properties['integrity-v2-lm']) "exit $($x.Code) (BLOCKED), корінь побайтово незмінний"
  $x = Invoke-Child (Join-Path $PSScriptRoot 'Install-V2LmService.ps1') (@('-Simulate', '-Root', $r, '-LlamaZip', $Zip, '-ModelPath', $Model, '-ModelSha256', $ModelSha) + $Apply)
  Add-Res 'L6.pinned-zip-sha' ($x.Code -eq 3 -and $x.Out -match 'b272cddf' -and (Get-Listing $r) -eq $before) 'без -LlamaZipSha256 діє закріплений SHA b12180 → тестовий ZIP відхилено (exit 3)'

  # ------------------------------------------------------------------ L7: збій /health → відкат
  $r = New-Root 'health' @{ LmHealth = 503 }
  $orig = [IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml")
  $x = Install $r ($Apply + @('-HealthTimeoutSec', '3'))
  $ev = Get-Evidence $r 'INSTALL'; $st = Get-State $r
  Add-Res 'L7.health-fail' ($x.Code -eq 1 -and $ev.Result -eq 'FAILED_ROLLED_BACK' -and -not $st.Services.PSObject.Properties['integrity-v2-lm'] -and $st.Services.'integrity-v2-backend'.State -eq 'Running' -and
                            ([IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml") -join ',') -eq ($orig -join ',') -and -not (Test-Path "$r\services\lm") -and -not (Test-Path "$r\lm\bin") -and -not (Test-Path "$r\lm\secrets") -and
                            (Test-Path "$r\lm\models\Qwen3-8B-Q4_K_M.gguf")) "exit $($x.Code); служба LM видалена; services\lm, lm\bin, ключ прибрано; модель лишилась; backend і XML незмінні"
  [IO.File]::WriteAllText((Join-Path (Split-Path -Parent $r) 'sim\config.json'), ((Get-Content (Join-Path (Split-Path -Parent $r) 'sim\config.json') -Raw) -replace '"LmHealth":\s*503', '"LmHealth": 200'), $utf8)
  $x = Install $r $Apply
  Add-Res 'L7.retry' ($x.Code -eq 0 -and $x.Out -match 'повторно не копіюється') "повтор після відкату: exit $($x.Code), перевірена модель повторно використана"

  # ------------------------------------------------------------------ L8: збій перезапуску backend → XML побайтово назад
  $r = New-Root 'backend'
  $orig = [IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml")
  $x = Install $r ($Apply + @('-SimulateFailAt', 'backend.restart'))
  $ev = Get-Evidence $r 'INSTALL'; $st = Get-State $r
  Add-Res 'L8.backend-fail' ($x.Code -eq 1 -and $ev.Result -eq 'FAILED_ROLLED_BACK' -and ([IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml") -join ',') -eq ($orig -join ',') -and
                             $st.Services.'integrity-v2-backend'.State -eq 'Running' -and -not $st.Services.PSObject.Properties['integrity-v2-lm']) "exit $($x.Code); XML backend = оригінал, backend Running, служби LM немає"
  $r = New-Root 'backend2' @{ BackendStartFail = $true }
  $orig = [IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml")
  $x = Install $r $Apply
  $ev = Get-Evidence $r 'INSTALL'
  Add-Res 'L8.rollback-fail' ($x.Code -eq 2 -and $ev.Result -eq 'ROLLBACK_INCOMPLETE' -and ([IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml") -join ',') -eq ($orig -join ',')) "backend не стартує й у відкаті → exit $($x.Code) ROLLBACK_INCOMPLETE; XML усе одно повернуто"

  # ------------------------------------------------------------------ L9: ключ через LLAMA_API_KEY (бінарник без --api-key-file)
  $r = New-Root 'env' @{ LmHelp = ($HelpFull -replace '(?m)^--api-key-file.*$', '') }
  $x = Install $r $Apply
  $ev = Get-Evidence $r 'INSTALL'
  $lmXml = [IO.File]::ReadAllText("$r\services\lm\integrity-v2-lm.xml")
  [xml]$bx = Get-Content "$r\services\backend\integrity-v2-backend.xml" -Raw -Encoding UTF8
  $k = @($bx.service.env | Where-Object { $_.name -eq 'V2_LM_API_KEY' })[0].value
  Add-Res 'L9.env-mode' ($x.Code -eq 0 -and $ev.KeyMode -eq 'Env' -and $lmXml.Contains("<env name=`"LLAMA_API_KEY`" value=`"$k`"/>") -and $lmXml -notmatch '--api-key-file ' -and -not (Test-Path "$r\lm\secrets") -and -not $x.Out.Contains($k)) "exit $($x.Code); ключ у LLAMA_API_KEY XML служби LM (не в аргументах), каталогу secrets немає"

  # ------------------------------------------------------------------ L10–L13: блокери
  $r = New-Root 'flag' @{ LmHelp = ($HelpFull -replace '--slots, --no-slots', '--slots') }
  $orig = [IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml")
  $x = Install $r $Apply
  Add-Res 'L10.missing-flag' ($x.Code -eq 1 -and $x.Out -match '--no-slots' -and -not (Test-Path "$r\lm\bin") -and -not (Test-Path "$r\services\lm") -and ([IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml") -join ',') -eq ($orig -join ',')) "бінарник без --no-slots → exit $($x.Code), створене прибрано"
  $r = New-Root 'busy' @{ LmPortBusy = @('tcp 0.0.0.0:8200 PID 77') }
  $before = Get-Listing $r
  $x = Install $r $Apply
  Add-Res 'L11.port-busy' ($x.Code -eq 3 -and $x.Out -match '8200' -and (Get-Listing $r) -eq $before) "порт 8200 зайнятий → exit $($x.Code), нічого не змінено"
  $r = New-Root 'wide' @{ LmEndpoints = @('tcp 0.0.0.0:8200', 'tcp 127.0.0.1:8200') }
  $x = Install $r $Apply
  $st = Get-State $r
  Add-Res 'L12.not-loopback' ($x.Code -eq 1 -and $x.Out -match 'лише tcp 127\.0\.0\.1:8200' -and -not $st.Services.PSObject.Properties['integrity-v2-lm']) "слухач поза loopback → exit $($x.Code), відкат"
  $r = New-Root 'nodec'
  $x = Invoke-Child (Join-Path $PSScriptRoot 'Install-V2LmService.ps1') @('-Simulate', '-Root', $r, '-LlamaZip', $Zip, '-ModelPath', $Model, '-Apply')
  $u = Uninstall $r @('-Apply')
  Add-Res 'L13.decision' ($x.Code -eq 3 -and $x.Out -match 'DecisionRef' -and $u.Code -eq 3) '-Apply без -DecisionRef → exit 3 (Install і Uninstall)'
} catch {
  Add-Res 'HARNESS' $false $_.Exception.Message
} finally {
  $res
  "Робочий каталог: $W"
}
if ($fail) { exit 1 } else { exit 0 }
