from pathlib import Path


def test_python_files_end_with_lf():
    root = Path(__file__).resolve().parents[2]
    violations = []
    for directory in (root / "src", root / "tools"):
        for path in directory.rglob("*.py"):
            content = path.read_bytes()
            if content and not content.endswith(b"\n"):
                violations.append(str(path.relative_to(root)))
    assert not violations, f"末尾改行がないPythonファイル: {violations}"