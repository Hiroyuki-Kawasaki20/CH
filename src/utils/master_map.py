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


def resolve_with_ukeire_fallback(
    master_map,
    vendor,
    lookup_vendor,
    order2,
    logger=None,
    label="",
):
    """分割受入拠点（KVC/元町/織機）のマスタ照合を単一実装に集約する。

    ① 合成キー (f"{納入先}-{UKEIRE}", 便番号) を優先して引く
    ② 未ヒット時のみ素名 (納入先, 便番号) へ1回だけフォールバックする
       （gui.py / exporter.py の「安全網」と同一挙動）

    受入ごとの分割は「同一便番号でも入車時刻が異なる」実態に対応した正式仕様であり
    （例: 便08 は 織機-21/28 が 10:30、織機-61 は 20:35 で約10時間差）、
    素名フォールバックはこの差を潰す応急処置にすぎない。したがって発動時は必ず
    WARNING を出し、マスタへの分割行登録を促す。

    戻り値: (値, 実際にヒットしたキーの納入先名)。未ヒットは (None, None)。
    """
    primary = (lookup_vendor, order2)
    if primary in master_map:
        return master_map[primary], lookup_vendor
    if lookup_vendor != vendor:
        fallback = (vendor, order2)
        if fallback in master_map:
            if logger is not None:
                logger.warning(
                    "%s: 分割受入キー%sがマスタ未登録のため素名%sで暫定照合しました。"
                    "受入ごとの便ずれ（同一便番号で最大約10時間差）が反映されないため、"
                    "入車時間マスタへ分割行の登録が必要です",
                    label,
                    primary,
                    fallback,
                )
            return master_map[fallback], vendor
    return None, None
