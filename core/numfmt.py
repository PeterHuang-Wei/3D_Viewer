"""量測/尺寸數值的顯示格式:固定小數位數(預設 3 位,即 .3f),可由設定調整。"""

PRECISION = 3


def set_precision(n: int) -> None:
    global PRECISION
    PRECISION = max(0, min(8, int(n)))


def fixed(v: float) -> str:
    """固定小數位數(預設 .3f);避免顯示 -0.000。"""
    p = PRECISION
    if abs(v) < 0.5 * 10 ** (-p):
        v = 0.0
    return f"{v:.{p}f}"
