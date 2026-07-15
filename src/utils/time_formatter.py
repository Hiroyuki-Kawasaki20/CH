"""
src.utils.time_formatter

秒 (int) → "HH:MM" 形式への変換
※ 24時間超は連続表記（"25:00", "48:00" など）
- Option B: 連続表記（翌日超過を一目瞭然）
"""


def seconds_to_hhMM(secs):
    """秒を HH:MM 形式に変換（翌日超過対応）
    
    Args:
        secs (int | None): 秒単位の時刻 (0 以上)
        
    Returns:
        str: "HH:MM" 形式
             異常値(None, 負数) は "N/A"
             
    Examples:
        >>> seconds_to_hhMM(0)
        '00:00'
        >>> seconds_to_hhMM(43200)
        '12:00'
        >>> seconds_to_hhMM(86399)
        '23:59'
        >>> seconds_to_hhMM(86400)
        '24:00'
        >>> seconds_to_hhMM(90000)
        '25:00'
        >>> seconds_to_hhMM(None)
        'N/A'
        >>> seconds_to_hhMM(-100)
        'N/A'
    """
    # 異常値チェック
    if secs is None or secs < 0:
        return "N/A"
    
    # 秒 → 分に変換（秒単位は切り捨て）
    total_minutes = secs // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    # Option B: 24時間超も連続表記
    return f"{hours:02d}:{minutes:02d}"
