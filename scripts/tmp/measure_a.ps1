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
  
function Find-One($L, $Rx) {  
  $hits = @()  
  for ($i = 0; $i -lt $L.Count; $i++) { if ($L[$i] -match $Rx) { $hits += $i } }  
  if ($hits.Count -ne 1) {  
    $at = ($hits | ForEach-Object { $_ + 1 }) -join ','  
    throw "ANCHOR NOT UNIQUE rx=$Rx hits=$($hits.Count) at=$at"  
  }  
  Write-Host "ANCHOR OK rx=$Rx line=$($hits[0] + 1)"  
  return $hits[0]  
}  
function Get-Indent($s) { if ($s -match '^([ \t]*)') { return $Matches[1] } ; return '' }  
  
$iA = Find-One $lines '^[ \t]*best_candidates: List\[List\[dict\]\] = \[\]'  
$iB = Find-One $lines '^[ \t]*trial = _build_trial_from_assignment\(bits\)[ \t]*$'  
$iB2 = $iB + 1  
if ($lines[$iB2] -notmatch '^[ \t]*trial_score = _state_score\(trial\)[ \t]*$') {  
  throw "ANCHOR2 NEXT LINE MISMATCH line=$($iB2 + 1) text=$($lines[$iB2])"  
}  
Write-Host "ANCHOR2 PAIR OK line=$($iB2 + 1)"  
$iF = Find-One $lines '^[ \t]*_finalize_inspection_delay_flags\(results\)[ \t]*$'  
$iC = $iF + 1  
while ($iC -lt $lines.Count -and $lines[$iC].Trim() -eq '') { $iC++ }  
if ($lines[$iC] -notmatch '^[ \t]*_serialize_lanes_final\(results\)[ \t]*$') {  
  throw "ANCHOR3 MISMATCH line=$($iC + 1) text=$($lines[$iC])"  
}  
Write-Host "ANCHOR3 OK line=$($iC + 1)"  
  
$indA = Get-Indent $lines[$iA]  
$indB = Get-Indent $lines[$iB2]  
$indC = Get-Indent $lines[$iC]  
Write-Host "INDENT A=$($indA.Length) B=$($indB.Length) C=$($indC.Length)"  
  
$blkA = @(  
  '_mA_scores = set()  # MEASURE-A temporary',  
  '_mA_trials = 0  # MEASURE-A temporary'  
)  
$blkB = @(  
  '_mA_trials += 1  # MEASURE-A',  
  '_mA_scores.add(trial_score)  # MEASURE-A'  
)  
$blkC = @(  
  '# MEASURE-A temporary instrumentation - remove before commit',  
  'import time as _mA_time',  
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
  'print(f"[MEASURE-A] n_yamas={_mA_ny} rows={len(results)} anchored={_mA_anchored} trials={_mA_tr} distinct_scores={_mA_ds} candidates={_mA_nc}")',  
  'print(f"[MEASURE-A] state_score={_mA_state} before={_mA_before} nbefore={len(_mA_before)} predicted_after={_mA_pred} cost_sec={_mA_cost:.4f}")',  
  '_serialize_lanes_final(results)',  
  '_mA_after = sorted(_deadline_violation_set(results))',  
  'print(f"[MEASURE-A] after={_mA_after} nafter={len(_mA_after)} newly_late={sorted(set(_mA_after) - set(_mA_before))} resolved={sorted(set(_mA_before) - set(_mA_after))} prediction_ok={len(_mA_after) == _mA_pred}")'  
)  
  
if ($mode -ne 'apply') {  
  Write-Host 'CHECK ONLY - no file was modified. Re-run with: apply'  
  exit 0  
}  
  
$lines.RemoveAt($iC)  
$lines.InsertRange($iC, [string[]]($blkC | ForEach-Object { $indC + $_ }))  
$lines.InsertRange($iB2 + 1, [string[]]($blkB | ForEach-Object { $indB + $_ }))  
$lines.InsertRange($iA + 1, [string[]]($blkA | ForEach-Object { $indA + $_ }))  
  
$out = [string]::Join($nl, $lines.ToArray())  
$enc = New-Object System.Text.UTF8Encoding($hasBom)  
[System.IO.File]::WriteAllText((Resolve-Path $path).Path, $out, $enc)  
Write-Host "APPLIED lines=$($lines.Count)"  
