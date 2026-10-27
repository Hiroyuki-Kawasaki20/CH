# Windows利用者別保存 — 検証記録・PR本文下書き

## 作業条件（2026-10-26）

- 起点: `main` / `63f185725db28a1bf7e9344782d1bfea492cd043`（PR #205）。開始時cleanを確認後、mainをfast-forward更新。
- 作業ブランチ: `fix/windows-user-local-settings`。
- Python: 3.11.14、既存conda環境`DIG_new`。CustomTkinter: 5.2.2。
- push・PR作成・マージ・本番SPO出力は実施しない。
- 旧設定・個人マスタ・実データ・生成物はコミット対象外。
- 保存先・初回設定・受入手順の正本は[起動・exe化ガイド](起動・exe化ガイド.md)、マスタ解決規則は[README](../README.md)。

## テスト実測

| 段階 | 結果 |
|---|---|
| 変更前・関連7ファイル | 120 passed |
| 変更前・全体 | 533 passed / 2 failed / 9 skipped / 4 xfailed / 2 xpassed |
| 新規利用者別テストのRED | 22 failed / 5 passed |
| 起動時マスタ未配置警告の追加RED | 1 failed（警告表示が0件） |
| 実装後・関連（配布テスト追加前） | 148 passed |
| 最終・関連9ファイル | 152 passed |
| 最終・全体 | 565 passed / 2 failed / 9 skipped / 4 xfailed / 2 xpassed |

- 全体収集は550件→582件（新規32件）。新規は利用者別・起動案内28件、GUI出力権限エラー1件、配布spec・リソース検証3件。
- REDのImportErrorは未実装`app_paths`の1件だけ。他21件は旧repo/exe隣パス、A/B混在、非辞書JSON、直接上書きによる設定破損、旧マスタ採用、固定ログ/出力先を既存APIで再現。
- `test_pickup_master_excel_text_format.py`を含む関連回帰が成功。AST比較でも`_write_master_excel`、`save_pickup_time_master_xlsx`、`load_pickup_time_master_xlsx`、`_rescue_master_dataframe`は起点から無変更。
- 既知#187の失敗2件は変更前後で同一。仕分けロジックやその期待値は変更していない。
  - `TestGrouping.test_size1_rescue_split_urgent_vendor_when_deadline_floor_conflict`（`2 != 2`）
  - `TestGrouping.test_size1_rescue_split_applies_to_non_takaoka_vendor`（`1 != 1`）
- GUIの全関数名集合も起点と一致。変更対象Pythonファイルのエディタ診断エラーなし。

### 隔離方法・未検証範囲

- ベースラインは`TemporaryDirectory`へ設定・ローカル出力・終了時刻履歴を差し替えて実行。変更後はpytestのimport前に`LOCALAPPDATA`を一時ディレクトリへ変更して実行し、定数の起動時評価も隔離。
- 各利用者分離テストは`tmp_path`と環境変数差し替えを使用。REDでも実設定を読まないよう旧repo/exe配置先を一時パスへ偽装。
- 起動時評価の`LOCAL_OUTPUT_DIR`・`DEFAULT_STAGING_DIR`はA/Bを別Pythonプロセスで検証。設定・GUIパス・履歴は呼出時に環境変数を解決する。
- 本番入力を読む`test_kvc_ukeire_gui_integration.py`の3件は、ベースライン・最終とも実行時フックで明示skip。その他6件のskip、4 xfail、2 xpassも変更なし。テストのソースにskipやxfailを追加して隠してはいない。
- `pytest.ini`の全体対象`tests`を実行。実マスタ保護の既存`conftest`も維持した。
- フォルダ選択は既存関数に対するダイアログのモックで検証。exeの対話GUI・別Windowsアカウント・condaなし環境での実機試験ではない。

### 既存テストの変更理由

`tests/unit/test_master_path_resolution.py`の7件のみ仕様変更に伴う期待を変更した。

- 候補列挙4件: 旧「設定候補＋legacy」→「設定候補のみ」。
- 解決先3件: 旧「legacyだけ存在／設定親不在／全親不在ならlegacy」→「設定候補を維持」。関数名も新仕様へ変更。
- 設定内の`master_path`/`base_dir`優先、明示legacy引数、OSError処理、救済保存、書式の期待は維持。無関係な期待値変更なし。

## exe配布検証

- 個人設定JSONの必須入力・同梱を削除。CustomTkinterの`assets/**/*`だけを明示収集。onedir構成を維持。
- 静的テストでspecの収集範囲・onedir・個人データ指定なしを確認。既存CustomTkinterに`blue.json`・`.ttf`・`.ico`が存在し、指定パターンに入ることを確認。
- `DIG_new`のPyInstaller照会は`PackageNotFoundError`。**ビルド未実施、exe生成なし**。新規インストール・環境変更は行っていない。
- 残作業: 開発者がPyInstallerを準備し、[ガイド第2章](起動・exe化ガイド.md#2-exe配布版の作成pyinstaller)に沿ってビルドする。続いて[第5章の別Windowsアカウント試験](起動・exe化ガイド.md#5-別windowsアカウントでの受入試験利用者実施)を実施する。ビルド成功だけで実機検証済みとしない。

## PR本文下書き（未作成）

### 概要

同じPCを別Windowsアカウントで使えるよう、かんばんセットの設定・ローカル出力・前回工程終了時刻を利用者別領域へ変更する。exe配布を使う利用者にPython・Minicondaを要求しないため、既存onedir specの個人設定同梱を除去する。

### 変更内容

- Tk非依存の`app_paths`を追加。開発版・exe版共通で現在ユーザーの保存領域を使用。importだけでは作成しない。
- 設定を利用者別JSONだけから読み書きし、同一ディレクトリの一時ファイル＋`os.replace`で保存。不正/非辞書JSONは初期状態とする。
- **設定・旧共有履歴の自動移行なし。河崎本人を含め初回に入力先・出力先を選び直す。前回工程終了時刻もWindows利用者別となり、別ユーザーへ自動共有しない。**
- ログ・履歴Excel・未ヒットCSV・既定アーカイブ・stagingはローカルへ分離。SPO本体は選択した`export_dir`のまま。
- マスタは設定内の既存優先規則を維持し、repo/exe隣への暗黙フォールバックを除去。文字列書式`@`・入力用100行・`PickupTimeMaster`・列名・時刻解釈・救済保存は変更しない。
- CustomTkinter assetsを明示同梱。onedir一式配布、利用者ごとの権限・OneDrive同期、同時編集/同時出力回避、Windows切替前終了を文書化。
- テスト追加32件。全体565 passed、既知#187の2 failedは変更前と同じ。関連152 passed。詳細と隔離条件は本記録を参照。

### 残タスク

- [ ] 開発者によるPyInstallerの準備とexeビルド（今回未導入のため未実施）
- [ ] 別Windowsアカウント・Python/condaなし・配布フォルダ書込不可での実機試験
- [ ] 各利用者のSPO権限とOneDrive同期の準備・確認（フォルダ存在だけでは同期完了を保証しない）
- [ ] 既知#187の2失敗は別テーマで対応

本作業ではpush・PR作成・マージ・本番SPO出力は行わない。
