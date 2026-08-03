#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check if yama1 has inspection delay rule trigger."""
import pandas as pd
from pathlib import Path
import json

root = Path('.')
spo_path = root / 'tests' / 'fixtures' / 'issue42' / 'spo_upload_snapshot.xlsx'

spo_df = pd.read_excel(spo_path)
print('All yamas in SPO:')
print(sorted(spo_df['グループ番号'].unique()))

# 山1の詳細
yama1_spo = spo_df[spo_df['グループ番号'] == 1]
print(f'\n山1 行数: {len(yama1_spo)}')
if len(yama1_spo) > 0:
    row = yama1_spo.iloc[0]
    print(f'Max移動工数: {row.get("Max移動工数", "N/A")}')
    grouped = row.get("GroupedData", "")
    if grouped:
        try:
            data = json.loads(grouped)
            print(f'GroupedData items: {len(data) if isinstance(data, list) else 1}')
            if isinstance(data, list):
                for i, item in enumerate(data):
                    nony = item.get("NONYUHIBIN", "")
                    print(f'  Item {i} (order_idx={i}): NONYUHIBIN={nony}, vendor={item.get("OData_納入先", "N/A")}')
                    # 検査遅延: order_idx >= 2 and order_idx % 2 == 0
                    triggers_inspection_delay = (i >= 2 and i % 2 == 0)
                    print(f'      -> Inspection delay trigger: {triggers_inspection_delay}')
        except Exception as e:
            print(f'GroupedData parse error: {e}')

print('\n[判定結果]')
print('山1は GroupedData に2項目のみ。')
print('order_idx は 0, 1 なので、i >= 2 かつ i % 2 == 0 の条件を満たさない。')
print('→ 山1に検査遅延ルールは発火しない')
print('→ テスト1は「山1がメイン割当」を確認するが、それは検査遅延ルールではなく')
print('   単なる通常の割当ロジックにより自明にメイン工程に割り当てられるだけ')
