# static-upgrade.ps1 — статичні перевірки скриптів upgrade\ (без запуску): розбір PowerShell, кодування, неінтерактивність,
# заборонені команди, межі видалення, відсутність виводу XML служби, закріплені імена завдань.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\static-upgrade.ps1   Код: 0 — усі PASS; 1 — є FAIL.
$ErrorActionPreference = 'Stop'
$D = $PSScriptRoot
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-5} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
$files = @(Get-ChildItem -LiteralPath $D -Recurse -Filter '*.ps1' | Sort-Object FullName)
$prod = @($files | Where-Object { $_.Name -notmatch '^(test-|static-)' -and $_.DirectoryName -notlike '*\sim' })
$asts = @{}; $errs = @()
foreach ($f in $files) { $t = $null; $e = $null; $asts[$f.FullName] = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t, [ref]$e); if ($e.Count) { $errs += "$($f.Name): $($e[0].Message)" } }
Add-Res 'U1' ($errs.Count -eq 0) "розбір PowerShell: файлів $($files.Count), помилок $($errs.Count) $($errs -join '; ')"
$enc = @(foreach ($f in $files) { $b = [IO.File]::ReadAllBytes($f.FullName); $non = @($b | Where-Object { $_ -gt 127 }).Count; if ($non -and -not ($b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)) { "$($f.Name): не-ASCII без BOM" }; if (@($b | Where-Object { $_ -lt 32 -and $_ -notin 9, 10, 13 }).Count) { "$($f.Name): керівні байти" } })
Add-Res 'U2' ($enc.Count -eq 0) "кодування: UTF-8 з BOM для не-ASCII (Windows PowerShell 5.1), без керівних байтів $($enc -join '; ')"
$cmds = @{}; foreach ($f in $prod) { $cmds[$f.Name] = @($asts[$f.FullName].FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $_ } | Sort-Object -Unique) }
$inter = @(foreach ($k in $cmds.Keys) { foreach ($c in $cmds[$k]) { if ($c -in 'Read-Host', 'Get-Credential', 'Out-GridView', 'Pause', 'Show-Command') { "${k}: $c" } } })
Add-Res 'U3' ($inter.Count -eq 0) "неінтерактивність (SSH): Read-Host/Get-Credential/Out-GridView відсутні $($inter -join '; ')"
$forbid = @(foreach ($k in $cmds.Keys) { foreach ($c in $cmds[$k]) { if ($c -in 'Set-Acl', 'New-Service', 'Remove-Service', 'Set-Service', 'Restart-Service', 'Unregister-ScheduledTask', 'Set-ItemProperty', 'New-NetFirewallRule', 'Set-NetFirewallRule', 'Stop-Process', 'Start-Transcript', 'Invoke-Expression') { "${k}: $c" } } })
Add-Res 'U4' ($forbid.Count -eq 0) "заборонені команди (Set-Acl, *-Service, Unregister-ScheduledTask, реєстр, Firewall, Stop-Process, Invoke-Expression): $($forbid -join '; ')"
$src = @{}; foreach ($f in $prod) { $src[$f.Name] = [IO.File]::ReadAllText($f.FullName) }
$noRestart = -not @($src.Keys | Where-Object { $src[$_] -match 'V2-release-TLSFIX5' -and $src[$_] -match '(?i)Remove-Item[^\r\n]*V2-release' }).Count -and $src['Protect-V2Leftovers.ps1'].Contains("'^V2-release-'") -and $src['Protect-V2Leftovers.ps1'] -notmatch 'Remove-Item'
Add-Res 'U5' $noRestart 'каталоги TLSFIX5/V1-recovery не видаляються й не змінюються; Protect-V2Leftovers не видаляє файлів'
$dis = $src['Disable-V2InstallLeftoverTasks.ps1']
Add-Res 'U6' ($dis.Contains("'^Codex-V2-[A-Za-z0-9._-]+$'") -and $dis.Contains("-match '^Integrity-V2-'") -and $dis -notmatch 'Unregister-ScheduledTask' -and $src['Register-V2BackupTask.ps1'].Contains("`$TaskName = 'Integrity-V2-DB-Backup'")) 'завдання: вимикаються лише Codex-V2-*, Integrity-V2-* заборонено, жодного видалення; резервна копія — Integrity-V2-DB-Backup'
$xmlOut = @(foreach ($k in $src.Keys) { [regex]::Matches($src[$k], '(?im)^(?!\s*#).*(Get-Content|ReadAllText)[^\r\n]*integrity-v2-backend\.xml[^\r\n]*$') | ForEach-Object { "${k}: $($_.Value.Trim())" } })
Add-Res 'U7' ($xmlOut.Count -eq 0) "XML служби не читається в текст для виводу (лише байти цілком, SHA256 і окремі елементи через функції бібліотеки) $($xmlOut -join '; ')"
$lib = $src['V2-upgrade-lib.ps1']; $up = $src['Update-V2InPlace.ps1']
$order = @('stop.backend', 'backup.db', 'xml.workdir', 'venv.pip', 'db.migrate', 'db.verify', 'start.backend') | ForEach-Object { $up.IndexOf("Step '$_'") }
Add-Res 'U8' (-not @($order | Where-Object { $_ -lt 0 }).Count -and (($order | Sort-Object) -join ',') -eq ($order -join ',') -and $up.Contains("-ArgList @('-B', '-E', '-s', '-X', 'utf8', '-m', 'app.migrations', '--apply', '--confirm-verified-backup')") -and $up.Contains('V2_SECRET_KEY = $null')) 'Update: зупинка → перевірена копія → XML → venv → явна міграція (без V2_SECRET_KEY) → строгі перевірки → старт'
Add-Res 'U9' ($lib.Contains("Set-V2UpStartMode `$V2UpBackend 'disabled'") -and $lib.IndexOf("RESTORE-IN-PROGRESS-") -lt $lib.IndexOf("'restore', (Join-Path `$Dir `$it.File)") -and $lib.IndexOf('Assert-V2UpBackupItems -Dir $Dir -Items $Items') -lt $lib.IndexOf("RESTORE-IN-PROGRESS-")) 'відновлення БД: перевірка копій → Disabled → RESTORE-IN-PROGRESS → restore у новий файл → RESTORE-OK/FAILED'
Add-Res 'U10' ($up.Contains("'--require-hashes'") -and $up.Contains("'--no-index'") -and $up.Contains("'--isolated'") -and $up.Contains("'--only-binary', ':all:'")) 'pip: --isolated --no-index --require-hashes --only-binary :all:'
$res
$fail = @($res | Where-Object { $_ -match ' FAIL ' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match ' PASS ' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
