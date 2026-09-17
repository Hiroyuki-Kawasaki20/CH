from pathlib import Path
import pandas as pd

BASE = Path('scripts/tmp')
MAIN_DETAILS = BASE / 'compare_main' / 'trace135_details_on.csv'
FEAT_DETAILS = BASE / 'compare_feat' / 'trace135_details_on.csv'
OUT_MD = BASE / '47cases_detail.md'
OUT_CSV = BASE / '47cases_detail.csv'

ID_COLS = ['NONYUHIBIN', 'HINBAN', 'SEBANGO']
SHOW_COLS = ['山通番', '納入先', 'NONYUHIBIN', '入車時間', '_truck_key', '高さ', 'サイズ種類']


def load_with_key(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.copy()
    for col in ID_COLS:
        df[col] = df[col].astype(str).str.strip()
    df['_key_base'] = df[ID_COLS].agg('|'.join, axis=1)
    df['_key_cum'] = df.groupby('_key_base').cumcount()
    df['unit_key'] = df['_key_base'] + '|' + df['_key_cum'].astype(str)
    df['order2'] = df['NONYUHIBIN'].astype(str).str.strip().str[-2:]
    return df


def summarize_yama(group: pd.DataFrame) -> dict:
    heights = pd.to_numeric(group['高さ'], errors='coerce').fillna(0)
    return {
        'NONYUHIBIN一覧': '/'.join(sorted(group['NONYUHIBIN'].astype(str).str.strip().unique())),
        '納入先一覧': '/'.join(sorted(group['納入先'].astype(str).str.strip().unique())),
        '_truck_key一覧': '/'.join(sorted(group['_truck_key'].astype(str).str.strip().unique())),
        '高さ合計': float(heights.sum()),
        'パレット数': int(len(group)),
    }


def classify(group: pd.DataFrame) -> str:
    vendors = group['納入先'].astype(str).str.strip().unique()
    if len(vendors) > 1:
        return '別納入先どうしの新規混載'
    truck_counts = group.groupby('納入先')['_truck_key'].nunique(dropna=False)
    if (truck_counts > 1).any():
        return '同一納入先内の別トラック混在'
    return '同一納入先内の別ユニットとの統合'


main = load_with_key(MAIN_DETAILS)
feat = load_with_key(FEAT_DETAILS)

main_map = main[['unit_key', '山通番']].rename(columns={'山通番': 'main_山通番'})
feat_map = feat[['unit_key', '山通番']].rename(columns={'山通番': 'feat_山通番'})
joined = feat_map.merge(main_map, on='unit_key', how='inner')

changed_cases = []
for feat_yama, rows in joined.groupby('feat_山通番'):
    main_yamas = sorted(rows['main_山通番'].astype(int).unique())
    if len(main_yamas) <= 1:
        continue
    unit_keys = set(rows['unit_key'])
    feat_group = feat[feat['unit_key'].isin(unit_keys)].copy()
    has_0102 = feat_group['order2'].isin(['01', '02']).any()
    changed_cases.append({
        'feat_山通番': int(feat_yama),
        'main_山通番群': main_yamas,
        'unit_keys': unit_keys,
        '01_02便を含む': bool(has_0102),
        '変化の種類': classify(feat_group),
        '別納入先どうし': feat_group['納入先'].astype(str).str.strip().nunique() > 1,
    })

no0102_cases = [c for c in changed_cases if not c['01_02便を含む']]

rows_for_csv = []
md = []
md.append('# 01/02便に無関係な変化 詳細明細')
md.append('')
md.append('## 再計算サマリ')
md.append(f'- main 山数: {main["山通番"].nunique()}')
md.append(f'- feat 山数: {feat["山通番"].nunique()}')
md.append(f'- main パレット総数: {len(main)}')
md.append(f'- feat パレット総数: {len(feat)}')
md.append(f'- 変化したfeat山数: {len(changed_cases)}')
md.append(f'- 01/02便絡み: {sum(c["01_02便を含む"] for c in changed_cases)}')
md.append(f'- 01/02便に無関係: {len(no0102_cases)}')
md.append(f'- 別納入先どうしの新規混載: {sum(c["別納入先どうし"] for c in changed_cases)}')
md.append('')
md.append('## 分類種別ごとの件数（01/02便に無関係なケースのみ）')
class_counts = pd.Series([c['変化の種類'] for c in no0102_cases]).value_counts().sort_index()
for name, count in class_counts.items():
    md.append(f'- {name}: {int(count)}')
md.append('')
md.append('## ケース一覧')

for idx, case in enumerate(no0102_cases, 1):
    feat_yama = case['feat_山通番']
    unit_keys = case['unit_keys']
    feat_group = feat[feat['unit_key'].isin(unit_keys)].copy().sort_values(['山通番', '納入先', 'NONYUHIBIN', '入車時間', '高さ'], kind='stable')
    main_group = main[main['unit_key'].isin(unit_keys)].copy().sort_values(['山通番', '納入先', 'NONYUHIBIN', '入車時間', '高さ'], kind='stable')

    md.append(f'### ケース{idx}')
    for main_yama in case['main_山通番群']:
        group = main_group[main_group['山通番'].astype(int).eq(main_yama)]
        summary = summarize_yama(group)
        md.append(f'  [main] 山ID={main_yama}: NONYUHIBIN一覧={summary["NONYUHIBIN一覧"]}, 納入先={summary["納入先一覧"]}, _truck_key={summary["_truck_key一覧"]}, 高さ合計={summary["高さ合計"]:g}, パレット数={summary["パレット数"]}')
        md.append('')
        md.append(group[SHOW_COLS].to_markdown(index=False))
        md.append('')
    feat_summary = summarize_yama(feat_group)
    md.append('  ↓')
    md.append(f'  [feat] 山ID={feat_yama}: NONYUHIBIN一覧={feat_summary["NONYUHIBIN一覧"]}, 納入先={feat_summary["納入先一覧"]}, _truck_key={feat_summary["_truck_key一覧"]}, 高さ合計={feat_summary["高さ合計"]:g}, パレット数={feat_summary["パレット数"]}')
    md.append('')
    md.append(feat_group[SHOW_COLS].to_markdown(index=False))
    md.append('')
    md.append(f'  変化の種類: {case["変化の種類"]}')
    md.append('')

    for _, r in main_group.iterrows():
        rows_for_csv.append({
            'ケース': idx,
            'side': 'main',
            'main_山通番群': '/'.join(map(str, case['main_山通番群'])),
            'feat_山通番': feat_yama,
            '変化の種類': case['変化の種類'],
            **{col: r[col] for col in SHOW_COLS},
        })
    for _, r in feat_group.iterrows():
        rows_for_csv.append({
            'ケース': idx,
            'side': 'feat',
            'main_山通番群': '/'.join(map(str, case['main_山通番群'])),
            'feat_山通番': feat_yama,
            '変化の種類': case['変化の種類'],
            **{col: r[col] for col in SHOW_COLS},
        })

OUT_MD.write_text('\n'.join(md), encoding='utf-8')
pd.DataFrame(rows_for_csv).to_csv(OUT_CSV, index=False, encoding='utf-8-sig')

print('\n'.join(md))
print('')
print('===== 件数要約 =====')
print(f'main 山数: {main["山通番"].nunique()}')
print(f'feat 山数: {feat["山通番"].nunique()}')
print(f'パレット総数: main={len(main)} feat={len(feat)}')
print(f'変化したfeat山数: {len(changed_cases)}')
print(f'01/02便絡み: {sum(c["01_02便を含む"] for c in changed_cases)}')
print(f'01/02便に無関係: {len(no0102_cases)}')
print(f'別納入先どうしの新規混載: {sum(c["別納入先どうし"] for c in changed_cases)}')
print('分類種別(01/02無関係):')
for name, count in class_counts.items():
    print(f'  {name}: {int(count)}')
print(f'出力MD: {OUT_MD}')
print(f'出力CSV: {OUT_CSV}')
