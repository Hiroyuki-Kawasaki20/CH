"""PyInstaller未導入でも配布specの狭い収集範囲を検証する。ビルド試験とは別。"""
import ast
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import customtkinter
import pytest


SPEC_PATH = Path(__file__).resolve().parents[2] / "CH_kanban_set_GUI.spec"
HOOK_PATH = SPEC_PATH.parent / "build_hooks" / "hook-mkl.py"
MKL_CPU_DLLS = (
    "libimalloc.dll", "mkl_rt.2.dll", "mkl_core.2.dll", "mkl_intel_thread.2.dll",
    "mkl_sequential.2.dll", "mkl_def.2.dll", "mkl_mc3.2.dll", "mkl_avx2.2.dll",
    "mkl_avx512.2.dll", "mkl_vml_def.2.dll", "mkl_vml_mc3.2.dll",
    "mkl_vml_avx2.2.dll", "mkl_vml_avx512.2.dll", "mkl_vml_cmpt.2.dll",
)


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


@pytest.fixture
def fake_conda_runtime(monkeypatch, tmp_path):
    # PyInstaller未導入の開発環境では既存の静的テストだけを実行できる。
    pytest.importorskip("PyInstaller")
    from PyInstaller import compat
    from PyInstaller.utils.hooks import conda_support

    prefix = tmp_path / "active-environment"
    lib_dir = prefix / "Library/bin"
    lib_dir.mkdir(parents=True)
    names = {"mkl": MKL_CPU_DLLS + ("mkl_blacs_lp64.2.dll", "mkl_tbb_thread.2.dll"),
             "intel-openmp": ("libiomp5md.dll", "libiomp5md_db.dll")}
    dlls = {}
    metadata = {}
    for package, filenames in names.items():
        dlls[package] = []
        for name in filenames:
            path = lib_dir / name
            path.write_bytes(b"test DLL placeholder")
            dlls[package].append((str(path), "."))
        cache = tmp_path / "package-cache" / package
        license_dir = cache / "info/licenses/vendor"
        license_dir.mkdir(parents=True)
        for name in ("license.txt", "tpp.txt"):
            (license_dir / name).write_text("test notice", encoding="utf-8")
        metadata[package] = SimpleNamespace(raw={"link": {"source": str(cache)}})
    for folder in ("share/doc/mkl/licensing", "share/doc/compiler/licensing/openmp"):
        notice_dir = prefix / folder
        notice_dir.mkdir(parents=True)
        (notice_dir / "third-party-programs.txt").write_text("test notice", encoding="utf-8")
    (prefix / "ch_kanban_settings.json").write_text('{"base_dir":"private"}', encoding="utf-8")
    (prefix / "入車時間マスタ.xlsx").write_bytes(b"private")
    calls = []

    def collect(name, dest=".", dependencies=True):
        calls.append((name, dest, dependencies))
        return [item for item in dlls[name] if Path(item[0]).is_file()]

    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(compat, "is_win", True)
    monkeypatch.setattr(compat, "is_pure_conda", True)
    monkeypatch.setattr(conda_support, "collect_dynamic_libs", collect)
    monkeypatch.setattr(conda_support, "distribution", lambda name: metadata[name])
    return prefix, dlls, metadata, calls


def test_mkl_hook_collects_only_current_environment_runtime_and_notices(fake_conda_runtime):
    prefix, dlls, metadata, calls = fake_conda_runtime
    # 同じDLLの重複候補でも配置先は1件にする。
    dlls["intel-openmp"].append(dlls["intel-openmp"][0])
    result = runpy.run_path(str(HOOK_PATH))
    binaries, datas = result["binaries"], result["datas"]
    assert {Path(p).name for p, dest in binaries} == set(MKL_CPU_DLLS) | {"libiomp5md.dll"}
    assert len(binaries) == 15
    assert all(Path(p).parent == prefix / "Library/bin" and dest == "." for p, dest in binaries)
    assert calls == [("mkl", ".", False), ("intel-openmp", ".", False)]
    assert len(datas) == 6
    assert all(Path(p).suffix == ".txt" and Path(dest).parts[0] == "licenses" for p, dest in datas)
    assert {Path(p).name for p, dest in datas} == {"license.txt", "tpp.txt", "third-party-programs.txt"}


@pytest.mark.parametrize("filename", ["mkl_intel_thread.2.dll", "mkl_core.2.dll", "libiomp5md.dll"])
def test_mkl_hook_fails_when_required_dll_missing(fake_conda_runtime, filename):
    prefix, _, _, _ = fake_conda_runtime
    (prefix / "Library/bin" / filename).unlink()
    with pytest.raises(RuntimeError, match=filename.replace(".", r"\.")):
        runpy.run_path(str(HOOK_PATH))


def test_mkl_hook_rejects_dll_from_other_environment(fake_conda_runtime, tmp_path):
    _, dlls, _, _ = fake_conda_runtime
    foreign = tmp_path / "other-environment/libiomp5md.dll"
    foreign.parent.mkdir()
    foreign.write_bytes(b"other runtime")
    dlls["intel-openmp"][0] = (str(foreign), ".")
    with pytest.raises(RuntimeError, match="現在のPython環境"):
        runpy.run_path(str(HOOK_PATH))


def test_mkl_hook_requires_license_text(fake_conda_runtime):
    _, _, metadata, _ = fake_conda_runtime
    root = Path(metadata["mkl"].raw["link"]["source"])
    (root / "info/licenses/vendor/license.txt").unlink()
    with pytest.raises(RuntimeError, match="ライセンス"):
        runpy.run_path(str(HOOK_PATH))


def test_spec_activates_mkl_hook_without_personal_path():
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    analysis = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Analysis"
    )
    hook_paths = next(k.value for k in analysis.keywords if k.arg == "hookspath")
    assert any(isinstance(n, ast.Constant) and n.value == "build_hooks" for n in ast.walk(hook_paths))
    assert HOOK_PATH.is_file()
    for source in (SPEC_PATH, HOOK_PATH):
        assert "c:\\users\\" not in source.read_text(encoding="utf-8").lower()


def test_intel_runtime_is_excluded_from_upx_modification():
    from fnmatch import fnmatch

    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    collect = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "COLLECT"
    )
    patterns = ast.literal_eval(next(k.value for k in collect.keywords if k.arg == "upx_exclude"))
    assert all(any(fnmatch(name, pattern) for pattern in patterns)
               for name in MKL_CPU_DLLS + ("libiomp5md.dll",))
