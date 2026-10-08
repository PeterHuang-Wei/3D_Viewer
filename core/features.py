"""建模操作:基本實體、草圖拉伸/旋轉、變換、布林運算。"""
import math
import cadquery as cq

PLANES = {"XY 平面": "XY", "XZ 平面": "XZ", "YZ 平面": "YZ"}


# --- 基本實體(皆以原點為中心) ---
def make_box(x, y, z) -> cq.Shape:
    return cq.Workplane().box(x, y, z).val()


def make_cylinder(radius, height) -> cq.Shape:
    return cq.Workplane().circle(radius).extrude(height / 2, both=True).val()


def make_sphere(radius) -> cq.Shape:
    return cq.Workplane().sphere(radius).val()


def make_cone(r1, r2, height) -> cq.Shape:
    return cq.Solid.makeCone(r1, r2, height, pnt=cq.Vector(0, 0, -height / 2))


def make_torus(major, minor) -> cq.Shape:
    return cq.Solid.makeTorus(major, minor)


# --- 草圖 ---
def _profile(plane: str, offset: float, kind: str, p: dict) -> cq.Workplane:
    wp = cq.Workplane(plane, origin=_origin(plane, offset))
    cx, cy = p.get("cx", 0), p.get("cy", 0)  # 輪廓中心偏移(旋轉時需離開旋轉軸)
    if cx or cy:
        wp = wp.pushPoints([(cx, cy)])
    if kind == "矩形":
        return wp.rect(p["w"], p["h"])
    if kind == "圓":
        return wp.circle(p["r"])
    if kind == "正多邊形":
        return wp.polygon(int(p["n"]), 2 * p["r"])  # 直徑 = 外接圓直徑
    if kind == "自訂多邊形":
        pts = p["pts"]
        if len(pts) < 3:
            raise ValueError("多邊形至少需要 3 個點")
        return wp.polyline([(x + cx, y + cy) for x, y in pts]).close()
    raise ValueError(f"未知草圖類型: {kind}")


def _origin(plane, offset):
    return {"XY": (0, 0, offset), "XZ": (0, offset, 0), "YZ": (offset, 0, 0)}[plane]


def sketch_extrude(plane, offset, kind, params, depth, symmetric=False) -> cq.Shape:
    return _profile(plane, offset, kind, params).extrude(depth, both=symmetric).val()


def sketch_revolve(plane, offset, kind, params, angle=360.0) -> cq.Shape:
    """繞草圖平面的局部 Y 軸旋轉(輪廓需位於軸的一側)。"""
    return _profile(plane, offset, kind, params).revolve(angle, (0, 0, 0), (0, 1, 0)).val()


def parse_points(text: str) -> list[tuple[float, float]]:
    """'0,0; 10,0; 5,8' -> [(0,0),(10,0),(5,8)]"""
    pts = []
    for item in text.replace("\n", ";").split(";"):
        item = item.strip()
        if item:
            x, y = item.split(",")
            pts.append((float(x), float(y)))
    return pts


# --- 變換 ---
def translate(shape: cq.Shape, dx, dy, dz) -> cq.Shape:
    return shape.moved(cq.Location(cq.Vector(dx, dy, dz)))


def rotate(shape: cq.Shape, rx, ry, rz, about_center=True) -> cq.Shape:
    c = shape.Center() if about_center else cq.Vector(0, 0, 0)
    for axis, ang in (((1, 0, 0), rx), ((0, 1, 0), ry), ((0, 0, 1), rz)):
        if ang:
            shape = shape.rotate(c, c + cq.Vector(*axis), ang)
    return shape


# --- 布林運算 ---
def boolean(op: str, target: cq.Shape, tool: cq.Shape) -> cq.Shape:
    """op: 聯集 / 差集 / 交集。差集 = target - tool。"""
    if op == "聯集":
        res = target.fuse(tool)
    elif op == "差集":
        res = target.cut(tool)
    elif op == "交集":
        res = target.intersect(tool)
    else:
        raise ValueError(f"未知運算: {op}")
    res = res.clean()
    if not res.Solids():
        raise ValueError("運算結果為空(兩物件可能沒有重疊)")
    return res
