# 【案A 影響範囲確認スクリプト】実行ガイド

## 概要

**目的**: `_pick_next_main_mountain` の並べ替えキーを `raw締切` → `eval締切(24時間軸補正後)` に変更した場合の影響を、実装前に実測で確認する。

**制約**: 
- ✅ 調査・比較のみ（本実装はしない）
- ✅ 確認OKが取れてから最小差分で実装
- ✅ mainコミット禁止（KVC受入分割ブランチで実装）

---

## ファイル構成

| ファイル名 | 目的 |
|-----------|------|
| `analysis_impact_evaluation_deadline.py` | STEP1-4を実行する基本スクリプト |
| `analysis_impact_full_pipeline.py` | テスト影響分析と実装チェックリスト生成 |
| `analysis_impact_test_dependency.txt` | (生成)テスト依存性詳細レポート |
| `analysis_implementation_checklist.txt` | (生成)本実装前チェックリスト |

---

## 実行手順

### ▶ STEP0: 環境確認

```bash
cd "c:\Users\1588386\DIG_Project\CHかんばんセット"

# 仮想環境確認
.venv\Scripts\Activate.ps1

# 必要なモジュール確認
pip list | findstr pandas

python --version  # Python 3.8+
```

### ▶ STEP1-4: 影響範囲調査（基本版）

```bash
# サンプルデータで動作確認
python analysis_impact_evaluation_deadline.py "SPOアップロード用.xlsx"
```

**出力**: コンソールに以下が表示される
```
================================================================================
【案A 影響範囲確認スクリプト】選択順キーをeval締切に統一
================================================================================

[STEP1] 現状(raw締切キー)でGUI本番フロー実行...
[RESULT] 現状(raw締切キー)の選択順:
  選択順1: 山8 | raw締切=13:00 | eval締切=13:00 | 工程=メイン | 前倒し=True
  選択順2: 山7 | raw締切=14:00 | eval締切=14:00 | 工程=メイン | 前倒し=True
  ...

[STEP2] 案A適用後(eval締切キー)を複製でシミュレート...
[RESULT] 案A(eval締切キー)の選択順:
  ...

[STEP3] STEP1(現状) vs STEP2(案A) 差分比較
選択順・工程の変化:
  ★ 山X: 選択順(Y→Z) / 工程(メイン→リリーフ)  [変化検出]
  ...

【重要観点 Q2確認】
  ✓ 現状(raw):  07便の工程 = メイン
  ✓ 案A(eval):  07便の工程 = メイン
  ✅ 07便がメイン通過 (Q2要件満たす)

【副作用チェック】07便以外で工程が反転する便:
  ✅ 副作用なし（07便以外の工程変化なし）

[STEP4] 既存テストへの影響予測
  ⚠️  影響を受ける可能性のあるテスト:
    - test_hino_2lane.py
    - test_sorter.py
```

### ▶ STEP5: テスト影響分析（詳細版）

```bash
python analysis_impact_full_pipeline.py
```

**出力ファイル**:
1. `analysis_impact_test_dependency.txt` - テスト依存性詳細レポート
2. `analysis_implementation_checklist.txt` - 本実装前チェックリスト

---

## 各STEPの説明

### STEP1: 現状(raw締切キー)のベースライン採取

```python
# 現状の _pick_next_main_mountain ロジック
# → 締切が最も早い山（raw締切）を主対象に選択

def _pick_next_main_mountain(unscheduled, main_end_time, main_mountain_count):
    # ★KEY★ raw締切でソート
    primary = sorted(with_deadline, key=lambda x: (x["締め切り_秒"], x["山通番"]))[0]
    # ...
```

**採取内容**:
- 各山の山通番 / オーダー / raw締切 / eval締切 / 選ばれた順番 / 最終割当(メイン/リリーフ)

### STEP2: 案A適用(eval締切キー)をシミュレート

```python
# 案A: _pick_next_main_mountain_eval_deadline 複製版
# → 締切が最も早い山（eval締切=24時間軸補正後）を主対象に選択

def _pick_next_main_mountain_eval_deadline(unscheduled, main_end_time, main_mountain_count):
    # ★KEY★ eval締切でソート
    primary_candidates = []
    for m in with_deadline:
        deadline = m.get("締め切り_秒")
        eval_deadline = _deadline_for_eval(deadline, main_end_time)  # 24h軸補正
        primary_candidates.append((eval_deadline, int(m["山通番"]), m))
    
    primary_candidates.sort(key=lambda x: (x[0], x[1]))
    primary = primary_candidates[0][2]
    # ...
```

