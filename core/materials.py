"""材料庫與質量屬性(質量、質心、慣性矩)。長度單位 mm、密度 g/cm³、質量 g、慣性矩 g·mm²。"""
import numpy as np
import cadquery as cq
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

CUSTOM = "自訂密度"
DEFAULT_MATERIAL = "碳鋼"
# 名稱 -> 密度 g/cm³
MATERIALS = {
    "碳鋼": 7.85, "不鏽鋼 304": 7.93, "鑄鐵": 7.20, "鋁 6061": 2.70, "鋁 7075": 2.81, "銅": 8.96,
    "黃銅": 8.50, "青銅": 8.80, "鈦合金 Ti-6Al-4V": 4.43, "鎂合金": 1.80, "鋅合金": 6.60, "鉛": 11.34,
    "ABS": 1.05, "PLA": 1.24, "PETG": 1.27, "尼龍 PA6": 1.14, "聚碳酸酯 PC": 1.20, "POM(delrin)": 1.41,
    "壓克力 PMMA": 1.18, "橡膠": 1.10, "木材(橡木)": 0.75, "玻璃": 2.50, "混凝土": 2.40, "水": 1.00,
}


def density_of(name: str, custom: float = 1.0) -> float:
    if name == CUSTOM:
        if custom <= 0:
            raise ValueError("密度必須大於 0")
        return float(custom)
    if name not in MATERIALS:
        raise ValueError(f"未知材料:{name}")
    return MATERIALS[name]


def mass_props(shape: cq.Shape, density: float) -> dict:
    """單一實體的質量屬性(慣性矩為對質心、軸向平行全域座標)。"""
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, p)
    vol = p.Mass()
    c = p.CentreOfMass()
    m = p.MatrixOfInertia()
    inertia = np.array([[m.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)]) * density / 1000.0   # g·mm²
    return {"volume": vol, "area": shape.Area(), "density": density, "mass": vol * density / 1000.0,
            "com": np.array([c.X(), c.Y(), c.Z()]), "inertia": inertia}


def principal_moments(inertia: np.ndarray):
    return tuple(float(v) for v in np.linalg.eigvalsh(inertia))


def assembly_props(items) -> dict:
    """items: [(名稱, 形狀, 密度)]。回傳 {"parts": [...], "mass","volume","com","inertia"}(慣性矩對整體質心)。"""
    parts = [{"name": n, **mass_props(s, d)} for n, s, d in items]
    if not parts:
        raise ValueError("沒有實體")
    mass = sum(p["mass"] for p in parts)
    vol = sum(p["volume"] for p in parts)
    com = sum(p["mass"] * p["com"] for p in parts) / mass
    inertia = np.zeros((3, 3))
    for p in parts:
        d = p["com"] - com
        inertia += p["inertia"] + p["mass"] * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return {"parts": parts, "mass": mass, "volume": vol, "com": com, "inertia": inertia}
