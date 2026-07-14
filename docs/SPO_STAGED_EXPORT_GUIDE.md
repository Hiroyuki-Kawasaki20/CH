# SPO Staged Export — OneDrive同期競合回避ガイド

**更新日**: 2026-07-14

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
│ staging領域                     │ ← C:\Temp\spo_staging（同期対象外）
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
    staging_dir=r"C:\Temp\spo_staging",   # staging領域（同期対象外）
    table_name="SPOExport",         # Excelテーブル名
    base_name="SPOアップロード用"    # ファイル名の基本部分
)
```

**引数**

| 引数 | 型 | 必須 | デフォルト | 説明 |
|-----|---|------|-----------|------|
| `df` | `pd.DataFrame` | ✅ | - | 出力対象のDataFrame |
| `watch_dir` | `str` | ✅ | - | Power Automate監視フォルダのパス |
| `staging_dir` | `str` |  | `C:\Temp\spo_staging` | staging領域のパス（OneDrive/SharePoint同期対象外） |
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

### 基本的な使い方（exporter.py を修正）

```python
# 従来の export_spo_xlsx（変更なし）
def export_spo_xlsx(spo_df: pd.DataFrame, out_dir: str, base_name: str = "SPOアップロード用") -> str:
    """既存関数：互換性維持のため変更しない"""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(out_dir, f"{base_name}.xlsx")
    export_to_spo(spo_df, output_path=path)
    return path

# 新しい export_spo_xlsx_staged（新規追加）
def export_spo_xlsx_staged(
    spo_df: pd.DataFrame,
    watch_dir: str,
    staging_dir: str = r"C:\Temp\spo_staging",
    base_name: str = "SPOアップロード用"
) -> Optional[str]:
    """
    Staging方式でSPO Excel出力（OneDrive同期競合回避）
    
    Args:
        spo_df: 出力対象DataFrame
        watch_dir: Power Automate監視フォルダのパス
        staging_dir: staging領域（デフォルト: C:\Temp\spo_staging）
        base_name: ファイル名の基本部分
    
    Returns:
        最終ファイルパス（成功時）、None（空DataFrame時）
    """
    from src.services.spo_export import export_to_spo_staged
    return export_to_spo_staged(
        df=spo_df,
        watch_dir=watch_dir,
        staging_dir=staging_dir,
        table_name="SPOExport",
        base_name=base_name
    )
```

### ファイル構成（環境に応じた例）

```
C:\OneDrive\工程管理
    └── SPO監視フォルダ/             ← Power Automate監視先
        ├── SPOアップロード用_20260714_070802_123456_a1b2c3d4.xlsx
        ├── SPOアップロード用_20260714_080115_234567_b2c3d4e5.xlsx
        └── (ancient files...)      ← 自動削除対象（不要な古いファイル）

C:\Temp\spo_staging\                ← staging領域（OneDrive同期対象外）
    └── (一時ファイルなし)          ← 移動完了後はクリーンアップ
```

### 環境構築

```powershell
# staging フォルダを作成
New-Item -ItemType Directory -Force -Path "C:\Temp\spo_staging"
Get-Acl "C:\Temp\spo_staging" | Format-List
```

---

## トラブルシューティング

### Q1: `C:\Temp\spo_staging` が見つからない

**A**: staging フォルダは自動作成されます。ただし、アクセス権限が必要です。

```powershell
# 権限確認
icacls "C:\Temp"
# BUILTIN\Users が「(OI)(CI)F」（フルコントロール）で表示されることを確認
```

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
- `watch_dir` に手動でテスト用 Excel を作成して、Power Automate が検出するか確認

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