**シミュレーション内容**:
- 同一入力で eval締切キー版を実行
- 選択順と最終割当が変わるか確認

### STEP3: 差分比較

| 便 | 現状選択順 | 案A選択順 | 現状工程 | 案A工程 | 変化 |
|---|----------|---------|--------|-------|------|
| 07 | 2 | 2 | メイン | メイン | ✅ なし |
| 08 | 1 | 1 | メイン | メイン | ✅ なし |

**重要確認**:
- **Q2要件**: 07便がメイン通過するか？ → YES/NO
- **副作用チェック**: 07便以外に工程変化があるか？ → YES/NO

### STEP4: 既存テスト影響予測

```python
# テストファイルをスキャン
# → 以下パターンを検出

パターン1: _pick_next_main_mountain を直接テスト
  ⚠️ 高リスク → eval版ロジックのテストが必要

パターン2: PROC_MAIN/PROC_RELIEF のassert
  🟡 中リスク → assert値が変わる可能性あり
  
パターン3: 選択順(sequence)に依存するassert
  🟡 中リスク → 選択順が変わるとテスト失敗
```

**検出件数** (例):
- `_pick_next_main_mountain` 直接使用: 0 件
- `PROC_MAIN` のassert: 20 件
- `PROC_RELIEF` のassert: 1 件
- 選択順関連のassert: 16 件

---

## 実装前チェックリスト

調査スクリプト実行後、以下をすべて確認してから本実装を開始：

```
□ STEP1: 現状(raw締切)のベースラインが正常に採取できたか
   → セットボード画面で確認可能な山と選択順が一致しているか

□ STEP2: 案A(eval締切)のシミュレーション結果が合理的か
   → eval締切によって選択順が正しく変わっているか

□ Q2重要観点: 07便がメイン通過しているか
   ✅ YES → OK
   ❌ NO → 要再検討（実装ストップ）

□ 副作用チェック: 07便以外の工程変化がないか
   ✅ なし → OK（KVC以外不変の制約を満たす）
   ⚠️ あり → 変化の理由を分析（許容か非許容か判断）

□ STEP4テスト影響: 高リスクテストの対応方針を決定
   → assert値修正方針を決定
   → テスト実行計画を立案
```

---

## 本実装フロー（チェックリストOK後）

### 1️⃣ ブランチ作成

```bash
git checkout -b feature/KVC-eval-deadline-v1
git branch -vv
```

### 2️⃣ 最小差分実装

[process_assigner.py](../src/services/process_assigner.py) の `_pick_next_main_mountain` 関数内のソートキーのみ変更：

```python
# 変更前 (raw締切)
primary = sorted(with_deadline, key=lambda x: (x["締め切り_秒"], x["山通番"]))[0]

# ↓

# 変更後 (eval締切)
primary_candidates = []
for m in with_deadline:
    deadline = m.get("締め切り_秒")
    eval_deadline = _deadline_for_eval(deadline, main_end_time)
    primary_candidates.append((eval_deadline, int(m["山通番"]), m))
primary_candidates.sort(key=lambda x: (x[0], x[1]))
primary = primary_candidates[0][2]
```

同様に `safe_prefetch.sort()` のキーも eval締切へ変更：

```python
# 変更前
safe_prefetch.sort(
    key=lambda x: (
        x[2].get("締め切り_秒") is None,
        x[2].get("締め切り_秒") or float("inf"),  # ← raw締切
        ...
    )
)

# ↓

# 変更後
safe_prefetch.sort(
    key=lambda x: (
        x[2].get("締め切り_秒") is None,
        x[3] or float("inf"),  # ← eval締切を計算済み
        ...
    )
)
```

### 3️⃣ テスト実行と修正

```bash
# テスト全実行
pytest tests/ -v --tb=short

# 失敗テストをピックアップ
pytest tests/ -v --tb=short 2>&1 | findstr FAILED

# 各失敗テストについて：
#   a) eval締切適用で「正しく選択順が変わった」ことを確認
#   b) assert値を修正（assert自体の削除/緩和は禁止）
```

