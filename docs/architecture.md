# CHかんばんセット — システム構成

## 1. 概要

CH受入のかんばん仕分けと工程割当を行う業務アプリです。現行の主系統は `CustomTkinter GUI`（`src/app/gui.py`）で、
処理結果をセットボード表示し、SPOアップロード用Excelを自動出力します。

実装は「UI」と「ドメインロジック（仕分け/割当/出力）」を `src` 配下で分離しています。

## 2. ディレクトリ構成（現行）

```text
CHかんばんセット/
├─ src/
│  ├─ app/
│  │  └─ gui.py                    # CustomTkinterメインUI
│  ├─ models/
│  │  └─ constants.py              # 定数（工程名・休憩時間・工数式・色など）
│  ├─ services/
│  │  ├─ data_loader.py            # 入力データ読込・設定読込保存
│  │  ├─ sorter.py                 # 仕分けパイプライン（山作成）
│  │  ├─ process_assigner.py       # 既存割当ロジック（後方互換の基準）
│  │  ├─ scheduler.py              # 新スケジューラ（EDF+同便クラスター+部分充填）
│  │  ├─ exporter.py               # SPO/帳票/HTML出力
│  │  └─ spo_export.py             # SPO出力の安全化（temp書込+同期待機）
│  └─ utils/
│     ├─ normalizer.py             # 文字列・時刻正規化
│     ├─ csv_utils.py              # CSV読込補助
│     └─ excel_utils.py            # Excel書込補助
├─ config/
│  └─ ch_kanban_settings.json      # base_dir/export_dir/自動再読込分など
├─ tests/
│  ├─ unit/
│  │  ├─ test_data_loader.py
│  │  ├─ test_sorter.py
│  │  └─ test_spo_export.py
│  └─ integration/
│     └─ __init__.py
├─ qt_setboard/                    # PySide6/QML版セットボード（別系統）
│  ├─ main.py
│  ├─ models.py
│  ├─ schedule.py
│  ├─ service.py
│  └─ qml/
└─ docs/
   ├─ requirements.md
   ├─ architecture.md
   ├─ 仕分け・割り振りルール.md
   ├─ 利用マニュアル.md
   └─ 起動・exe化ガイド.md
```

## 3. 主な依存関係

```text
gui.py
  ├─ data_loader.py
  │   ├─ csv_utils.py
  │   └─ normalizer.py
  ├─ sorter.py
  │   └─ normalizer.py
  ├─ process_assigner.py
  │   ├─ constants.py
  │   └─ normalizer.py
  ├─ scheduler.py
  │   ├─ process_assigner.py
  │   ├─ constants.py
  │   └─ normalizer.py
  └─ exporter.py
      ├─ spo_export.py
      ├─ excel_utils.py
      └─ constants.py
```

補足:
- `scheduler.py` は `process_assigner.py` の関数/定数を再利用し、比較評価で採否判定します。
- `exporter.py` は `spo_export.py` を経由してSPO出力の競合リスクを低減します。

## 4. 実行フロー（GUI）

```text
入力データ読込（CSV/Excel + 設定）
  ↓
選択条件（便名/受入/オーダー）で絞込
  ↓
sorter.run_pipeline（山作成・混載）
  ↓
process_assigner / scheduler による工程割当
  ├─ 新スケジューラ結果が同等以上: 採用
  └─ 劣後: 既存ロジックへフォールバック
  ↓
（任意）バッテリー交換ON時: 仮想山(-1)を時刻確定後に注入
  ↓
セットボード更新（メイン/リリーフ/あふれ）
  ↓
SPO用Excel自動出力
  ├─ 未ヒット一覧CSV出力（必要時）
  └─ 履歴追記（可能時）
```

## 5. 工程割当アーキテクチャ（CH固有）

- 工程は `メイン` / `リリーフ` / `あふれ` の3区分です。
- 締切は「入車時間 - 10分」を基本に扱います。
- 休憩時間と照合180秒ルールを加味して開始/終了時刻を計算します。
- メインとリリーフの両方で締切を満たせない山は `あふれ` として警告レーンへ表示します。

## 6. データと設定

- 入力データ:
  - 出荷情報CSV（CH版優先）
  - 出荷場一覧CSV
  - 入車時間マスタExcel
- 設定ファイル:
  - `config/ch_kanban_settings.json`
  - 主なキー: `base_dir`, `export_dir`, `auto_reload_minute`

## 7. 出力物

- `SPOアップロード用.xlsx`（主出力）
- `SPOアップロード用_未ヒット一覧.csv`（入車時間未マッチがある場合）
- 履歴追記ファイル（`append_to_spo_history` が書込可能な場合）
- 補助出力（ユーティリティとして実装済み）:
  - セットボードHTML
  - 工程別かんばん明細Excel

## 8. 補足（別系統UI）

`qt_setboard` は PySide6/QML のタイムラインUI実装です。現行運用の主系統は `src/app/gui.py` であり、
`qt_setboard` は検証・拡張用の別系統として扱います。
