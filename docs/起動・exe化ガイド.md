# CHかんばんセット 起動・exe化ガイド

このガイドは、VS Codeを開かずに起動・運用するための最短手順です。

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
- 配布時は `dist\CH_kanban_set` フォルダごと渡す（onedir構成）

## 3. 運用のおすすめ

- 開発者: `run_ch_kanban.bat` で起動
- 利用者: `dist\CH_kanban_set\CH_kanban_set.exe` のショートカットをデスクトップ配置
- 毎日の起動忘れ防止: Windowsタスクスケジューラでログオン時起動

## 4. 注意点

- 設定ファイル `ch_kanban_settings.json` はexe起動時、exeと同じフォルダを参照します。
- 入力CSV/マスタの置き場所はアプリの設定値（base_dir）に依存します。
- 共有フォルダ運用時は、出力先の書き込み権限を事前確認してください。