### 4️⃣ コミット

```bash
git add src/services/process_assigner.py tests/...
git commit -m "feat(KVC): Change selection key from raw deadline to eval deadline in _pick_next_main_mountain"
```

### 5️⃣ PR作成 & レビュー

```bash
# PR作成時に以下を記載
# - 影響範囲確認レポート
# - テスト修正内容
# - eval締切キー変更の合理性
```

---

## トラブルシューティング

### Q1: STEP1でスクリプトが実行できない

**A**: 
```bash
# 仮想環境を確認
.venv\Scripts\Activate.ps1

# 依存パッケージを確認
pip install pandas openpyxl xlrd

# スクリプトを再実行
python analysis_impact_evaluation_deadline.py "SPOアップロード用.xlsx"
```

### Q2: STEP3で差分が出ない

**A**: 
- サンプルデータが小さすぎる可能性 → 実際のSPOアップロード用.xlsx で試してください
- eval締切と raw締切が同じ値の場合、選択順が変わらないのは**正常**です

### Q3: テストが大量に失敗する

**A**: 
- 各失敗テストについて、eval締切適用による選択順変化が**正しい**ことを確認
- 「想定外の副作用」が多い場合は、実装前に要件を再検討

### Q4: 07便がメイン通過しない

**A**: 
- ⚠️ **要件不満足** → 実装ストップ
- Q2（07便メイン通過）の前提条件を確認
- 他の制約（SET_FLAG_MAIN_LIMIT_SECS など）の影響を再検証

---

## 重要ポイント

### ✅ 必ず守ること

1. **本実装前の調査が必須**
   - STEP1-4 をすべて実行
   - チェックリストをすべて確認
   
2. **最小差分の厳守**
   - 変更: `_pick_next_main_mountain` のソートキーのみ
   - 変更禁止: `groupby("入車時間")`、KVC以外の挙動、テストassert削除
   
3. **07便メイン通過の必須確認**
   - Q2要件を満たす必須
   - NG の場合は実装ストップ
   
4. **副作用チェックの必須確認**
   - 07便以外の変化を許容か判断
   - 複数便に副作用がある場合は要再検証

5. **テストassert修正ルール**
   - eval締切による正しい選択順変化なら assert値を修正
   - assert削除・緩和は禁止
   - テスト値修正のみ許可

### ❌ してはいけないこと

- ❌ main ブランチに直接コミット（KVC受入分割ブランチ必須）
- ❌ assert削除・緩和（テスト値修正のみ）
- ❌ `groupby("入車時間")` 変更
- ❌ KVC以外の挙動変更
- ❌ 調査なしでの本実装

---

## 参考資料

### 関連ドキュメント

- [process_assigner.py](../src/services/process_assigner.py) - `_pick_next_main_mountain` の実装
- [構成ドキュメント.md](../構成ドキュメント.md) - システム全体
- [仕分け・割り振りルール.md](../docs/仕分け・割り振りルール.md) - ビジネスロジック

### 参照コード

```python
# 24時間軸補正（eval締切計算）
def _deadline_for_eval(deadline_val: Optional[int], start_or_end_secs: Optional[int]) -> Optional[int]:
    """業務日タイムラインへ正規化する。
    
    00:00〜02:59 は「前日2直の続き」とみなし +24h へ寄せる。
    これにより 23:xx と 00:xx を同一日の連続時刻として扱える。
    """
    if deadline_val is None:
        return None
    ddl = int(deadline_val)
    if start_or_end_secs is None:
        return ddl
    if int(start_or_end_secs) >= DAY_SECS and ddl < DAY_SECS:
        return ddl + DAY_SECS
    return ddl
```

---

## 最後に

**✅ このスクリプトで何ができるのか**:
1. ✅ eval締切キー変更の影響を実測で確認
2. ✅ 07便がメイン通過するか事前確認
3. ✅ 副作用（07便以外の工程変化）を事前検出
4. ✅ 既存テストの影響を事前予測
5. ✅ 本実装前のリスク評価

**⚠️ このスクリプトでできないこと**:
- 本実装（あくまで調査のみ）
- テスト修正（実装後に修正）

---

**作成日**: 2026-06-29  
**バージョン**: 1.0  
**状態**: 調査用（本実装前の必須ステップ）
