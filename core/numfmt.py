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


# --- 顯示單位(內部一律 mm,僅影響量測/屬性文字的顯示)---
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
UNIT = "mm"


def set_unit(u: str) -> None:
    global UNIT
    if u not in UNITS:
        raise ValueError(f"不支援的單位:{u}")
    UNIT = u


def fmtl(v: float) -> str:
    """長度(mm)轉成目前顯示單位後格式化,不含單位字尾。"""
    return fmtn(v / UNITS[UNIT])


def fmta(v: float) -> str:
    """面積(mm²)轉成目前單位²。"""
    return fmtn(v / UNITS[UNIT] ** 2)


def fmtv(v: float) -> str:
    """體積(mm³)轉成目前單位³。"""
    return fmtn(v / UNITS[UNIT] ** 3)
