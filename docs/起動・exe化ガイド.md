# 旧・起動 / exe化ガイド

> この文書は過去の起動・exe手順です。現行運用ではexeを使用・配布しません。bat起動、本人のDIG_new、ユーザー別設定の現行手順は [環境構築手順書.md](環境構築手順書.md) を参照してください。

## 現行運用

アプリの起動と初回設定には上記の現行手順書を使用してください。この文書の以下のexe作成・配布内容は現行運用の手順ではありません。

## 過去のexe配布手順（現行運用では不使用）

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

## 過去の運用メモ

- 開発者: `run_ch_kanban.bat` で起動
- 利用者: `dist\CH_kanban_set\CH_kanban_set.exe` のショートカットをデスクトップ配置
- 毎日の起動忘れ防止: Windowsタスクスケジューラでログオン時起動

## 過去の注意点

- 設定ファイル `ch_kanban_settings.json` はexe起動時、exeと同じフォルダを参照します。
- 入力CSV/マスタの置き場所はアプリの設定値（base_dir）に依存します。
- 共有フォルダ運用時は、出力先の書き込み権限を事前確認してください。
