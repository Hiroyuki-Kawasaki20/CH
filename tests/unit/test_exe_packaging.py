"""PyInstaller未導入でも配布specの狭い収集範囲を検証する。ビルド試験とは別。"""
import ast
from pathlib import Path

import customtkinter


SPEC_PATH = Path(__file__).resolve().parents[2] / "CH_kanban_set_GUI.spec"


def test_spec_collects_only_customtkinter_assets():
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    assignments = {node.targets[0].id: node.value for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    data = assignments["datas"]
    assert isinstance(data, ast.Call)
    assert isinstance(data.func, ast.Name)
    assert data.func.id == "collect_data_files"
    assert [ast.literal_eval(arg) for arg in data.args] == ["customtkinter"]
    assert {kw.arg: ast.literal_eval(kw.value) for kw in data.keywords} == {"includes": ["assets/**/*"]}
    assert ast.literal_eval(assignments["hiddenimports"]) == []
    assert "collect_submodules" not in SPEC_PATH.read_text(encoding="utf-8")


def test_customtkinter_assets_pattern_contains_theme_fonts_and_icon():
    package = Path(customtkinter.__file__).parent
    assets = [path for path in package.glob("assets/**/*") if path.is_file()]
    assert package / "assets/themes/blue.json" in assets
    assert any(path.suffix == ".ttf" for path in assets)
    assert any(path.suffix == ".ico" for path in assets)


def test_spec_keeps_onedir_and_no_personal_data_literal():
    source = SPEC_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert any(node.func.id == "COLLECT" for node in calls)
    exe = next(node for node in calls if node.func.id == "EXE")
    assert any(kw.arg == "exclude_binaries" and ast.literal_eval(kw.value) is True for kw in exe.keywords)
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for value in literals:
        assert not any(name in value for name in ("ch_kanban_settings.json", "入車時間マスタ", "_export_archive", ".csv", ".log", "tests", "scripts"))
    compile(source, str(SPEC_PATH), "exec")


def test_spec_excludes_only_unused_torch():
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    analysis = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    excludes = next(keyword.value for keyword in analysis.keywords if keyword.arg == "excludes")
    # 元の除外リストは空。無関係な除外や重複を増やさない。
    assert ast.literal_eval(excludes) == ["torch"]
