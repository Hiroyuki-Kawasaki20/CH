# CHかんばんセット — コーディングルール

## 言語・命名
- 日本語コメント・変数名を積極的に使用する
- エンコーディングは常に `utf-8`
- GUIフォントは `Meiryo UI` を統一で使う

## GUI
- CustomTkinter ウィジェット名は `ctk.CTk*` を使用する
- `ttkbootstrap` は使わない（CustomTkinter に移行済み）
- Treeview, Listbox はそのまま tkinter/ttk を使用する

## データ処理
- pandas vectorized操作を優先（ループは最小限）
- 数値型変換は `errors="coerce"` で安全に行う
- Excel出力時は `_protect_excel_injection()` でインジェクション対策を行う
- 全角→半角正規化を徹底する

## モジュール構成
- `src/models/` — 定数・データモデル
- `src/utils/` — ユーティリティ（正規化、CSV、Excel操作）
- `src/services/` — ビジネスロジック（仕分け、工程割当、出力）
- `src/app/` — GUI
- `tests/` — テスト

## エラーハンドリング
- ファイル読み込み時は存在チェック＋必須列検証
- GUIからの操作はtry/exceptでラップし、messagebox表示
- 起動時の `load_master()` は `self.after(200, ...)` で遅延実行
