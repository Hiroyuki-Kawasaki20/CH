"""docs の定数早見表(付録A)が実装コードと乖離したら落ちるテスト。

対象: docs/仕分け・割り振りルール.md の「付録A 定数早見表」。
値の正本はコード側(主に src/models/constants.py)。表の値とコードの実値が
一致しない場合、このテストが落ちる。定数を変更したらこの表も必ず更新すること。
"""
import re
from pathlib import Path

from src.models import constants as _constants_module
from src.services import process_assigner as _process_assigner_module

DOC = Path(__file__).resolve().parents[2] / "docs" / "仕分け・割り振りルール.md"

# 値の探索先(優先順)。ARRIVAL_BUFFER_SECS は constants.py ではなく
# process_assigner.py が定義元のため、フォールバック先として追加している。
_SOURCES = (_constants_module, _process_assigner_module)

# 早見表の行: | `定数名` | 値 | 説明 |
ROW = re.compile(r"^\|\s*`([A-Z0-9_]+)`\s*\|\s*([0-9]+)\s*\|")


def _resolve(name: str):
    for module in _SOURCES:
        if hasattr(module, name):
            return getattr(module, name)
    return None


def test_doc_constant_table_matches_code():
    rows = [
        m.groups()
        for m in map(ROW.match, DOC.read_text(encoding="utf-8").splitlines())
        if m
    ]
    assert rows, "付録A 定数早見表が見つかりません(docs/仕分け・割り振りルール.md)"

    for name, doc_val in rows:
        actual = _resolve(name)
        assert actual is not None, (
            f"{name} が src/models/constants.py にも "
            f"src/services/process_assigner.py にも存在しません"
        )
        assert int(doc_val) == int(actual), (
            f"{name}: ドキュメント={doc_val} / コード={actual} が不一致です。"
            f"docs/仕分け・割り振りルール.md の付録Aを実値に合わせて修正してください。"
        )