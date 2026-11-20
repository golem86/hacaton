# Build-V2CleanPackage.ps1 — збирає пакет Clean Install / оновлення поточного релізу з Git-коміту (робоча станція інтегратора).
# Нічого не завантажує: колеса — лише з локальних каталогів -WheelSource (раніше перевірені завантаження), розв'язання залежностей —
# pip --no-index --dry-run --report (офлайн). Вихід (-OutDir — новий каталог):
#   <OutDir>\package\backend-src.zip       git archive <commit> backend (байти LF, як у Git), записи <ReleaseId>/backend/…
#   <OutDir>\package\BACKEND-SHA256.txt    "<sha256>  backend/<шлях>" — з байтів ZIP
#   <OutDir>\package\dist.zip + DIST-SHA256.txt   з -DistZip (записи dist/…)
#   <OutDir>\package\Caddyfile             шаблон installer\windows-v2\deploy\Caddyfile того самого коміту
#   <OutDir>\package\requirements-hashed.txt + wheels\   ПОВНИЙ набір (requirements.txt + транзитивні, напр. colorama), кожен з sha256
#   <OutDir>\APPROVED-SHA256.txt           суми 6 файлів пакета — передається окремим каналом (не разом із package\)
# Приклад:
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\windows-v2\deploy\Build-V2CleanPackage.ps1 -Commit HEAD `
#     -DistZip D:\build\integrity-v2-dist-<sha7>.zip -WheelSource D:\wheels\cp313 -Py 'C:\Program Files\Python313\python.exe' -OutDir D:\release-<sha7>
[CmdletBinding()]
param(
  [string] $Commit = 'HEAD',
  [string] $ReleaseId,                          # за замовчуванням integrity-v2-<sha7>
  [Parameter(Mandatory)] [string] $DistZip,
  [Parameter(Mandatory)] [string[]] $WheelSource,
  [Parameter(Mandatory)] [string] $Py,          # Python 3.13 x64 (та сама платформа, що й сервер) з pip
  [Parameter(Mandatory)] [string] $OutDir,
  [string] $Repo
)
$ErrorActionPreference = 'Stop'
function Stop-B([string]$m) { throw "STOP: $m" }
# порядок рядків маніфестів — ординальний (як sorted() у Python і git): Sort-Object за замовчуванням нечутливий до регістру
function Get-OrdinalEntries($Zip) { $a = [object[]]@($Zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') }); $k = [string[]]@($a | ForEach-Object FullName); [Array]::Sort($k, $a, [StringComparer]::Ordinal); , $a }
function Get-Sha([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
function Invoke-Checked([string]$Exe, [string[]]$A) {
  $ErrorActionPreference = 'Continue'                        # PS 5.1: stderr нативної програми не є винятком; рішення — за кодом виходу
  $out = @(& $Exe @A 2>&1 | ForEach-Object { "$_" })
  if ($LASTEXITCODE -ne 0) { Stop-B "$Exe $($A[0..2] -join ' ') → код $LASTEXITCODE`n$($out | Select-Object -Last 15 | Out-String)" }
  $out
}
$enc = New-Object Text.UTF8Encoding $false
$WheelSource = @($WheelSource | ForEach-Object { $_ -split ';' } | Where-Object { $_ })   # powershell -File передає масив одним рядком: каталоги через ';'
if (-not $Repo) { $Repo = (Invoke-Checked 'git' @('-C', $PSScriptRoot, 'rev-parse', '--show-toplevel') | Select-Object -Last 1).Trim() }
$sha = (Invoke-Checked 'git' @('-C', $Repo, 'rev-parse', '--verify', "$Commit^{commit}") | Select-Object -Last 1).Trim()
if (-not $ReleaseId) { $ReleaseId = 'integrity-v2-' + $sha.Substring(0, 7) }
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') { Stop-B "ReleaseId поза дозволеною формою: $ReleaseId" }
if (Test-Path -LiteralPath $OutDir) { Stop-B "$OutDir уже існує" }
$pv = (Invoke-Checked $Py @('-I', '-c', 'import sys,struct; print(sys.version_info[0], sys.version_info[1], struct.calcsize(chr(80))*8)') | Select-Object -Last 1).Trim()   # без лапок: PS 5.1 обрізає " в аргументах
if ($pv -ne '3 13 64') { Stop-B "Python має бути 3.13 x64 (як на сервері), отримано $pv" }
$pkg = Join-Path $OutDir 'package'; $tmp = Join-Path $OutDir 'build-tmp'
$null = New-Item -ItemType Directory -Path $pkg, "$pkg\wheels", $tmp
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
try {
  # 1. backend: git archive (LF), маніфест — з байтів ZIP
  $bz = Join-Path $pkg 'backend-src.zip'
  $null = Invoke-Checked 'git' @('-C', $Repo, '-c', 'core.autocrlf=false', 'archive', '--format=zip', "--prefix=$ReleaseId/", '-o', $bz, $sha, 'backend')
  $man = New-Object System.Collections.Generic.List[string]; $req = $null
  $z = [IO.Compression.ZipFile]::OpenRead($bz)
  try {
    foreach ($e in (Get-OrdinalEntries $z)) {
      $s = $e.Open(); $h = [Security.Cryptography.SHA256]::Create()
      try { $man.Add((([BitConverter]::ToString($h.ComputeHash($s)) -replace '-', '').ToLowerInvariant()) + '  ' + $e.FullName.Substring($ReleaseId.Length + 1)) } finally { $s.Dispose(); $h.Dispose() }
      if ($e.FullName -eq "$ReleaseId/backend/requirements.txt") { $r = New-Object IO.StreamReader($e.Open(), [Text.Encoding]::UTF8); try { $req = $r.ReadToEnd() } finally { $r.Dispose() } }
    }
  } finally { $z.Dispose() }
  if (-not $req) { Stop-B 'у коміті немає backend/requirements.txt' }
  [IO.File]::WriteAllText((Join-Path $pkg 'BACKEND-SHA256.txt'), (($man -join "`n") + "`n"), $enc)
  # 2. dist
  $dm = New-Object System.Collections.Generic.List[string]
  $z = [IO.Compression.ZipFile]::OpenRead($DistZip)
  try {
    foreach ($e in (Get-OrdinalEntries $z)) {
      if (-not $e.FullName.StartsWith('dist/') -or ($e.FullName -split '/') -contains '..') { Stop-B "dist ZIP: запис поза dist/: $($e.FullName)" }
      $s = $e.Open(); $h = [Security.Cryptography.SHA256]::Create()
      try { $dm.Add((([BitConverter]::ToString($h.ComputeHash($s)) -replace '-', '').ToLowerInvariant()) + '  ' + $e.FullName) } finally { $s.Dispose(); $h.Dispose() }
    }
  } finally { $z.Dispose() }
  if (-not ($dm | Where-Object { $_.EndsWith('  dist/index.html') })) { Stop-B 'dist ZIP без dist/index.html' }
  [IO.File]::Copy($DistZip, (Join-Path $pkg 'dist.zip'), $false)
  [IO.File]::WriteAllText((Join-Path $pkg 'DIST-SHA256.txt'), (($dm -join "`n") + "`n"), $enc)
  # 3. Caddyfile — шаблон того самого коміту (байти Git)
  $cz = Join-Path $tmp 'caddy.zip'
  $null = Invoke-Checked 'git' @('-C', $Repo, '-c', 'core.autocrlf=false', 'archive', '--format=zip', '-o', $cz, $sha, 'installer/windows-v2/deploy/Caddyfile')
  $z = [IO.Compression.ZipFile]::OpenRead($cz); try { [IO.Compression.ZipFileExtensions]::ExtractToFile($z.GetEntry('installer/windows-v2/deploy/Caddyfile'), (Join-Path $pkg 'Caddyfile'), $false) } finally { $z.Dispose() }
  # 4. залежності: офлайн-розв'язання (лише колеса з -WheelSource) → повний набір із sha256
  $reqFile = Join-Path $tmp 'requirements.txt'; [IO.File]::WriteAllText($reqFile, $req, $enc)
  $report = Join-Path $tmp 'pip-report.json'
  $a = @('-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', '--dry-run', '--ignore-installed', '--no-index', '--only-binary', ':all:', '--report', $report, '-r', $reqFile)
  foreach ($w in $WheelSource) { if (-not (Test-Path -LiteralPath $w -PathType Container)) { Stop-B "немає каталогу коліс $w" }; $a += @('--find-links', $w) }
  $null = Invoke-Checked $Py $a
  $rep = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
  $lines = New-Object System.Collections.Generic.List[string]
  foreach ($it in @($rep.install | Sort-Object { $_.metadata.name.ToLowerInvariant() })) {
    $u = [Uri]$it.download_info.url
    if (-not $u.IsFile) { Stop-B "колесо не з локального каталогу: $($it.metadata.name)" }
    $src = $u.LocalPath
    if (-not $src.EndsWith('.whl')) { Stop-B "не колесо: $src" }
    $dst = Join-Path "$pkg\wheels" ([IO.Path]::GetFileName($src))
    [IO.File]::Copy($src, $dst, $false)
    $lines.Add("$($it.metadata.name)==$($it.metadata.version) --hash=sha256:$(Get-Sha $dst)")
  }
  if (-not $lines.Count) { Stop-B 'розв''язання залежностей порожнє' }
  [IO.File]::WriteAllText((Join-Path $pkg 'requirements-hashed.txt'), (($lines -join "`n") + "`n"), $enc)
  # 5. суми окремого каналу
  $ap = foreach ($n in 'backend-src.zip', 'BACKEND-SHA256.txt', 'dist.zip', 'DIST-SHA256.txt', 'Caddyfile', 'requirements-hashed.txt') { "$(Get-Sha (Join-Path $pkg $n))  $n" }
  [IO.File]::WriteAllText((Join-Path $OutDir 'APPROVED-SHA256.txt'), (($ap -join "`n") + "`n"), $enc)
} finally { if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force } }
"PASS  пакет $pkg (реліз $ReleaseId, коміт $sha): backend $($man.Count) файлів, dist $($dm.Count), коліс $($lines.Count)"
"PASS  суми окремого каналу: $(Join-Path $OutDir 'APPROVED-SHA256.txt') (SHA256 $(Get-Sha (Join-Path $OutDir 'APPROVED-SHA256.txt')))"
