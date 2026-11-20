# test-caddy-config.ps1 — локальні перевірки конфігурації посилення V2 (I1, I2, I3, I11). Лише тимчасові файли в %TEMP%;
# служби, ACL, мережа, C:\srv не змінюються. caddy.exe запускається лише як adapt / validate (не run).
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-caddy-config.ps1 -Py <python із trustme і fastapi>
#          [-Caddy <caddy.exe 2.11.9>] [-DeployZip <integrity-v2-dde86e6-deploy.zip>] [-Backend <…\backend з app\api_docs.py>]
#          [-DistZip <zip зібраного frontend (dist/…)>] — сумісність dist із CSP SPA
# Код завершення: 0 — усі PASS; 1 — є FAIL або NOT RUN.
param(
  [Parameter(Mandatory)] [string] $Py,
  [string] $Caddy,
  [string] $DeployZip,
  [string] $Backend,
  [string] $DistZip
)
if (-not $Backend) { $Backend = Join-Path $PSScriptRoot '..\..\backend' }
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'V2-install-common.ps1')
$ErrorActionPreference = 'Stop'
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-14} {1,-7} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
function Add-NotRun([string]$id, [string]$d) { $res.Add(('{0,-14} {1,-7} {2}' -f $id, 'NOT RUN', $d)) }
function Test-Stop([scriptblock]$b, [string]$like = '*') { try { $null = & $b; $false } catch { "$($_.Exception.Message)" -like "STOP:*" -and "$($_.Exception.Message)" -like $like } }
function Prop($o, [string[]]$path) { foreach ($n in $path) { if ($null -eq $o) { return $null }; $p = $o.PSObject.Properties[$n]; if (-not $p) { return $null }; $o = $p.Value }; $o }
function Get-Handlers($Node, [string]$Ctx, $Acc) {
  if ($null -eq $Node) { return }
  if ($Node -is [System.Array]) { foreach ($x in $Node) { Get-Handlers $x $Ctx $Acc }; return }
  if ($Node -isnot [System.Management.Automation.PSCustomObject]) { return }
  $m = Prop $Node 'match'
  if ($m) { $paths = @(@($m) | ForEach-Object { Prop $_ 'path' } | Where-Object { $_ }); if ($paths.Count) { $Ctx = ($paths -join ',') } }
  if (Prop $Node 'handler') { $Acc.Add([pscustomobject]@{ Ctx = $Ctx; H = $Node }) }
  foreach ($p in $Node.PSObject.Properties) { if ($p.Name -ne 'match') { Get-Handlers $p.Value $Ctx $Acc } }
}
function Invoke-Native([string]$Exe, [string[]]$A) {
  $psi = New-Object Diagnostics.ProcessStartInfo $Exe, ((@($A | ForEach-Object { ConvertTo-V2Arg $_ })) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(120000)) { $p.Kill(); throw "тайм-аут $Exe" }
  [pscustomobject]@{ Code = $p.ExitCode; Out = $o.Result; Err = $e.Result }
}

