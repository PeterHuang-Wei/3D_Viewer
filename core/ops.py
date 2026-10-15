"""特徵操作表:kind -> 執行函式。參數皆為可存成 JSON 的簡單值。"""
import cadquery as cq

from . import features as F
from . import thread as T
from . import sketch2d as SK
from . import paths as PA
from .io_step import step_text_to_shapes

LABELS = {
    "box": "方塊", "cylinder": "圓柱", "sphere": "球", "cone": "圓錐", "torus": "環",
    "extrude": "快速拉伸", "revolve": "快速旋轉", "rod": "外螺紋螺桿",
    "thread_tool": "內螺紋工具體", "step": "匯入 STEP",
    "translate": "平移", "sketch": "草圖", "sketch_extrude": "草圖拉伸", "sketch_revolve": "草圖旋轉", "sketch_sweep": "草圖掃掠", "sketch_loft": "草圖放樣", "helix": "螺旋線路徑", "annotation": "半徑/直徑標註", "pattern": "3D 陣列", "appearance": "外觀", "material": "材料", "draft": "拔模", "surface_extrude": "曲面拉伸", "surface_offset": "偏移面", "surface_trim": "曲面修剪", "surface_knit": "縫合曲面", "thicken": "曲面加厚", "insert": "插入零件", "mate": "配合", "rib": "加肋", "mirror": "鏡射實體", "hole": "孔", "shell": "抽殼", "refplane": "參考面", "scale": "縮放", "rotate": "旋轉", "fillet": "圓角", "chamfer": "倒角",
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


SURFACE_KINDS = {"surface_extrude", "surface_offset", "surface_trim", "surface_knit", "thicken"}


# kind -> fn(params) -> [Shape]  (建立新實體)
def _insert(p):
    from .assembly import project_shapes
    return [s for _, s in project_shapes(p["project"], p.get("x", 0), p.get("y", 0), p.get("z", 0))]


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
    "insert": _insert,
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


def _pattern(p, s):
    if p["kind"] == "線性":
        return F.pattern_linear(s, p["n"], p["dx"], p["dy"], p["dz"])
    ax = p["axis"]
    if ax.startswith("鎖定") and p.get("wp"):
        return F.pattern_circular(s, p["n"], p["angle"], p["wp"]["origin"], p["wp"]["normal"])
    if ax.startswith("鎖定"):
        raise ValueError("旋轉軸選了鎖定平面法向,但沒有工作平面")
    d = {"X": (1, 0, 0), "Y": (0, 1, 0)}.get(ax[0], (0, 0, 1))
    return F.pattern_circular(s, p["n"], p["angle"], (p["cx"], p["cy"], p["cz"]), d)


def _draft(p, s):
    if p.get("plane") == "鎖定平面":
        if not p.get("wp"):
            raise ValueError("中性面選了鎖定平面,但沒有工作平面")
        neutral = p["wp"]
    else:
        base = F.WORLD_PLANES[p["plane"]]
        n = base["normal"]
        neutral = {"origin": [c * p.get("offset", 0.0) for c in n], "normal": n}
    return F.draft_faces(s, set(p["faces"]), p["angle"], neutral, p.get("flip", False))


def _holes(p, s):
    if not p.get("wp"):
        raise ValueError("孔需要在鎖定的工作平面上建立")
    pts = F.parse_points(p["pts"])
    return F.make_holes(s, p["wp"], pts, p["type"], p["d"], p["depth"], p.get("flip", False),
                        cb_d=p.get("cb_d", 0), cb_depth=p.get("cb_depth", 0),
                        csk_d=p.get("csk_d", 0), csk_angle=p.get("csk_angle", 90))


# kind -> fn(params, shape) -> shape  (修改既有實體,params["body"] 為實體編號)
MODIFIERS = {
    "translate": lambda p, s: F.translate(s, p["x"], p["y"], p["z"]),
    "scale": lambda p, s: (F.scale(s, p["sx"], p["sx"], p["sx"], p["c"]) if p["uniform"]
                           else F.scale(s, p["sx"], p["sy"], p["sz"], p["c"])),
    "rotate": lambda p, s: F.rotate(s, p["x"], p["y"], p["z"], p["c"]),
    "fillet": lambda p, s: F.fillet(s, set(p["edges"]), p["r"]),
    "chamfer": lambda p, s: F.chamfer(s, set(p["edges"]), p["d"], p.get("d2") or None),
    "thread_hole": _hole,
    "pattern": _pattern,
    "draft": _draft,
    "hole": _holes,
    "shell": lambda p, s: F.shell_shape(s, set(p["faces"]), p["thickness"], p["dir"] == "向內"),
}


def sketch_solid(kind: str, p: dict, sk: dict) -> cq.Shape:
    """由草圖({"entities","wp"})依參數產生實體(全域座標)。"""
    ents, wp = sk["entities"], sk["wp"]
    if kind == "sketch_extrude":
        depth = -p["depth"] if p.get("flip") else p["depth"]
        return SK.extrude_solid(ents, wp, depth, p.get("sym", False))
    return SK.revolve_solid(ents, wp, p["angle"], "X" if "X" in p.get("axis", "Y") else "Y")


def sweep_solid(p: dict, profile: dict, path: dict) -> cq.Shape:
    """輪廓草圖沿路徑(草圖線/圓弧,或螺旋線)掃掠。
    align=True 時把輪廓座標系移到路徑起點:一般路徑讓輪廓法向沿路徑切線;螺旋線則讓輪廓平面通過螺旋軸(X=徑向,Y=軸向)。"""
    is_helix = "helix" in path
    wire = PA.helix_wire(path["helix"], path["wp"]) if is_helix else SK.path_wire(path["entities"], path["wp"])
    if p.get("align", False):
        if is_helix:
            place = PA.helix_frame(wire, path["wp"]).rG
        else:
            start, tangent = wire.startPoint(), wire.Edges()[0].tangentAt(0)
            px = F.plane_from_dict(profile["wp"]).xDir
            px = px - tangent * px.dot(tangent)                 # 取輪廓 X 軸在垂直面上的投影
            if px.Length < 1e-9:
                px = cq.Plane(origin=(0, 0, 0), normal=tangent.toTuple()).xDir
            place = cq.Plane(origin=start.toTuple(), xDir=px.toTuple(), normal=tangent.toTuple()).rG
    else:
        place = F.plane_from_dict(profile["wp"]).rG
    solids = []
    for f in SK.local_faces(profile["entities"]):
        g = f.transformShape(place)
        try:
            solids.append(cq.Solid.sweep(g.outerWire(), g.innerWires(), wire, True,
                                         p.get("frenet", True), None, p.get("transition", "transformed")))
        except Exception as e:  # noqa: BLE001
            raise ValueError("掃掠失敗:輪廓需位於路徑起點並垂直於路徑(或勾選自動對齊)") from e
    res = SK._fuse(solids)
    if not res.isValid() or res.Volume() < 1e-9:
        raise ValueError("掃掠結果無效:請確認輪廓位於路徑起點、垂直於路徑起始方向")
    return res


def loft_solid(p: dict, profiles: list) -> cq.Shape:
    """依序通過多個輪廓草圖(各取面積最大的外輪廓)的放樣。p["ruled"]=True 為直紋(各段直線連接)。"""
    if len(profiles) < 2:
        raise ValueError("放樣至少需要兩個輪廓草圖")
    wires = []
    for sk in profiles:
        faces = SK.local_faces(sk["entities"])
        f = max(faces, key=lambda x: x.Area()).transformShape(F.plane_from_dict(sk["wp"]).rG)
        wires.append(f.outerWire())
    try:
        res = cq.Solid.makeLoft(wires, bool(p.get("ruled", False)))
    except Exception as e:  # noqa: BLE001
        raise ValueError("放樣失敗:請確認各輪廓都是封閉輪廓,且彼此位置不同") from e
    if not res.isValid() or res.Volume() < 1e-9:
        raise ValueError("放樣結果無效:請檢查輪廓的位置與順序")
    return res
