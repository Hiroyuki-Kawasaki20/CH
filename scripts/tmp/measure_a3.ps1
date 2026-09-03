$ErrorActionPreference = 'Stop'
$mode = if ($args.Count -ge 1) { $args[0] } else { 'check' }
$path = 'src\services\process_assigner.py'

$bytes = [System.IO.File]::ReadAllBytes($path)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$raw = [System.IO.File]::ReadAllText($path)
if ($raw.Contains('MEASURE-A')) { throw 'ALREADY INSTRUMENTED - run git restore first' }
$crlf = $raw.Contains("`r`n")
$nl = if ($crlf) { "`r`n" } else { "`n" }
$lines = New-Object 'System.Collections.Generic.List[string]'
foreach ($l in ($raw -split "`r`n|`n")) { $lines.Add($l) }
Write-Host "MODE=$mode LINES=$($lines.Count) NEWLINE=$(if ($crlf) {'CRLF'} else {'LF'}) BOM=$hasBom"

function Find-All($L, $Rx) {
  $hits = @()
  for ($i = 0; $i -lt $L.Count; $i++) { if ($L[$i] -match $Rx) { $hits += $i } }
  return @($hits)
}
function Find-One($L, $Rx) {
  $h = Find-All $L $Rx
  if ($h.Count -ne 1) { throw "ANCHOR NOT UNIQUE rx=$Rx hits=$($h.Count) at=$((($h | ForEach-Object { $_ + 1 }) -join ','))" }
  Write-Host "ANCHOR OK rx=$Rx line=$($h[0] + 1)"
  return [int]$h[0]
}
function Get-Indent($s) { if ($s -match '^([ \t]*)') { return $Matches[1] } ; return '' }
function Get-TopDef($L, $i) {
  for ($k = $i; $k -ge 0; $k--) {
    if ($L[$k] -match '^def ([A-Za-z_][A-Za-z0-9_]*)') { return @($Matches[1], $k) }
  }
  return @('<module>', -1)
}
function Show-Ctx($L, $i, $up, $dn) {
  $s = [Math]::Max(0, $i - $up)
  $e = [Math]::Min($L.Count - 1, $i + $dn)
  for ($k = $s; $k -le $e; $k++) {
    $m = if ($k -eq $i) { '>>' } else { '  ' }
    Write-Host ("{0} {1,5} | {2}" -f $m, ($k + 1), $L[$k])
  }
}

$iA = Find-One $lines '^[ \t]*best_candidates: List\[List\[dict\]\] = \[\]'
$iB = Find-One $lines '^[ \t]*trial = _build_trial_from_assignment\(bits\)[ \t]*$'
$iB2 = $iB + 1
if ($lines[$iB2] -notmatch '^[ \t]*trial_score = _state_score\(trial\)[ \t]*$') {
  throw "ANCHOR2 NEXT LINE MISMATCH line=$($iB2 + 1) text=$($lines[$iB2])"
}
Write-Host "ANCHOR2 PAIR OK line=$($iB2 + 1)"
$iSite = Find-One $lines '^[ \t]*_serialize_lanes_final\(results\)[ \t]*$'
$iDefSer = Find-One $lines '^[ \t]*def _serialize_lanes_final\('
if ($iSite -lt $iDefSer) { throw "SITE BEFORE DEF site=$($iSite + 1) def=$($iDefSer + 1)" }
if ((Get-Indent $lines[$iSite]).Length -lt 1) { throw "SITE AT MODULE LEVEL line=$($iSite + 1)" }

foreach ($f in @('_deadline_violation_set', '_state_score', '_serialized_late_count')) {
  $d = Find-All $lines ('^[ \t]*def ' + $f + '\(')
  if ($d.Count -ne 1) { throw "HELPER DEF NOT UNIQUE name=$f hits=$($d.Count)" }
  Write-Host "HELPER $f def_line=$($d[0] + 1)"
  if ([int]$d[0] -gt $iSite) { throw "HELPER DEFINED AFTER SITE name=$f def_line=$($d[0] + 1) site=$($iSite + 1)" }
}

$iDef = Find-One $lines '^def _legacy_assign_processes_by_arrival_time\('
foreach ($p in @(@('ANCHOR1', $iA), @('ANCHOR2', $iB2), @('SITE', $iSite))) {
  $t = Get-TopDef $lines ([int]$p[1])
  Write-Host "SCOPE $($p[0]) line=$([int]$p[1] + 1) indent=$((Get-Indent $lines[[int]$p[1]]).Length) top_def=$($t[0]) at=$([int]$t[1] + 1)"
  if ($t[0] -ne '_legacy_assign_processes_by_arrival_time') { Write-Host "WARN $($p[0]) is in a different top-level function" }
}
Write-Host '----- ANCHOR1 CONTEXT -----'
Show-Ctx $lines $iA 6 10
Write-Host '----- ANCHOR2 CONTEXT -----'
Show-Ctx $lines $iB2 8 14
Write-Host '----- SITE CONTEXT -----'
Show-Ctx $lines $iSite 12 6

$iApp = -1
$app = Find-All $lines '^[ \t]*best_candidates\.append\('
Write-Host "APPEND_SITES count=$($app.Count) at=$((($app | ForEach-Object { $_ + 1 }) -join ','))"
if ($app.Count -eq 1) { $iApp = [int]$app[0] ; Show-Ctx $lines $iApp 4 4 } else { Write-Host 'APPEND SKIPPED - candidates count will be reported as 0' }

