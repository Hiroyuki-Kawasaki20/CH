# Issue #52 再現テスト報告書

## 概要

Issue #52 の根本原因である `_serialize_lanes_final()` 関数の **% 86400 巻き戻し処理**（line 1797）の影響を検証する再現テストを作成しました。

## テスト戦略

### 目的
`src/services/process_assigner.py` の nested 関数 `_serialize_lanes_final()` が:
- **line 1797**: `rr["実開始時間"] = _seconds_to_hhmm(new_start % 86400)`
- この行により 24:xx → 00:xx への巻き戻しが発生し、
- その結果、**次山の start 順序が乱れ、締切超過が生じる**

という仮説を検証

### テストスイート

| # | テスト名 | 条件 | 状態 |
|---|---------|------|------|
| 1 | `test_issue52_serialize_lanes_final_affects_start_time` | シンプル 2 山同一納入先 | ✅ PASS |
| 2 | `test_issue52_midnight_wrapping_via_serialize_lanes_final` | 夜間入車（23:30）、長作業時間 | ✅ PASS |
| 3 | `test_issue52_direct_serialize_lanes_final_impact` | 複数ケース（同/異納入先）| ✅ PASS |
| 4 | `test_issue52_manual_before_after_comparison` | 夜間帯（23:45）、秒単位検証 | ✅ PASS |

### テスト結果

```
tests/unit/test_process_assigner_issue52_repro.py::test_issue52_serialize_lanes_final_affects_start_time PASSED [ 25%]
tests/unit/test_process_assigner_issue52_repro.py::test_issue52_midnight_wrapping_via_serialize_lanes_final PASSED [ 50%]
tests/unit/test_process_assigner_issue52_repro.py::test_issue52_direct_serialize_lanes_final_impact PASSED [ 75%]
tests/unit/test_process_assigner_issue52_repro.py::test_issue52_manual_before_after_comparison PASSED [100%]

============================== 4 passed in 1.74s ==============================
```

### ベースライン検証

```
5 failed, 219 passed, 2 skipped, 1 xfailed in 12.53s
```

- ✅ 新テスト 4 個追加: 215 → 219 passed
- ✅ 既存テスト failed: 5 (変わらず、後退なし)
- ✅ 既存テスト passed: 215 → 219 (+4, 新テスト分)

## 検証内容

### ケース 1: 同一納入先・同時刻入車
- **入車時刻**: 13:30
- **割当対象**: 2 山、メイン工程
- **結果**: 正常に直列化処理（時刻巻き戻し未観測）

### ケース 2: 夜間帯入車（23:30）
- **入車時刻**: 23:30
- **割当対象**: 3 山、長作業時間（移動工数 500秒）
- **結果**: 24:xx 巻き戻し条件設定も、実装上未発生
- **秒単位確認**: すべて当日内 (< 86400秒) に収まる

### ケース 3: 異納入先・分散入車
- **入車時刻**: 22:30 / 22:30
- **割当対象**: 異なる納入先各 2 山
- **結果**: メイン工程のみ割当、リリーフ化なし

### ケース 4: 手動比較（23:45 入車）
- **テスト内容**: 秒単位での時刻トラッキング
- **仮想締切**: 入車時刻 + 30分 (24:15 = 87300秒)
- **超過判定**: すべて超過なし

## 分析結果

### 現在の状態
1. **% 86400 巻き戻し処理は存在** (line 1797 確認済)
   ```python
   rr["実開始時間"] = _seconds_to_hhmm(new_start % 86400)
   ```

2. **ただし、実際の issue #52 症状（締切超過）は再現されていない**
   - テスト条件ではまだ 24:xx 状態が作られていない可能性
   - または、呼び出し側の条件（直列化前のレーン構成）が不足

3. **直列化の影響は観測不可**
   - 単山テストでは複数山同時発生がない
   - レーン内の競合状態が発生していない可能性

## 推奨される次のステップ

1. **実データベース検証**: 日野2026073113便など具体例で再現
   - 当時の SPO, master_df, previous_lane_end_times をそのまま使用

2. **メイン＋リリーフ同時割当テスト**
   - 単一レーン内で両工程競合が発生する条件設定

3. **複数day_shift spanning**
   - 深夜帯で複数日にまたがる場合を明示的にテスト

4. **_serialize_lanes_final の call stack 検証**
   - 本関数呼び出し直前の `results` 状態ダンプ
   - 処理後の結果比較で差分抽出

## ファイル参考

### 生成テストファイル
- `tests/unit/test_process_assigner_issue52_repro.py` (新規)
  - 4 個のテストケース
  - 各々が output file に結果を保存

### 出力ファイル
- `t133_issue52_repro.txt`
- `t133_issue52_midnight_test.txt`
- `t133_issue52_direct_impact.txt`
- `t133_issue52_manual_comparison.txt`

## 結論

✅ **テスト作成完了**
- 4 個の再現テスト全て PASS
- 既存テスト後退なし (5 failed, 219 passed)
- % 86400 巻き戻し処理は存在するが、単純なテスト条件では症状未再現

⏳ **実データ検証待ち**
- より複雑な condition（メイン+リリーフ同時割当等）での再現必要
- 過去の具体例（日野2026073113便）での直接検証推奨

---

**テスト実行日**: 2026-08-03  
**ブランチ**: `investigate/issue52-deadline-serialize-repro`  
**ベース commit**: `0f96419` (origin/main)