$K = $PSScriptRoot
$tpl = Join-Path $K 'deploy\Caddyfile'
$xmlTpl = Join-Path $K 'integrity-v2-backend.xml.template'
$prodHost = 'desktop-jtgc2sg.taild5c033.ts.net'
$tmp = Join-Path $env:TEMP ('v2-caddy-cfg-' + [guid]::NewGuid().ToString('N').Substring(0, 8)); $null = New-Item -ItemType Directory $tmp
$utf8 = New-Object Text.UTF8Encoding($false, $true)
try {
  # C1: шаблон — UTF-8 без BOM, LF, рівно одне ім'я хоста і один рядок bind (вхід New-V2TargetConfig)
  $tb = [IO.File]::ReadAllBytes($tpl); $tt = $utf8.GetString($tb)
  Add-Res 'C1.template' (-not ($tb[0] -eq 0xEF -and $tb[1] -eq 0xBB) -and -not $tt.Contains("`r") -and [regex]::Matches($tt, [regex]::Escape($prodHost)).Count -eq 1 -and
                         [regex]::Matches($tt, [regex]::Escape('bind 100.111.221.74 [fd7a:115c:a1e0::ef01:dddc]')).Count -eq 1) 'шаблон Caddyfile: UTF-8 без BOM, LF, 1 хост, 1 bind'

  # C2: New-V2TargetConfig (production, -UseFileTls) → форма TLSFIX5; кирилиця коментарів побайтово збережена (I2)
  $out = Join-Path $tmp 'target'
  $null = New-V2TargetConfig -CaddySource $tpl -BackendSource $xmlTpl -Destination $out -HostName $prodHost -Addresses @('100.111.221.74') -UseFileTls
  $gen = [IO.File]::ReadAllBytes((Join-Path $out 'Caddyfile')); $gt = $utf8.GetString($gen)
  $commentsSame = (($tt -split "`n" | Where-Object { $_ -match '^\s*#' }) -join "`n") -eq (($gt -split "`n" | Where-Object { $_ -match '^\s*#' }) -join "`n")
  Add-Res 'C2.tlsfix5' ($gt.Contains("`tauto_https off`n") -and $gt.Contains("`tbind 100.111.221.74`n`ttls C:/srv/integrity-v2/caddy/tls/site.crt C:/srv/integrity-v2/caddy/tls/site.key`n") -and
                        -not $gt.Contains('fd7a:') -and -not $gt.Contains('disable_redirects') -and $commentsSame -and -not ($gen[0] -eq 0xEF)) 'цільова форма: auto_https off, лише IPv4, файлова TLS-пара; коментарі UTF-8 без змін'

  # C3: регресія I2 — кирилиця в UTF-8 не перекодовується (раніше cp1251 → подвійне кодування «вЂ”»)
  $src3 = Join-Path $tmp 'utf8.Caddyfile'
  [IO.File]::WriteAllText($src3, "# Коментар — тире й «лапки» (UTF-8)`n{`n`tauto_https disable_redirects`n}`n${prodHost}:443 {`n`tbind 100.111.221.74 [fd7a:115c:a1e0::ef01:dddc]`n}`n", $utf8)
  $null = New-V2TargetConfig -CaddySource $src3 -BackendSource $xmlTpl -Destination (Join-Path $tmp 't3') -HostName $prodHost -Addresses @('100.111.221.74') -UseFileTls
  $o3 = [IO.File]::ReadAllText((Join-Path $tmp 't3\Caddyfile'), $utf8)
  Add-Res 'C3.utf8' ($o3.StartsWith('# Коментар — тире й «лапки» (UTF-8)') -and -not $o3.Contains('вЂ')) 'I2: коментар з кирилицею й «—» після генерації побайтово той самий'
  $bom = Join-Path $tmp 'bom.Caddyfile'; [IO.File]::WriteAllBytes($bom, [byte[]](0xEF, 0xBB, 0xBF) + [IO.File]::ReadAllBytes($src3))
  $cp = Join-Path $tmp 'cp1251.Caddyfile'; [IO.File]::WriteAllBytes($cp, [Text.Encoding]::GetEncoding(1251).GetBytes([IO.File]::ReadAllText($src3, $utf8)))
  Add-Res 'C3.reject' ((Test-Stop { New-V2TargetConfig -CaddySource $bom -BackendSource $xmlTpl -Destination (Join-Path $tmp 'tb') -HostName $prodHost -Addresses @('100.111.221.74') -UseFileTls } '*без BOM*') -and
                       (Test-Stop { New-V2TargetConfig -CaddySource $cp -BackendSource $xmlTpl -Destination (Join-Path $tmp 'tc') -HostName $prodHost -Addresses @('100.111.221.74') -UseFileTls } '*не є коректним UTF-8*')) 'I2: BOM або не-UTF-8 (cp1251) → STOP до запису'

  # C4: preflight -PrintTargetCaddyfile дає побайтово той самий цільовий текст, що й New-V2TargetConfig
  $pf = Invoke-Native "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $K 'deploy\V2-release-preflight.ps1'), '-PrintTargetCaddyfile', $tpl)
  Add-Res 'C4.preflight' ($pf.Code -eq 0 -and $pf.Out -eq $gt) "I11: перетворення preflight = New-V2TargetConfig (exit $($pf.Code))"

  # C5–C6: caddy adapt / validate
  if (-not $Caddy) { Add-NotRun 'C5.adapt' 'немає -Caddy'; Add-NotRun 'C6.validate' 'немає -Caddy' }
  else {
    $null = Assert-V2FileHash -Path $Caddy -Sha256 $CaddyRefSha256 -Label 'caddy.exe'
    $a0 = Invoke-Native $Caddy @('adapt', '--config', $tpl, '--adapter', 'caddyfile')
    $a1 = Invoke-Native $Caddy @('adapt', '--config', (Join-Path $out 'Caddyfile'), '--adapter', 'caddyfile')
    $cfg = $a1.Out | ConvertFrom-Json
    $srv = @((Prop $cfg 'apps', 'http', 'servers').PSObject.Properties | ForEach-Object Value)
    $hs = New-Object System.Collections.Generic.List[object]; Get-Handlers $srv '' $hs
    $rp = @($hs | Where-Object { (Prop $_.H 'handler') -eq 'reverse_proxy' })
    $rpOk = $rp.Count -eq 4 -and -not @($rp | Where-Object { (Prop $_.H 'transport', 'keep_alive', 'idle_timeout') -ne 4000000000 -or @(Prop $_.H 'headers', 'request', 'delete') -notcontains 'X-Role' -or ((@(Prop $_.H 'upstreams') | ForEach-Object { Prop $_ 'dial' }) -join ',') -ne '127.0.0.1:8100' }).Count
    $rb = @($hs | Where-Object { (Prop $_.H 'handler') -eq 'request_body' } | ForEach-Object { "$($_.Ctx)=$(Prop $_.H 'max_size')" } | Sort-Object)
    $cspOf = { param($ctx) @($hs | Where-Object { $_.Ctx -eq $ctx -and (Prop $_.H 'handler') -eq 'headers' } | ForEach-Object { @(Prop $_.H 'response', 'set', 'Content-Security-Policy') } | Where-Object { $_ }) }
    $spa = @(& $cspOf ''); $assets = @(& $cspOf '/assets/*'); $docs = @(& $cspOf '/docs*'); $api = @(& $cspOf '/api/*')
    $deferred = -not @($hs | Where-Object { (Prop $_.H 'handler') -eq 'headers' -and (Prop $_.H 'response', 'set', 'Content-Security-Policy') -and (Prop $_.H 'response', 'deferred') -ne $true }).Count
    $logs = Prop $cfg 'logging', 'logs', 'default'
    $glob = @($hs | Where-Object { (Prop $_.H 'response', 'set', 'Strict-Transport-Security') })
    Add-Res 'C5.adapt' ($a0.Code -eq 0 -and $a1.Code -eq 0) "caddy adapt: шаблон exit $($a0.Code), цільова форма exit $($a1.Code)"
    Add-Res 'C5.listen' ((@($srv | ForEach-Object { Prop $_ 'listen' }) -join ',') -eq '100.111.221.74:443' -and (Prop $srv[0] 'automatic_https', 'disable') -eq $true -and (Prop $cfg 'admin', 'disabled') -eq $true -and
                         (@(Prop $srv[0] 'protocols') -join ',') -eq 'h1,h2' -and -not (Prop $srv[0] 'logs') -and (Prop $cfg 'apps', 'tls', 'certificates', 'load_files')) 'лише 100.111.221.74:443, auto_https off, admin off, h1/h2, без access log, файлова TLS-пара'
    Add-Res 'C5.logs' ((@(Prop $logs 'exclude') -join ',') -eq 'http.log.error,http.handlers.reverse_proxy,http.stdlib' -and -not (Prop $logs 'include') -and (@((Prop $cfg 'logging', 'logs').PSObject.Properties).Count -eq 1)) 'журнал default виключає http.log.error, reverse_proxy, http.stdlib (IP/URI)'
    Add-Res 'C5.proxy' $rpOk 'усі 4 reverse_proxy: 127.0.0.1:8100, keepalive 4s, header_up -X-Role'
    Add-Res 'C5.body' (($rb -join ';') -eq '/api/*=256000;/v2/*=256000') "request_body max_size: $($rb -join '; ')"
    Add-Res 'C5.csp' ($spa.Count -eq 1 -and $assets.Count -eq 1 -and $spa[0] -eq $assets[0] -and $spa[0] -match "^default-src 'self'; script-src 'self'; style-src 'self';" -and $spa[0] -notmatch 'unsafe' -and
                      $spa[0].Contains("object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'") -and $docs.Count -eq 1 -and $docs[0] -match "script-src 'self' 'sha256-[A-Za-z0-9+/]{43}='" -and
                      $docs[0] -notmatch 'unsafe-eval' -and $api.Count -eq 1 -and $api[0].StartsWith("default-src 'none'") -and $deferred) 'CSP: SPA і /assets однакові без unsafe-*; /docs — sha256 скрипта; API — default-src none; усі CSP відкладені (перекривають upstream)'
    Add-Res 'C5.headers' ($glob.Count -eq 1 -and @(Prop $glob[0].H 'response', 'delete') -contains 'Server' -and (Prop $glob[0].H 'response', 'set', 'Permissions-Policy') -and
                          @(Prop $glob[0].H 'response', 'set', 'X-Frame-Options') -contains 'DENY' -and @(Prop $glob[0].H 'response', 'set', 'Referrer-Policy') -contains 'same-origin' -and
                          @(Prop $glob[0].H 'response', 'set', 'X-Content-Type-Options') -contains 'nosniff' -and @($hs | Where-Object { @(Prop $_.H 'request', 'delete') -contains 'X-Role' }).Count -eq 1 -and
                          @($hs | Where-Object { $_.Ctx -eq '/redoc*' -and (Prop $_.H 'status_code') -eq 404 }).Count -eq 1) 'HSTS, nosniff, DENY, Referrer-Policy, Permissions-Policy, -Server; X-Role видаляється (request_header + 4 header_up); /redoc 404'
    # C6: validate з тимчасовою самопідписаною парою (шляхи C:/srv/integrity-v2/ → тимчасовий корінь); нічого не записується
    $root = Join-Path $tmp 'root'; foreach ($d in 'caddy\tls', 'caddy\data', 'app\frontend\dist') { $null = New-Item -ItemType Directory -Path (Join-Path $root $d) -Force }
    $mk = Invoke-Native $Py @('-I', '-B', '-c', 'import sys, trustme; ca = trustme.CA(); c = ca.issue_cert(sys.argv[3]); c.cert_chain_pems[0].write_to_path(sys.argv[1]); c.private_key_pem.write_to_path(sys.argv[2])', (Join-Path $root 'caddy\tls\site.crt'), (Join-Path $root 'caddy\tls\site.key'), $prodHost)
    $vf = Join-Path $tmp 'validate.Caddyfile'; [IO.File]::WriteAllText($vf, $gt.Replace('C:/srv/integrity-v2/', ($root -replace '\\', '/') + '/'), $utf8)
    $before = @(Get-ChildItem -LiteralPath $root -Recurse -Force | ForEach-Object FullName)
    $saved = @{}; foreach ($n in 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'APPDATA') { $saved[$n] = [Environment]::GetEnvironmentVariable($n, 'Process'); [Environment]::SetEnvironmentVariable($n, (Join-Path $tmp 'xdg'), 'Process') }
    $vt = Join-Path $tmp 'validate-template.Caddyfile'; [IO.File]::WriteAllText($vt, $tt.Replace('C:/srv/integrity-v2/', ($root -replace '\\', '/') + '/'), $utf8)
    try { $v = Invoke-Native $Caddy @('validate', '--config', $vf, '--adapter', 'caddyfile'); $v0 = Invoke-Native $Caddy @('validate', '--config', $vt, '--adapter', 'caddyfile') } finally { foreach ($n in $saved.Keys) { [Environment]::SetEnvironmentVariable($n, $saved[$n], 'Process') } }
    $after = @(Get-ChildItem -LiteralPath $root -Recurse -Force | ForEach-Object FullName)
    Add-Res 'C6.validate' ($mk.Code -eq 0 -and $v.Code -eq 0 -and (($v.Out + $v.Err) -match 'Valid configuration') -and $v0.Code -eq 0 -and (($v0.Out + $v0.Err) -match 'Valid configuration') -and -not @(Compare-Object $before $after).Count -and -not (Test-Path (Join-Path $tmp 'xdg'))) "caddy validate: цільова форма TLSFIX5 з тимчасовою TLS-парою exit $($v.Code), шаблон exit $($v0.Code); файлів не створено"
  }

  # C7: sha256 у CSP /docs = хеш вбудованого скрипта сторінки /docs, згенерованої FastAPI з параметрами api_docs.swagger_ui
  $docsPy = 'import sys, re, hashlib, base64; sys.path.insert(0, sys.argv[1]); from app import api_docs; import fastapi; h = api_docs.swagger_ui().body.decode("utf-8"); s = [m.group(1) for m in re.finditer(r"<script>(.*?)</script>", h, re.S)]; print(fastapi.__version__, len(s), "sha256-" + base64.b64encode(hashlib.sha256(s[0].encode("utf-8")).digest()).decode())'
  if (-not (Test-Path -LiteralPath (Join-Path $Backend 'app\api_docs.py'))) { Add-NotRun 'C7.docs-hash' "немає $Backend\app\api_docs.py" }
  else {
    $env:INTEGRITY_DB = Join-Path $tmp 'docs-i.db'; $env:V2_AUTH_DB = Join-Path $tmp 'docs-a.db'
    try { $dh = Invoke-Native $Py @('-I', '-B', '-c', $docsPy, (Resolve-Path $Backend).Path) } finally { Remove-Item Env:INTEGRITY_DB, Env:V2_AUTH_DB }
    $fields = "$($dh.Out)".Trim() -split ' '
    Add-Res 'C7.docs-hash' ($dh.Code -eq 0 -and $fields.Count -eq 3 -and $fields[1] -eq '1' -and $tt.Contains("'$($fields[2])'")) "FastAPI $($fields[0]): вбудованих скриптів $($fields[1]); $($fields[2]) у CSP /docs шаблону"
  }

  # C8 (I3): --no-proxy-headers вимагає TRUSTED_PROXIES=127.0.0.1,::1
  $xt = [IO.File]::ReadAllText($xmlTpl, $utf8)
  $mut = @(
    @('C8.missing', ([regex]::Replace($xt, '(?m)^[ \t]*<env name="TRUSTED_PROXIES"[^\r\n]*\r?\n', '')), $false),
    @('C8.value', $xt.Replace('value="127.0.0.1,::1"', 'value="127.0.0.1"'), $false),
    @('C8.double', $xt.Replace('  <env name="TRUSTED_PROXIES" value="127.0.0.1,::1"/>', "  <env name=`"TRUSTED_PROXIES`" value=`"127.0.0.1,::1`"/>`n  <env name=`"TRUSTED_PROXIES`" value=`"127.0.0.1,::1`"/>"), $false),
    @('C8.noflag', ([regex]::Replace($xt.Replace(' --no-proxy-headers', ''), '(?m)^[ \t]*<env name="TRUSTED_PROXIES"[^\r\n]*\r?\n', '')), $true))
  Add-Res 'C8.template' ((@(Test-V2WinswXml -XmlPath $xmlTpl -Name integrity-v2-backend -WinswVersion '2.12.0' -AllowPlaceholders))[-1] -like 'PASS*') 'шаблон backend XML: --no-proxy-headers + TRUSTED_PROXIES=127.0.0.1,::1 → PASS'
  foreach ($m in $mut) {
    $p = Join-Path $tmp "$($m[0]).xml"; [IO.File]::WriteAllText($p, $m[1], $utf8)
    $ok = if ($m[2]) { (@(Test-V2WinswXml -XmlPath $p -Name integrity-v2-backend -WinswVersion '2.12.0' -AllowPlaceholders))[-1] -like 'PASS*' } else { Test-Stop { Test-V2WinswXml -XmlPath $p -Name integrity-v2-backend -WinswVersion '2.12.0' -AllowPlaceholders } '*TRUSTED_PROXIES=127.0.0.1,::1*' }
    Add-Res $m[0] ($m[1] -ne $xt -and $ok) $(if ($m[2]) { 'без --no-proxy-headers TRUSTED_PROXIES не вимагається' } else { 'мутація TRUSTED_PROXIES → STOP' })
  }

  # C10: зібраний dist сумісний із CSP SPA (без вбудованих скриптів/стилів/обробників, без data:-ресурсів, лише той самий origin)
  if (-not $DistZip) { Add-NotRun 'C10.dist-csp' 'немає -DistZip' }
  else {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $dz = Join-Path $tmp 'dist'; [IO.Compression.ZipFile]::ExtractToDirectory($DistZip, $dz)
    $idx = @(Get-ChildItem -LiteralPath $dz -Recurse -Filter 'index.html')
    $bad = New-Object System.Collections.Generic.List[string]
    if ($idx.Count -ne 1) { $bad.Add("index.html: $($idx.Count)") }
    else {
      $h = [IO.File]::ReadAllText($idx[0].FullName)
      foreach ($m in [regex]::Matches($h, '(?is)<script\b([^>]*)>(.*?)</script>')) { if ($m.Groups[1].Value -notmatch '\bsrc=' -or $m.Groups[2].Value.Trim()) { $bad.Add('вбудований <script>') } }
      if ($h -match '(?i)<style\b|\sstyle=|\son[a-z]+=') { $bad.Add('вбудований стиль або обробник подій') }
      foreach ($m in [regex]::Matches($h, '(?i)\b(?:src|href)="([^"]+)"')) { if ($m.Groups[1].Value -notmatch '^/[^/]') { $bad.Add("ресурс не з того самого origin: $($m.Groups[1].Value)") } }
    }
    foreach ($f in @(Get-ChildItem -LiteralPath $dz -Recurse -File -Include '*.css', '*.js')) {
      $x = [IO.File]::ReadAllText($f.FullName)
      if ($x -match 'data:(image|font|application)/' -or $x -match '(?i)url\(\s*["'']?data:') { $bad.Add("$($f.Name): data:-ресурс") }
      if ($f.Extension -eq '.css' -and $x -match '(?i)@import|url\(\s*["'']?https?:') { $bad.Add("$($f.Name): зовнішній CSS-ресурс") }
      if ($f.Extension -eq '.js' -and $x -match '\beval\(|new Function\(') { $bad.Add("$($f.Name): eval / new Function") }
    }
    $svg = @(Get-ChildItem -LiteralPath $dz -Recurse -File -Filter '*.svg' | Where-Object { [IO.File]::ReadAllText($_.FullName) -match '(?i)<script|\son[a-z]+=' })
    if ($svg.Count) { $bad.Add("SVG зі скриптом: $($svg.Name -join ', ')") }
    Add-Res 'C10.dist-csp' (-not $bad.Count) "dist $(Split-Path $DistZip -Leaf): $(if ($bad.Count) { $bad -join '; ' } else { "сумісний із CSP SPA (img-src 'self', без unsafe-*, без data:)" })"
  }

  # C9 (I11): повний preflight на копії пакета dde86e6 з новим шаблоном — розділ Caddy без BLOCKED; мутації → BLOCKED
  if (-not $DeployZip -or -not $Caddy) { Add-NotRun 'C9.preflight' 'немає -DeployZip або -Caddy' }
  else {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $runPf = {
      param([string]$Name, [string]$CaddyText)
      $pk = Join-Path $tmp "pkg-$Name"; [IO.Compression.ZipFile]::ExtractToDirectory($DeployZip, $pk)
      [IO.File]::WriteAllText((Join-Path $pk 'Caddyfile'), $CaddyText, $utf8)
      $sums = Join-Path $tmp "sums-$Name.txt"
      [IO.File]::WriteAllLines($sums, [string[]]@(Get-ChildItem -LiteralPath $pk -File | Where-Object Name -ne 'SHA256SUMS.txt' | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName).Hash.ToLower())  $($_.Name)" }))
      $r = Invoke-Native "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $K 'deploy\V2-release-preflight.ps1'), '-PackageDir', $pk, '-ApprovedSums', $sums, '-Python', $Py, '-Caddy', $Caddy)
      @($r.Out -split "`r?`n" | Where-Object { $_ -match '^(BLOCKED|INFO): ' })
    }
    $good = & $runPf 'good' $tt
    Add-Res 'C9.preflight' (-not @($good | Where-Object { $_ -match '^BLOCKED: Caddy' }).Count -and @($good | Where-Object { $_ -like 'INFO: Caddy: v2.11.9*TLSFIX5 OK*100.111.221.74:443' }).Count -eq 1) 'розділ Caddy без BLOCKED; цільова форма TLSFIX5 OK (вивід дочірнього preflight — кодова сторінка консолі, порівнюються ASCII-фрагменти)'
    $bad = & $runPf 'nolog' ($tt.Replace(' http.stdlib', '').Replace("max_size 256KB", "max_size 10MB"))
    Add-Res 'C9.mutation' (@($bad | Where-Object { $_ -like 'BLOCKED: Caddy:*http.log.error*' }).Count -eq 1 -and @($bad | Where-Object { $_ -like 'BLOCKED: Caddy:*request_body max_size*' }).Count -eq 2) 'мутації (http.stdlib не виключено, max_size 10MB) → BLOCKED'
  }
} catch {
  $res.Add(('{0,-14} {1,-7} {2}' -f 'ERROR', 'FAIL', $_.Exception.Message))
} finally {
  Remove-Item -LiteralPath $tmp -Recurse -Force
}
$res
$fail = @($res | Where-Object { $_ -match '\s(FAIL|NOT RUN)\s' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match '\sPASS\s' }).Count) PASS, $fail FAIL/NOT RUN"
if ($fail) { exit 1 } else { exit 0 }
