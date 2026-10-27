# SPO Staged Export — OneDrive同期競合回避ガイド

**更新日**: 2026-10-26

## 概要

従来の `export_spo_xlsx()` は固定ファイル名でOneDrive監視フォルダに直接出力していたため、Power Automate実行中の同期競合が発生する可能性がありました。

新しい `export_to_spo_staged()` は **staging + timestamp + move方式** を採用し、OneDrive/SharePoint同期競合を根本回避します。

---

## 実装概要

### 処理フロー

```
┌─────────────────────────────────┐
│ DataFrame                       │
└──────────────┬──────────────────┘
              ▼
┌─────────────────────────────────┐
│ staging領域                     │ ← 利用者別output配下の_staging（同期対象外）
│ (一意タイムスタンプ+UUID付き)  │
│ 1. Excel書込                    │
│ 2. テーブル化（SPOExport）     │
│ 3. 完成                         │
└──────────────┬──────────────────┘
              ▼
┌─────────────────────────────────┐
│ os.replace / shutil.move        │
│ (atomic + fallback)             │
└──────────────┬──────────────────┘
              ▼
┌─────────────────────────────────┐
│ watch_dir                       │ ← OneDrive監視フォルダ
│ (完成ファイルのみ移動)          │
│ Power Automate トリガー発動     │
└─────────────────────────────────┘
```

### 主な特徴

| 項目 | 従来方式 | 新方式（Staged） |
|-----|--------|-----------------|
| **ファイル名** | 固定（SPOアップロード用.xlsx） | タイムスタンプ+UUID（SPOアップロード用_20260714_070802_123456_a1b2c3d4.xlsx） |
| **書込先** | OneDrive同期フォルダ（watch_dir）直接 | staging領域で完成 → 移動 |
| **テーブル化** | 同期フォルダ内で実施 | staging領域で完成してから移動 |
| **同期フォルダへの操作** | Excel書込 → テーブル追加（2回アクセス） | os.replace で1回の移動のみ |
| **競合のリスク** | 高（Power Automate実行中に上書き/テーブル更新） | 最小化（完成品のみ移動） |

---

## API リファレンス

### `export_to_spo_staged()`

```python
from src.services.spo_export import export_to_spo_staged

result = export_to_spo_staged(
    df=spo_df,                      # 出力対象DataFrame
    watch_dir=r"C:\OneDrive\監視フォルダ",  # Power Automate監視フォルダ
    # staging_dir省略時は利用者別の既定領域を使用
    table_name="SPOExport",         # Excelテーブル名
    base_name="SPOアップロード用"    # ファイル名の基本部分
)
```

**引数**

