# CHかんばんセット 起動・exe化ガイド

このガイドは、VS Codeを開かずに起動・運用するための最短手順です。

**exe配布版を使う利用者はPython・Minicondaのインストール不要です。** 開発者が用意したonedirフォルダ一式から起動します。ソース・bat起動を使う開発者には、引き続きconda環境`DIG_new`が必要です（[環境構築手順書.md](環境構築手順書.md)）

## 1. ワンクリック起動（bat）

プロジェクト直下にある [run_ch_kanban.bat](../run_ch_kanban.bat) をダブルクリックしてください。

### 1.1 実行内容
- `conda run -n DIG_new` で環境を切り替え
- `python -m src.app.gui` でGUIを起動

### 1.2 自己診断（起動テスト）

PowerShell で次を実行します。

```powershell
./run_ch_kanban.bat --self-test
```

成功時:

```text
[OK] self-test passed. conda + DIG_new + python are available.
```

### 1.3 うまく起動しない場合
- condaが未インストール
- conda環境名が `DIG_new` ではない
- Python依存パッケージが不足

`run_ch_kanban.bat` は診断ログを出力します。

- ログファイル: `%TEMP%\run_ch_kanban_startup.log`
- まず `CONDA_CMD=...` と `self-test success` の有無を確認

必要に応じて PowerShell で以下を実行してください。

```powershell
conda run -n DIG_new python -m src.app.gui
```

## 2. exe配布版の作成（PyInstaller）

GUI専用specとして `CH_kanban_set_GUI.spec` を追加済みです。

### 2.1 初回のみ

```powershell
conda activate DIG_new
pip install pyinstaller
```

### 2.2 ビルド手順

プロジェクトルートで実行:

```powershell
conda activate DIG_new
pyinstaller CH_kanban_set_GUI.spec --noconfirm --clean
```

### 2.3 生成物
- 実行ファイル: `dist\CH_kanban_set\CH_kanban_set.exe`
- **配布時は `dist\CH_kanban_set` フォルダ一式を渡す（onedir構成）。exe単体をコピーしない。** `_internal`等の実行リソースも必要です。
- specはCustomTkinterのテーマ・フォント等の`assets`を収集します。個人用設定JSON・入車時間マスタ・入力CSV・ログ・アーカイブは同梱しません。テストや解析スクリプトの一括収集もしません。
- 配布フォルダには各利用者の読み取り・実行権限が必要です。通常動作の保存のために配布フォルダへの書込権限は要求しません。
- 生成した`build`・`dist`はGitへ登録しません。ビルド成功と「別Windowsユーザー・condaなしで動作確認済み」は別です。

## 3. 運用のおすすめ

- 開発者: `run_ch_kanban.bat` で起動
- 利用者: `dist\CH_kanban_set\CH_kanban_set.exe` のショートカットをデスクトップ配置
- 毎日の起動忘れ防止: Windowsタスクスケジューラでログオン時起動

## 4. Windows利用者ごとの初回設定・保存先

開発版とexe版は同じ規則です。アプリ内ユーザー切替はなく、Windowsへログインした利用者の保存領域を使います。

| 保存内容 | 保存先 |
|---|---|
| 設定（入力先・出力先等） | `%LOCALAPPDATA%\CHKanban\ch_kanban_settings.json` |
| ローカル履歴Excel・未ヒットCSV等 | `%LOCALAPPDATA%\CHKanban\output` |
| GUIログ | 上記`output\logs`（`ch_kanban.log`等） |
| 既定アーカイブ | 上記`output\_export_archive`（明示`archive_dir`があればそちら） |
| SPO出力の一時作成先 | 上記`output\_staging` |
| 前回工程終了時刻の履歴 | `%LOCALAPPDATA%\CHKanban\lane_end_times_history.json` |
| SPO本体Excel | 利用者が選択した`export_dir`（従来どおり） |

`LOCALAPPDATA`が未設定なら、現在ユーザーのホーム配下`AppData\Local\CHKanban`を使います。フォルダは保存・初期化時に作成します。他ユーザー、repo、共有アプリ配置先へはフォールバックしません。batの起動診断ログは従来どおり利用者の`%TEMP%\run_ch_kanban_startup.log`です。

### 初回起動

1. **各Windows利用者が**同じSPO実体への必要な権限とOneDrive同期を準備します。同期先のローカルパスは利用者ごとに異なって構いません。
2. 既存の選択ダイアログで入力フォルダを選びます。出荷情報CSV・出荷場一覧CSVを配置し、通常は`入車時間マスタ.xlsx`もその直下に置きます。
3. 続くダイアログでSPO出力フォルダを選びます。2回目以降は、その利用者の設定を再利用します。
4. マスタ未配置時は案内を確認し、選択した入力フォルダへ配置します。マスタの詳細な解決規則は[README](../README.md#入車時間マスタの管理sharepoint同期フォルダ)を参照してください。

**旧repo内・exe隣の設定や共有履歴は自動移行しません。河崎本人も初回は入力先・出力先を選び直してください。** 他人の`base_dir`・`export_dir`・`master_path`・`archive_dir`をコピーしないでください。既存の独自設定キーは、新しい利用者別設定の通常の読込・保存では保持します。不正JSON・辞書でないJSONは警告ログを残して初期状態として扱い、読込だけでは書き換えません。保存は一時ファイルからの置換で行い、失敗時はエラーを通知します。

### 運用上の注意

- **前回工程終了時刻はWindows利用者ごとになります。別ユーザーへ自動共有・引継ぎはしません。** 切替後に画面の時刻を確認してください。
- 同じSPOマスタの同時編集・同時出力を避けてください。Windowsユーザーを切り替える前にアプリを終了してください。
- フォルダの存在確認だけではSPO同期完了は保証しません。OneDriveの起動・同期状態を各利用者が確認してください。
- 書込権限を調べるための試験ファイルはSPO監視先へ作りません。実出力で権限エラーが出たら、対象フォルダの権限やExcelの使用状態を確認してください。設定・ログ・履歴を監視先に混ぜないでください。
- フォルダを選び直す場合はアプリを終了し、**自分の**設定JSONの`base_dir`または`export_dir`キーだけを削除して再起動すると既存ダイアログが再表示されます。他のキーを消さないでください。

## 5. 別Windowsアカウントでの受入試験（利用者実施）

1. 開発者がビルドしたonedirフォルダ一式を、メンバーが読取・実行できる場所に配置する。
2. 本番とは別の入力CSV・マスタのコピーと、**監視されていない試験用出力フォルダ**を準備する。本番SPOへの出力は行わない。
3. 利用者Aでexeを起動し、初回の入力・出力選択、マスタ読込、仕分け・試験用Excel出力、再起動後の設定と時刻履歴の再利用を確認する。
4. Aのアプリを終了して別Windows利用者Bへ切り替える。BにはPython・Minicondaがない状態で同じ配布フォルダから起動する。
5. Bにも初回ダイアログが出ること、Aの設定や前回終了時刻が出ないこと、B自身の保存領域にログ・設定・履歴が作られることを確認する。
6. Bで入力マスタを未配置にして案内を確認し、配布フォルダ隣の旧マスタを勝手に採用しないことを確認する。
7. 試験用出力先の書込権限不足を試し、成功通知にならず対象先のエラーが案内されることを確認する。配布フォルダへの書込権限なしでも通常起動できることを確認する。
8. Bを終了してAへ戻し、Aの設定・履歴が維持されていることを確認する。実機試験結果を記録してから配布可否を判断する。
