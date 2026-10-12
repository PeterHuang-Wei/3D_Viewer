"""量測/尺寸數值的顯示格式:最多顯示 PRECISION 位小數(預設 3,即 .3f),並去掉多餘的 0。
整數維持整數(50),0.1 顯示 0.1,0.25 顯示 0.25,0.1234 顯示 0.123。"""

PRECISION = 3


def set_precision(n: int) -> None:
    global PRECISION
    PRECISION = max(0, min(8, int(n)))


def fmtn(v: float) -> str:
    p = PRECISION
    if abs(v) < 0.5 * 10 ** (-p):
        return "0"                               # 避免 -0
    s = f"{v:.{p}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s
