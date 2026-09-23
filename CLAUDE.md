# CLAUDE.md

Claude Code がこのリポジトリで作業するときの前提・規約をまとめた正本です。
セッション開始時に自動で読み込まれます。詳細な業務ルールや手順書は `docs/` 配下を参照してください。

## プロジェクト概要

CHラインのかんばんを仕分け、**3レーン構成**の工程へ割り振るデスクトップGUIアプリ（Python + customtkinter）。
出荷情報CSV・出荷場一覧CSV・入車時間マスタを読み込み、仕分け結果の表示とSPOアップロード用Excelの出力を行う。

- 業務ルールの**正本**: [docs/仕分け・割り振りルール.md](docs/仕分け・割り振りルール.md)
- 要件 / 構成: [docs/requirements.md](docs/requirements.md) / [docs/architecture.md](docs/architecture.md)
- 利用者向け操作手順: [docs/利用マニュアル.md](docs/利用マニュアル.md)

## 開発環境とコマンド

Python **3.11**（3.11.14 で動作確認）／conda環境名は **`DIG_new`** 固定（`run_ch_kanban.bat` が前提にしている）。

```powershell  
# 環境の有効化  
conda activate DIG_new  
  
# アプリ起動（通常は run_ch_kanban.bat をダブルクリック）  
python -m src.app.gui  
  
# テスト  
python -m pytest -q                            # 全件（testpaths = tests）  
python -m pytest tests/unit/test_sorter.py -q  # 単体で確認したいとき  
```

- **`python src/app/gui.py` のような直実行は禁止。** `src` パッケージ前提のため import が壊れる。必ず `-m src.app.gui`。
- 初回セットアップは [docs/環境構築手順書.md](docs/環境構築手順書.md)、exe配布は [docs/起動・exe化ガイド.md](docs/起動・exe化ガイド.md)。

## リポジトリ規約

- **マジックナンバーを書かない。** 閾値・バッファ秒数などの定数は `src/models/constants.py` に集約し、ドキュメント側（仕分け・割り振りルール.md 付録A）と値を一致させる。
- **ドキュメントは正本を1つに保つ。** 同じ内容を2ファイルに書かず、参照リンクで繋ぐ。数値を直すときはコード実値と照合する。
- **コード変更時は `src/app/gui.py` の `APP_VERSION` を更新する**（既存の書式を維持）。
- ブランチは `docs/...` `feat/...` `fix/...` 等の接頭辞付き。1PR＝1テーマで、PR本文に「概要／変更内容／残タスク」を書く。
- `main` への直接コミットはしない。

## 注意点（ハマりどころ）

- **実運用データはGit管理外**（`.gitignore` 済み）。コミットしようとしないこと。
  - `入車時間マスタ.xlsx`、`SPOアップロード用.xlsx`、`*_audit.csv`、`_export_archive/`
  - `config/lane_end_times_history.json` … 端末ごとの作業結果なので共有しない
- `config/ch_kanban_settings.json` の `base_dir` / `export_dir` は**PCごとに異なる**。テストや例に実パスを埋め込まない。
- 休憩明けの再開時刻は休憩種別で異なる（短休憩と食事休憩で別定数）。値は `constants.py` と仕分け・割り振りルール.md 付録Aを参照し、記憶で書かない。
- `docs/_archive/` 配下は歴史的資料。現行仕様として扱わない。
- pytest は `_archive` `_tmp` を走査対象から除外している（`pytest.ini`）。

## 参照（自動で読み込む）

コーディング規約の正本:

@prompts/coding-rules.md

元プロジェクトとの関係・工程の定義:

@.claude/context.md