# -*- coding: utf-8 -*-
"""MKL-SDLの動的DLLを補完するビルド専用フック（Windows/conda）。

NumPyのINSTALLERがpipでも、実体がMKLを使う環境向け。
標準conda収集APIの結果をCPU実行用に限定する。MPI/TBB/GPUやLibrary全体は収集しない。
再配布条件の確認状況は docs/検証_exe_MKL収集_20261026.md を参照。
"""

import sys
from pathlib import Path

from PyInstaller import compat
from PyInstaller.utils.hooks import conda_support


_REQUIRED_DLLS = {
    "mkl": (
        "libimalloc.dll", "mkl_rt.2.dll", "mkl_core.2.dll", "mkl_intel_thread.2.dll",
        "mkl_sequential.2.dll", "mkl_def.2.dll", "mkl_mc3.2.dll", "mkl_avx2.2.dll",
        "mkl_avx512.2.dll", "mkl_vml_def.2.dll", "mkl_vml_mc3.2.dll",
        "mkl_vml_avx2.2.dll", "mkl_vml_avx512.2.dll", "mkl_vml_cmpt.2.dll",
    ),
    "intel-openmp": ("libiomp5md.dll",),
}
_NOTICE_DIRS = {
    "mkl": "share/doc/mkl/licensing",
    "intel-openmp": "share/doc/compiler/licensing/openmp",
}


def _collect_runtime():
    if not compat.is_win or not compat.is_pure_conda:
        raise RuntimeError("MKL収集にはWindowsのconda Python環境が必要です")
    prefix = Path(sys.prefix).resolve()
    lib_dir = (prefix / "Library/bin").resolve()
    selected = {}
    notices = []
    for package, required in _REQUIRED_DLLS.items():
        # sys.prefix/conda-metaに属するファイルを標準APIで列挙する。
        # dependencies=TrueではTBB/MPI等も広く入るため、指定した2パッケージだけに限定。
        candidates = conda_support.collect_dynamic_libs(package, dest=".", dependencies=False)
        found = set()
        for source, _ in candidates:
            path = Path(source).resolve()
            name = path.name.lower()
            if name not in required:
                continue
            if path.parent != lib_dir:
                raise RuntimeError(f"現在のPython環境以外のDLLは収集できません: {path}")
            if not path.is_file():
                raise RuntimeError(f"必須MKL/OpenMP DLLがありません: {path}")
            previous = selected.get(name)
            if previous is not None and previous != path:
                raise RuntimeError(f"同名DLLの収集元が競合しています: {previous} / {path}")
            selected[name] = path
            found.add(name)
        missing = set(required) - found
        if missing:
            raise RuntimeError(f"必須MKL/OpenMP DLLがありません ({package}, {prefix}): {', '.join(sorted(missing))}")

        # DLLと同じインストールのメタデータが指すライセンス原文を無改変で同梱する。
        dist = conda_support.distribution(package)
        cache = dist.raw.get("link", {}).get("source")
        if not cache:
            raise RuntimeError(f"ライセンス取得元のcondaメタデータがありません: {package}")
        license_dir = Path(cache) / "info/licenses"
        texts = sorted(p for p in license_dir.rglob("*.txt") if p.is_file())
        if not {"license.txt", "tpp.txt"}.issubset({p.name.lower() for p in texts}):
            raise RuntimeError(f"ライセンス本文・第三者通知がありません: {license_dir}")
        for path in texts:
            dest = Path("licenses") / package / "package" / path.relative_to(license_dir).parent
            notices.append((str(path), str(dest)))
        notice_dir = prefix / _NOTICE_DIRS[package]
        texts = sorted(p for p in notice_dir.glob("*.txt") if p.is_file())
        if not texts:
            raise RuntimeError(f"ライセンス第三者通知がありません: {notice_dir}")
        notices.extend((str(p), str(Path("licenses") / package / "notices")) for p in texts)

    # 同名OpenMP DLLを複数同梱しない。PyInstaller 6 onedirでは'.'は_internal直下になる。
    return [(str(path), ".") for path in selected.values()], notices


binaries, datas = _collect_runtime()