| 引数 | 型 | 必須 | デフォルト | 説明 |
|-----|---|------|-----------|------|
| `df` | `pd.DataFrame` | ✅ | - | 出力対象のDataFrame |
| `watch_dir` | `str` | ✅ | - | Power Automate監視フォルダのパス |
| `staging_dir` | `str` |  | `DEFAULT_STAGING_DIR` | 利用者別のローカル一時領域（[保存先の正本](起動・exe化ガイド.md#4-windows利用者ごとの初回設定保存先)） |
| `table_name` | `str` |  | `"SPOExport"` | Excelテーブル名 |
| `base_name` | `str` |  | `"SPOアップロード用"` | ファイル名の基本部分 |

**戻り値**

| パターン | 戻り値 | 説明 |
|---------|--------|------|
| 成功 | `str` | 移動後の最終ファイルパス（例：`C:\OneDrive\監視フォルダ\SPOアップロード用_20260714_070802_123456_a1b2c3d4.xlsx`） |
| 空DataFrame | `None` | 処理をスキップ |
| エラー | 例外 raise | 詳細はログ出力 |

**例外**

- `FileNotFoundError`: 移動後のファイルが見つからない
- `OSError`: ファイルシステムエラー（権限不足など）
- その他の `Exception`: 処理中のエラー

**ログ出力**

すべての処理段階を `logging.INFO` / `logging.EXCEPTION` で記録します。

```python
import logging
logging.basicConfig(level=logging.INFO)
# export_to_spo_staged() 実行時にログが出力される
```

---

## 使用例

GUIは`src/services/exporter.py`の`export_spo_xlsx_staged()`を経由します。`staging_dir`省略時は起動時の現在ユーザーから解決した`DEFAULT_STAGING_DIR`を使い、試験などでは明示パスを渡せます。引数・実装の正本は同関数と`src/services/spo_export.py`です。

stagingは保存時に自動作成されます。旧`C:\Temp\spo_staging`の作成・権限付与は不要です。保存先の詳細は[起動・exe化ガイド 第4章](起動・exe化ガイド.md#4-windows利用者ごとの初回設定保存先)を参照してください。

---

## トラブルシューティング

### Q1: stagingフォルダが見つからない

**A**: 実出力時に利用者別領域へ自動作成されます。作成できない場合は、現在ユーザーのローカル保存領域の権限を確認してください。共有アプリ配置先へは退避しません。

### Q2: "cross-device link" エラーが出た

**A**: staging と watch_dir が異なるドライブにある場合、`os.replace` が失敗し `shutil.move` にフォールバックします。これは正常動作です。ログで確認できます。

```
export_to_spo_staged: os.replace 失敗（[Errno 18] Invalid cross-device link）、shutil.move にフォールバック
export_to_spo_staged: shutil.move で移動成功 (...)
```

### Q3: Power Automate が新ファイルを検出しない

**A**: Power Automate のトリガーが「ファイルが作成されたとき」の場合、タイムスタンプ付きの一意ファイル名により毎回新しいファイルとして検出します。

問題が続く場合は：
- Power Automate トリガーのフォルダ設定を確認
- OneDrive アプリの同期状態を確認
- 本番監視先へ確認用ファイルを勝手に作らない。動作試験は承認された別の試験用フォルダ・フローで実施する

---

## 内部仕様（開発者向け）

### ファイル名生成ロジック

```python
def _generate_unique_filename(base_name: str) -> str:
    """
    例: SPOアップロード用_20260714_070802_123456_a1b2c3d4.xlsx
    
    構成:
    - base_name:    "SPOアップロード用"
    - timestamp:    "20260714_070802"（YYYYMMDD_HHMMSS）
    - microseconds: "123456"（6桁）
    - uuid_prefix:  "a1b2c3d4"（UUID4の先頭8文字）
    
    一意性の保証:
    - 同一秒内の異なる呼び出し → マイクロ秒で区別
    - 同一マイクロ秒の呼び出し → UUID4で保証
    - 同一プロセス内の並行呼び出し → _export_lock で直列化
    """
```

### エラーハンドリング

処理中に例外が発生した場合：

1. staging ファイルが存在していれば削除
2. watch_dir の不完全ファイルが存在していれば削除
3. 例外を re-raise

```python
except Exception as e:
    # cleanup logic
    if os.path.exists(staging_path):
        os.remove(staging_path)
    if os.path.exists(final_path):
        os.remove(final_path)
    raise  # re-raise で呼び出し元へ伝播
```

---

## テスト

単体テスト（pytest）:

```bash
cd "c:\Users\1588386\DIG_Project\CHかんばんセット"

# 新関数のテストのみ
pytest tests/unit/test_spo_export.py::test_export_to_spo_staged_creates_file_in_watch_dir_after_move -xvs

# 全 SPO テスト
pytest tests/unit/test_spo_export.py -xvs
```

テストケース：
- ✅ 一意なファイル名生成
- ✅ 空DataFrame時の None 返却
- ✅ staging → watch_dir の正常移動
- ✅ os.replace 失敗時の shutil.move フォールバック
- ✅ 例外時の cleanup

---

## 今後の展開

### Phase 5: 統合テスト（予定）
- GUI → export_spo_xlsx_staged() → Power Automate の E2E テスト
- OneDrive 監視フォルダでの実データ動作確認

### Phase 6: 運用（予定）
- Power Automate 側の「ファイル削除」ロジック確認
- 古い固定名ファイル（SPOアップロード用.xlsx）の廃止判定
- watch_dir のクリーンアップ戦略（N世代保持など）

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/services/spo_export.py` | `_generate_unique_filename()` / `export_to_spo_staged()` 実装 |
| `tests/unit/test_spo_export.py` | ユニットテスト（12テスト、全 PASS） |
| `src/services/exporter.py` | `export_spo_xlsx()` 既存関数（変更なし） |

---

## 参考資料

- OneDrive 同期の基本: https://docs.microsoft.com/ja-jp/onedrive/sync
- Power Automate トリガー: https://docs.microsoft.com/ja-jp/power-automate/desktop/actions-reference/sharepoint
- Python `os.replace()` vs `shutil.move()`: https://docs.python.org/ja/3/library/os.html#os.replace
