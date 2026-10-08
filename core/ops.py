"""特徵操作表:kind -> 執行函式。參數皆為可存成 JSON 的簡單值。"""
import cadquery as cq

from . import features as F
from . import thread as T
from .io_step import step_text_to_shapes

LABELS = {
    "box": "方塊", "cylinder": "圓柱", "sphere": "球", "cone": "圓錐", "torus": "環",
    "extrude": "草圖拉伸", "revolve": "草圖旋轉", "rod": "外螺紋螺桿",
    "thread_tool": "內螺紋工具體", "step": "匯入 STEP",
    "translate": "平移", "rotate": "旋轉", "fillet": "圓角", "chamfer": "倒角",
    "thread_hole": "螺紋孔", "boolean": "布林運算", "delete": "刪除",
}


def _sketch(p):
    kind = p["kind"]
    pts = F.parse_points(p.get("pts", "")) if kind == "自訂多邊形" else []
    params = dict(w=p["w"], h=p["h"], r=p["r"], n=p["n"], cx=p["cx"], cy=p["cy"], pts=pts)
    return F.PLANES[p["plane"]], p["offset"], kind, params


def _thread_dp(p):
    return (p["d"], p["p"]) if p["spec"] == T.CUSTOM else T.parse_spec(p["spec"])


def _rod(p):
    d, pitch = _thread_dp(p)
    return [T.make_threaded_rod(d, pitch, p["len"], p["left"])]


def _extrude(p):
    plane, off, kind, params = _sketch(p)
    return [F.sketch_extrude(plane, off, kind, params, p["depth"], p["sym"])]


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

# kind -> fn(params, shape) -> shape  (修改既有實體,params["body"] 為實體編號)
MODIFIERS = {
    "translate": lambda p, s: F.translate(s, p["x"], p["y"], p["z"]),
    "rotate": lambda p, s: F.rotate(s, p["x"], p["y"], p["z"], p["c"]),
    "fillet": lambda p, s: F.fillet(s, set(p["edges"]), p["r"]),
    "chamfer": lambda p, s: F.chamfer(s, set(p["edges"]), p["d"], p.get("d2") or None),
    "thread_hole": lambda p, s: T.threaded_hole(
        s, *_thread_dp(p), p["depth"], (p["x"], p["y"], p["z"]), p["axis"], p["left"]),
}
