"""マスタ由来の辞書構築ユーティリティ。"""

from typing import Any, Callable, Iterable, Mapping


def build_master_map_with_duplicate_warning(
    rows: Iterable[Mapping[str, Any]],
    key_cols: tuple[str, ...],
    value_col: str,
    logger,
    value_formatter: Callable[[Any], Any] | None = None,
) -> dict[tuple[Any, ...], Any]:
    """マスタ辞書を構築し、重複キーは警告して後行の値を採用する。"""
    result: dict[tuple[Any, ...], Any] = {}
    format_value = value_formatter or (lambda value: value)
    for row in rows:
        key = tuple(row[col] for col in key_cols)
        value = format_value(row.get(value_col, ""))
        if key in result:
            logger.warning(
                "マスタの重複キーを検出: key=%s, 既存値=%r, 新しい値=%r, 後行の値=%rを採用",
                key,
                result[key],
                value,
                value,
            )
        result[key] = value
    return result