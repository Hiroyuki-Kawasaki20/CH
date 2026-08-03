#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze window bounds for test 3."""
import sys
sys.path.insert(0, '.')

from src.services import process_assigner as pa

# 山2 is 日野便7, previous is 日野便6
# 日野便6: 入車時間 23:50
# 日野便7: 入車時間 00:24 (次日の24時制)

pickup_6_str = "23:50"
pickup_7_str = "00:24"

pickup_6_secs = pa._time_to_seconds(pickup_6_str)  # 23*3600 + 50*60
pickup_7_secs = pa._time_to_seconds(pickup_7_str)  # 0*3600 + 24*60

print(f"日野便6 入車時刻: {pickup_6_str} = {pickup_6_secs} secs")
print(f"日野便7 入車時刻: {pickup_7_str} = {pickup_7_secs} secs")

# ARRIVAL_BUFFER_SECS
buffer = pa.ARRIVAL_BUFFER_SECS
print(f"\nARRIVAL_BUFFER_SECS: {buffer} secs")

# 日野便6到着 + バッファ（前便ベースのスタート時刻下限）
prev_arrival_with_buffer = pickup_6_secs + buffer
print(f"\n日野便6 到着 + バッファ: {pickup_6_secs} + {buffer} = {prev_arrival_with_buffer} secs")

# 山2の実開始時刻
actual_start = 86700  # 00:05 (次日)
print(f"山2 実開始時刻: {actual_start} secs")

# 元の窓幅
original_width = 1500
print(f"\n元の窓幅: {original_width} secs (=25分)")

# 候補窓
window_lower = actual_start - 375  # 25分の半分
window_upper = actual_start + 1125  # 25分の3/4

print(f"\n候補窓 [実測値-25分/2, 実測値+25分*3/4]:")
print(f"  [{window_lower}, {window_upper}] secs")
print(f"  = [{window_lower - 86400}, {window_upper - 86400}] secs (前日からのオフセット)")

# Convert to HH:MM for readability
def secs_to_hhmm(s):
    h = (s // 3600) % 24
    m = (s % 3600) // 60
    return f"{h:02d}:{m:02d}"

print(f"  = [{secs_to_hhmm(window_lower)}, {secs_to_hhmm(window_upper)}] (24時制)")

# もっと保守的な窓
conservative_lower = prev_arrival_with_buffer
conservative_upper = actual_start + 600  # さらに 10分の余裕

print(f"\n保守的な窓 [前便+バッファ, 実測+10分]:")
print(f"  [{conservative_lower}, {conservative_upper}] secs")
print(f"  = [{secs_to_hhmm(conservative_lower)}, {secs_to_hhmm(conservative_upper)}] (24時制)")
