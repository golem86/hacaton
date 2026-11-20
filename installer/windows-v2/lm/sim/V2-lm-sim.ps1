# V2-lm-sim.ps1 — ЛИШЕ ДЛЯ ТЕСТІВ: адаптери симуляції для Install/Uninstall-V2LmService (-Simulate).
# Підключається на рівні скрипта ПІСЛЯ V2-lm-lib.ps1 і upgrade\sim\V2-upgrade-sim.ps1 (стан «служб» — <корінь>\..\sim\state.json).
# Додаткові ключі <корінь>\..\sim\config.json: LmHelp (текст --help), LmHealth (код /health, типово 200), LmEndpoints (масив),
# FreeMemory, TotalMemory, LmPortBusy (масив слухачів 8200 до встановлення), BackendStartFail (true → старт backend падає).
# Нічого в системі не змінює: служби не реєструються, ACL не змінюються, процеси не запускаються, мережа не використовується.

function Get-V2LmSimCfg([string]$Name, $Default) {
  $c = Get-V2UpSimConfig
  $p = $c.PSObject.Properties[$Name]
  if ($p -and $null -ne $p.Value) { $p.Value } else { $Default }
}
function Get-V2LmFreeMemory { [int64](Get-V2LmSimCfg 'FreeMemory' 12GB) }
function Get-V2LmTotalMemory { [int64](Get-V2LmSimCfg 'TotalMemory' 24GB) }
function Get-V2LmListeners {
  $s = Get-V2UpService $V2LmName
  if ($s -and $s.State -eq 'Running') { return @("tcp 127.0.0.1:$V2LmPort PID 4242") }
  @(Get-V2LmSimCfg 'LmPortBusy' @())
}
function Assert-V2LmWinswSource([string]$Path) { if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-V2 "немає $Path" }; "SIM   WinSW $Path (SHA/версія не перевіряються)" }
function Get-V2LmHelpText([string]$Exe) {
  if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { Stop-V2 "немає $Exe" }
  [string](Get-V2LmSimCfg 'LmHelp' '')
}
function Install-V2LmScm([scriptblock]$OnCreated) {
  if (Get-V2UpService $V2LmName) { Stop-V2 "служба $V2LmName уже існує" }
  if (-not (Test-Path -LiteralPath $V2Services[$V2LmName].Exe)) { Stop-V2 'немає wrapper LM' }
  $st = Get-V2UpSimState
  $st.Services | Add-Member -NotePropertyName $V2LmName -NotePropertyValue ([pscustomobject]@{ State = 'Stopped'; StartMode = 'Manual'; Delayed = $false; DependsOn = @() })
  Save-V2UpSimState $st; Add-V2UpSimEvent "install $V2LmName"
  if ($OnCreated) { & $OnCreated $V2LmName }
  "SIM   служба $V2LmName зареєстрована"
}
function Uninstall-V2LmScm {
  $s = Get-V2UpService $V2LmName
  if (-not $s) { return "INFO  служби $V2LmName немає" }
  if ($s.State -ne 'Stopped') { Stop-V2 "${V2LmName}: видалення лише зі стану Stopped" }
  $st = Get-V2UpSimState
  $st.Services.PSObject.Properties.Remove($V2LmName)
  Save-V2UpSimState $st; Add-V2UpSimEvent "uninstall $V2LmName"
  "SIM   служба $V2LmName видалена"
}
function Start-V2LmService {
  $s = Assert-V2UpServiceIdentity $V2LmName
  if ($s.State -ne 'Stopped') { Stop-V2 "${V2LmName}: старт лише зі стану Stopped" }
  $null = Test-V2LmXml -XmlPath "$V2Root\services\lm\$V2LmName.xml"
  foreach ($f in "$V2Root\lm\bin\llama-server.exe", "$V2Root\lm\models\$V2LmModelFile") { if (-not (Test-Path -LiteralPath $f)) { Stop-V2 "SIM LM: немає $f" } }
  Set-V2UpSimService $V2LmName @{ State = 'Running' }; Add-V2UpSimEvent "start $V2LmName"
  "SIM   $V2LmName запущено"
}
function Get-V2LmEndpoints { @(Get-V2LmSimCfg 'LmEndpoints' @("tcp 127.0.0.1:$V2LmPort")) }
function Get-V2LmPriority { [xml]$x = Get-Content -LiteralPath "$V2Root\services\lm\$V2LmName.xml" -Raw -Encoding UTF8; [string]$x.service.priority }
function Get-V2LmFirewallRuleCount([string]$Program) { 0 }
# Ключ, який реально отримала б служба: файл --api-key-file або LLAMA_API_KEY з XML служби LM
function Get-V2LmSimServiceKey {
  $f = "$V2Root\$V2LmKeyFileRel"
  if (Test-Path -LiteralPath $f) { return ([IO.File]::ReadAllText($f)).Trim() }
  [xml]$x = Get-Content -LiteralPath "$V2Root\services\lm\$V2LmName.xml" -Raw -Encoding UTF8
  $e = @($x.SelectNodes('/service/env') | Where-Object { $_.GetAttribute('name') -eq 'LLAMA_API_KEY' })
  if ($e.Count) { $e[0].GetAttribute('value') } else { $null }
}
function Get-V2LmHttpStatus([string]$Path, [hashtable]$Headers = @{}) {
  $s = Get-V2UpService $V2LmName
  if (-not $s -or $s.State -ne 'Running') { return 0 }
  if ($Path -eq '/health') { return [int](Get-V2LmSimCfg 'LmHealth' 200) }
  $k = Get-V2LmSimServiceKey
  if ($k -and $Headers.ContainsKey('Authorization') -and $Headers['Authorization'] -ceq "Bearer $k") { 200 } else { 401 }
}
# Backend: старт перевіряє валідність XML (як WinSW) і, якщо задано, ключ LM у XML backend = ключу служби LM
function Start-V2UpService([string]$Name) {
  $s = Assert-V2UpServiceIdentity $Name
  if ($s.State -ne 'Stopped') { Stop-V2 "${Name}: старт лише зі стану Stopped (зараз $($s.State))" }
  if ($Name -eq $V2UpBackend) {
    $null = Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name $V2UpBackend -WinswVersion $WinswRefVersion
    if ([bool](Get-V2LmSimCfg 'BackendStartFail' $false)) { Stop-V2 'SIM backend: імітований збій старту' }
  }
  Set-V2UpSimService $Name @{ State = 'Running' }; Add-V2UpSimEvent "start $Name"
  "SIM   $Name запущено"
}
