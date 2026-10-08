"""特徵操作表:kind -> 執行函式。參數皆為可存成 JSON 的簡單值。"""
import cadquery as cq

from . import features as F
from . import thread as T
from .io_step import step_text_to_shapes

LABELS = {
    "box": "方塊", "cylinder": "圓柱", "sphere": "球", "cone": "圓錐", "torus": "環",
    "extrude": "草圖拉伸", "revolve": "草圖旋轉", "rod": "外螺紋螺桿",
    "thread_tool": "內螺紋工具體", "step": "匯入 STEP",
    "translate": "平移", "scale": "縮放", "rotate": "旋轉", "fillet": "圓角", "chamfer": "倒角",
    "thread_hole": "螺紋孔", "boolean": "布林運算", "delete": "刪除",
}


def _sketch(p):
    kind = p["kind"]
    if p.get("wp"):                      # 鎖定平面時直接用該平面
        plane, offset = F.plane_from_dict(p["wp"]), 0
    else:
        plane, offset = F.PLANES[p["plane"]], p["offset"]
    pts = F.parse_points(p.get("pts", "")) if kind == "自訂多邊形" else []
    params = dict(w=p["w"], h=p["h"], r=p["r"], n=p["n"], cx=p["cx"], cy=p["cy"], pts=pts)
    return plane, offset, kind, params


def _thread_dp(p):
    return (p["d"], p["p"]) if p["spec"] == T.CUSTOM else T.parse_spec(p["spec"])


def _rod(p):
    d, pitch = _thread_dp(p)
    return [T.make_threaded_rod(d, pitch, p["len"], p["left"])]


def _extrude(p):
    plane, off, kind, params = _sketch(p)
    depth = -p["depth"] if p.get("flip") else p["depth"]
    return [F.sketch_extrude(plane, off, kind, params, depth, p["sym"])]


def _revolve(p):
    plane, off, kind, params = _sketch(p)
    return [F.sketch_revolve(plane, off, kind, params, p["angle"])]


# kind -> fn(params) -> [Shape]  (建立新實體)
CREATORS = {
    "box": lambda p: [F.make_box(p["x"], p["y"], p["z"])],
    "cylinder": lambda p: [F.make_cylinder(p["r"], p["h"])],
    "sphere": lambda p: [F.make_sphere(p["r"])],
    "cone": lambda p: [F.make_cone(p["r1"], p["r2"], p["h"])],
    "torus": lambda p: [F.make_torus(p["R"], p["r"])],
    "extrude": _extrude,
    "revolve": _revolve,
    "rod": _rod,
    "thread_tool": _rod,
    "step": lambda p: step_text_to_shapes(p["data"]),
}

# 鎖定平面時可放置的建立類特徵 -> 是否讓底面貼齊平面
PLACEABLE = {"box": True, "cylinder": True, "sphere": True, "cone": True, "torus": True,
             "rod": False, "thread_tool": False}


def _hole(p, s):
    d, pitch = _thread_dp(p)
    if p.get("wp"):                      # 預設由平面往實體內(法向反方向)切入
        tool = F.to_plane(T.make_threaded_rod(d, pitch, p["depth"], p["left"]), p["wp"],
                          flip=not p.get("flip", False))
        return T.cut_tool(s, tool)
    return T.threaded_hole(s, d, pitch, p["depth"], (p["x"], p["y"], p["z"]), p["axis"], p["left"])


# kind -> fn(params, shape) -> shape  (修改既有實體,params["body"] 為實體編號)
MODIFIERS = {
    "translate": lambda p, s: F.translate(s, p["x"], p["y"], p["z"]),
    "scale": lambda p, s: (F.scale(s, p["sx"], p["sx"], p["sx"], p["c"]) if p["uniform"]
                           else F.scale(s, p["sx"], p["sy"], p["sz"], p["c"])),
    "rotate": lambda p, s: F.rotate(s, p["x"], p["y"], p["z"], p["c"]),
    "fillet": lambda p, s: F.fillet(s, set(p["edges"]), p["r"]),
    "chamfer": lambda p, s: F.chamfer(s, set(p["edges"]), p["d"], p.get("d2") or None),
    "thread_hole": _hole,
}