$indA = Get-Indent $lines[$iA]
$indB = Get-Indent $lines[$iB2]
$indS = Get-Indent $lines[$iSite]
$indP = if ($iApp -ge 0) { Get-Indent $lines[$iApp] } else { '' }
Write-Host "INDENT A=$($indA.Length) B=$($indB.Length) SITE=$($indS.Length) APPEND=$($indP.Length)"

$blkM = @(
  '_MA_STATS = {"trials": 0, "scores": set(), "cand": 0}  # MEASURE-A temporary'
)
$blkA = @(
  '_MA_STATS["trials"] = 0  # MEASURE-A',
  '_MA_STATS["scores"] = set()  # MEASURE-A',
  '_MA_STATS["cand"] = 0  # MEASURE-A'
)
$blkB = @(
  '_MA_STATS["trials"] += 1  # MEASURE-A',
  '_MA_STATS["scores"].add(trial_score)  # MEASURE-A'
)
$blkP = @(
  '_MA_STATS["cand"] += 1  # MEASURE-A'
)
$blkS = @(
  '# MEASURE-A temporary instrumentation - remove before commit',
  'import time as _mA_time',
  "_mA_tag = $($iSite + 1)",
  'try:',
  '    _mA_ny = int(n_yamas)',
  'except Exception:',
  '    _mA_ny = -1',
  'try:',
  '    _mA_sc = sorted(_MA_STATS["scores"])',
  'except Exception:',
  '    _mA_sc = list(_MA_STATS["scores"])',
  '_mA_tr = _MA_STATS["trials"]',
  '_mA_ds = len(_mA_sc)',
  '_mA_nc = _MA_STATS["cand"]',
  '_mA_lo = _mA_sc[0] if _mA_sc else None',
  '_mA_hi = _mA_sc[-1] if _mA_sc else None',
  '_mA_anchored = sum(1 for _r in results if _r.get("_is_anchored"))',
  '_mA_before = sorted(_deadline_violation_set(results))',
  '_mA_state = _state_score(results)',
  '_mA_t0 = _mA_time.perf_counter()',
  '_mA_pred = _serialized_late_count(results)',
  '_mA_cost = _mA_time.perf_counter() - _mA_t0',
  'print(f"[MEASURE-A] site={_mA_tag} n_yamas={_mA_ny} rows={len(results)} anchored={_mA_anchored} trials={_mA_tr} distinct_scores={_mA_ds} candidates={_mA_nc}")',
  'print(f"[MEASURE-A] site={_mA_tag} score_min={_mA_lo} score_max={_mA_hi} state_score={_mA_state} before={_mA_before} nbefore={len(_mA_before)} predicted_after={_mA_pred} cost_sec={_mA_cost:.4f}")',
  '_serialize_lanes_final(results)',
  '_mA_after = sorted(_deadline_violation_set(results))',
  'print(f"[MEASURE-A] site={_mA_tag} after={_mA_after} nafter={len(_mA_after)} newly_late={sorted(set(_mA_after) - set(_mA_before))} resolved={sorted(set(_mA_before) - set(_mA_after))} prediction_ok={len(_mA_after) == _mA_pred}")'
)

$tasks = @()
$tasks += @{ Pos = $iSite ; Rep = $true ; Lines = @($blkS | ForEach-Object { $indS + $_ }) ; Name = 'SITE' }
$tasks += @{ Pos = $iB2 + 1 ; Rep = $false ; Lines = @($blkB | ForEach-Object { $indB + $_ }) ; Name = 'ANCHOR2' }
$tasks += @{ Pos = $iA + 1 ; Rep = $false ; Lines = @($blkA | ForEach-Object { $indA + $_ }) ; Name = 'ANCHOR1' }
$tasks += @{ Pos = $iDef ; Rep = $false ; Lines = @($blkM) ; Name = 'MODULE' }
if ($iApp -ge 0) { $tasks += @{ Pos = $iApp ; Rep = $false ; Lines = @($blkP | ForEach-Object { $indP + $_ }) ; Name = 'APPEND' } }
Write-Host "PLAN total_insert_lines=$((($tasks | ForEach-Object { $_.Lines.Count }) | Measure-Object -Sum).Sum)"
foreach ($t in ($tasks | Sort-Object { [int]$_.Pos })) { Write-Host "PLAN $($t.Name) pos=$([int]$t.Pos + 1) lines=$($t.Lines.Count) replace=$($t.Rep)" }

if ($mode -ne 'apply') {
  Write-Host 'CHECK ONLY - no file was modified. Re-run with: apply'
  exit 0
}

foreach ($t in ($tasks | Sort-Object { [int]$_.Pos } -Descending)) {
  $p = [int]$t.Pos
  if ($t.Rep) { $lines.RemoveAt($p) }
  $lines.InsertRange($p, [string[]]$t.Lines)
  Write-Host "APPLIED_TASK $($t.Name) pos=$($p + 1) lines=$($t.Lines.Count)"
}
$out = [string]::Join($nl, $lines.ToArray())
$enc2 = New-Object System.Text.UTF8Encoding($hasBom)
[System.IO.File]::WriteAllText((Resolve-Path $path).Path, $out, $enc2)
Write-Host "APPLIED lines=$($lines.Count)"
