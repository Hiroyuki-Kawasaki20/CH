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
  if ($h.Count -ne 1) {
    $at = ($h | ForEach-Object { $_ + 1 }) -join ','
    throw "ANCHOR NOT UNIQUE rx=$Rx hits=$($h.Count) at=$at"
  }
  Write-Host "ANCHOR OK rx=$Rx line=$($h[0] + 1)"
  return $h[0]
}
function Get-Indent($s) { if ($s -match '^([ \t]*)') { return $Matches[1] } ; return '' }
function Get-EnclosingDef($L, $i) {
  $need = (Get-Indent $L[$i]).Length
  for ($k = $i - 1; $k -ge 0; $k--) {
    $t = $L[$k]
    if ($t.Trim() -eq '') { continue }
    if ($t -match '^[ \t]*#') { continue }
    $ti = (Get-Indent $t).Length
    if ($ti -lt $need) {
      if ($t -match '^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)') { return @($Matches[1], $ti) }
      $need = $ti
    }
  }
  return @('<module>', -1)
}

$iA = Find-One $lines '^[ \t]*best_candidates: List\[List\[dict\]\] = \[\]'
$iB = Find-One $lines '^[ \t]*trial = _build_trial_from_assignment\(bits\)[ \t]*$'
$iB2 = $iB + 1
if ($lines[$iB2] -notmatch '^[ \t]*trial_score = _state_score\(trial\)[ \t]*$') {
  throw "ANCHOR2 NEXT LINE MISMATCH line=$($iB2 + 1) text=$($lines[$iB2])"
}
Write-Host "ANCHOR2 PAIR OK line=$($iB2 + 1)"

$fin = Find-All $lines '^[ \t]*_finalize_inspection_delay_flags\(results\)[ \t]*$'
Write-Host "FINALIZE_CALLS count=$($fin.Count) at=$((($fin | ForEach-Object { $_ + 1 }) -join ','))"
$defSer = Find-One $lines '^[ \t]*def _serialize_lanes_final\('
$sites = Find-All $lines '^[ \t]*_serialize_lanes_final\(results\)[ \t]*$'
Write-Host "SERIALIZE_CALLSITES count=$($sites.Count) at=$((($sites | ForEach-Object { $_ + 1 }) -join ','))"
if ($sites.Count -lt 1) { throw 'NO SERIALIZE CALLSITE FOUND' }

$targets = @()
foreach ($i in $sites) {
  $ind = Get-Indent $lines[$i]
  $enc = Get-EnclosingDef $lines $i
  Write-Host "----- SITE line=$($i + 1) indent=$($ind.Length) enclosing_def=$($enc[0]) def_indent=$($enc[1]) -----"
  $s = [Math]::Max(0, $i - 12)
  $e = [Math]::Min($lines.Count - 1, $i + 6)
  for ($k = $s; $k -le $e; $k++) {
    $mark = if ($k -eq $i) { '>>' } else { '  ' }
    Write-Host ("{0} {1,5} | {2}" -f $mark, ($k + 1), $lines[$k])
  }
  if ($i -lt $defSer) { Write-Host "SKIP line=$($i + 1) reason=before_def" ; continue }
  if ([int]$enc[1] -ne 0) { throw "SITE NOT IN TOP LEVEL FUNCTION line=$($i + 1) enclosing_def=$($enc[0]) def_indent=$($enc[1])" }
  $targets += $i
}
Write-Host "TARGETS count=$($targets.Count) at=$((($targets | ForEach-Object { $_ + 1 }) -join ','))"
if ($targets.Count -lt 1) { throw 'NO TARGET AFTER FILTER' }
$minT = ($targets | Measure-Object -Minimum).Minimum
if (-not ($iA -lt $iB2 -and $iB2 -lt $minT)) { throw "ORDER UNEXPECTED A=$($iA + 1) B=$($iB2 + 1) minT=$($minT + 1)" }

$blkA = @(
  '_mA_scores = set()  # MEASURE-A temporary',
  '_mA_trials = 0  # MEASURE-A temporary'
)
$blkB = @(
  '_mA_trials += 1  # MEASURE-A',
  '_mA_scores.add(trial_score)  # MEASURE-A'
)
function Make-BlockC($tag) {
  return @(
    '# MEASURE-A temporary instrumentation - remove before commit',
    'import time as _mA_time',
    "_mA_tag = $tag",
    'try:',
    '    _mA_ny = int(n_yamas)',
    'except Exception:',
    '    _mA_ny = -1',
    'try:',
    '    _mA_tr = int(_mA_trials)',
    '    _mA_ds = len(_mA_scores)',
    '    _mA_nc = len(best_candidates)',
    'except Exception:',
    '    _mA_tr = -1',
    '    _mA_ds = -1',
    '    _mA_nc = -1',
    '_mA_anchored = sum(1 for _r in results if _r.get("_is_anchored"))',
    '_mA_before = sorted(_deadline_violation_set(results))',
    '_mA_state = _state_score(results)',
    '_mA_t0 = _mA_time.perf_counter()',
    '_mA_pred = _serialized_late_count(results)',
    '_mA_cost = _mA_time.perf_counter() - _mA_t0',
    'print(f"[MEASURE-A] site={_mA_tag} n_yamas={_mA_ny} rows={len(results)} anchored={_mA_anchored} trials={_mA_tr} distinct_scores={_mA_ds} candidates={_mA_nc}")',
    'print(f"[MEASURE-A] site={_mA_tag} state_score={_mA_state} before={_mA_before} nbefore={len(_mA_before)} predicted_after={_mA_pred} cost_sec={_mA_cost:.4f}")',
    '_serialize_lanes_final(results)',
    '_mA_after = sorted(_deadline_violation_set(results))',
    'print(f"[MEASURE-A] site={_mA_tag} after={_mA_after} nafter={len(_mA_after)} newly_late={sorted(set(_mA_after) - set(_mA_before))} resolved={sorted(set(_mA_before) - set(_mA_after))} prediction_ok={len(_mA_after) == _mA_pred}")'
  )
}

if ($mode -ne 'apply') {
  Write-Host 'CHECK ONLY - no file was modified. Re-run with: apply'
  exit 0
}

foreach ($i in ($targets | Sort-Object -Descending)) {
  $ind = Get-Indent $lines[$i]
  $blk = Make-BlockC ($i + 1)
  $lines.RemoveAt($i)
  $lines.InsertRange($i, [string[]]($blk | ForEach-Object { $ind + $_ }))
  Write-Host "INSERTED at line=$($i + 1) block=$($blk.Count)"
}
$indB = Get-Indent $lines[$iB2]
$lines.InsertRange($iB2 + 1, [string[]]($blkB | ForEach-Object { $indB + $_ }))
$indA = Get-Indent $lines[$iA]
$lines.InsertRange($iA + 1, [string[]]($blkA | ForEach-Object { $indA + $_ }))

$out = [string]::Join($nl, $lines.ToArray())
$enc2 = New-Object System.Text.UTF8Encoding($hasBom)
[System.IO.File]::WriteAllText((Resolve-Path $path).Path, $out, $enc2)
Write-Host "APPLIED lines=$($lines.Count)"
