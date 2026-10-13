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
def _profile(plane, offset: float, kind: str, p: dict) -> cq.Workplane:
    if isinstance(plane, cq.Plane):             # 鎖定的工作平面
        wp = cq.Workplane(plane)
    else:
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


# --- 倒角 / 圓角(以 shape.Edges() 的索引指定邊) ---
def _single_solid(shape: cq.Shape) -> cq.Solid:
    solids = shape.Solids()
    if len(solids) != 1:
        raise ValueError("倒角/圓角僅支援單一實體")
    return solids[0]


def face_edge_ids(shape: cq.Shape, face_ids) -> set[int]:
    """面索引(shape.Faces())所包含的邊索引(shape.Edges())。"""
    faces, edges = shape.Faces(), shape.Edges()
    out = set()
    for fi in face_ids:
        fedges = faces[fi].Edges()
        out.update(j for j, e in enumerate(edges) if any(e.isSame(fe) for fe in fedges))
    return out


def _pick_edges(shape, edge_ids):
    if not edge_ids:
        raise ValueError("請先選取要處理的邊或面")
    edges = shape.Edges()
    return [edges[i] for i in sorted(edge_ids)]


def fillet(shape: cq.Shape, edge_ids, radius: float) -> cq.Shape:
    try:
        return _single_solid(shape).fillet(radius, _pick_edges(shape, edge_ids)).clean()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("圓角失敗,半徑可能過大或邊不適用") from e


def chamfer(shape: cq.Shape, edge_ids, length: float, length2: float | None = None) -> cq.Shape:
    try:
        return _single_solid(shape).chamfer(length, length2, _pick_edges(shape, edge_ids)).clean()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("倒角失敗,距離可能過大或邊不適用") from e


# --- 縮放 ---
def scale(shape: cq.Shape, sx, sy, sz, about_center=True) -> cq.Shape:
    """各軸縮放。三軸相同時保持解析曲面;不等比縮放會把曲面轉成 B-spline。"""
    if min(sx, sy, sz) <= 0:
        raise ValueError("縮放倍率必須大於 0")
    c = shape.Center() if about_center else cq.Vector(0, 0, 0)
    moved = shape.moved(cq.Location(-c))
    if sx == sy == sz:
        res = moved.scale(sx)
    else:
        res = moved.transformGeometry(cq.Matrix([[sx, 0, 0, 0], [0, sy, 0, 0], [0, 0, sz, 0]]))
    return res.moved(cq.Location(cq.Vector(c.x, c.y, c.z)))


# --- 工作平面(鎖定平面):wp = {"origin": [...], "xdir": [...], "normal": [...]} ---
def plane_from_dict(wp: dict) -> cq.Plane:
    return cq.Plane(origin=tuple(wp["origin"]), xDir=tuple(wp["xdir"]), normal=tuple(wp["normal"]))


def plane_from_face(face: cq.Face) -> dict:
    """由平面的面取得工作平面(法向朝實體外側);非平面則丟出錯誤。"""
    if face.geomType() != "PLANE":
        raise ValueError("只能鎖定平面(所選的面不是平面)")
    o, n = face.Center(), face.normalAt()
    pl = cq.Plane(origin=(o.x, o.y, o.z), normal=(n.x, n.y, n.z))
    r = lambda v: [round(v.x, 6) + 0.0, round(v.y, 6) + 0.0, round(v.z, 6) + 0.0]  # noqa: E731
    return {"origin": r(pl.origin), "xdir": r(pl.xDir), "normal": r(pl.zDir)}


WORLD_PLANES = {
    "XY": {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, 0, 1]},
    "XZ": {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, -1, 0]},
    "YZ": {"origin": [0, 0, 0], "xdir": [0, 1, 0], "normal": [1, 0, 0]},
}


def to_plane(shape: cq.Shape, wp: dict, flip: bool = False, ground: bool = False) -> cq.Shape:
    """把以原點、+Z 向上建立的形狀放到工作平面上。
    ground=True 時先讓形狀底面貼齊平面;flip=True 時朝法向反方向(例如往實體內)。"""
    if ground:
        shape = shape.moved(cq.Location(cq.Vector(0, 0, -shape.BoundingBox().zmin)))
    if flip:
        shape = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180)
    return shape.transformShape(plane_from_dict(wp).rG)


def _rot(v, axis, deg):
    """羅德里格旋轉公式:向量 v 繞單位軸 axis 轉 deg 度。"""
    import numpy as np
    t = np.radians(deg)
    return v * np.cos(t) + np.cross(axis, v) * np.sin(t) + axis * np.dot(axis, v) * (1 - np.cos(t))


def offset_plane(wp: dict, offset: float, rx: float = 0.0, ry: float = 0.0) -> dict:
    """由基準平面產生參考面:沿法向平移 offset,再依序繞平面 X 軸、Y 軸傾斜 rx、ry 度。"""
    import numpy as np
    x = np.asarray(wp["xdir"], float)
    n = np.asarray(wp["normal"], float)
    x, n = x / np.linalg.norm(x), n / np.linalg.norm(n)
    y = np.cross(n, x)
    o = np.asarray(wp["origin"], float) + n * offset
    y, n = _rot(y, x, rx), _rot(n, x, rx)       # 繞 X 軸傾斜
    x, n = _rot(x, y, ry), _rot(n, y, ry)       # 再繞(新的)Y 軸傾斜
    r = lambda v: [round(float(c), 6) + 0.0 for c in v]  # noqa: E731
    return {"origin": r(o), "xdir": r(x), "normal": r(n)}


# --- 3D 陣列 / 鏡射 / 孔 / 抽殼 ---
def _fuse_all(shapes):
    res = shapes[0]
    if len(shapes) > 1:
        res = res.fuse(*shapes[1:]).clean()
    return res


def pattern_linear(shape: cq.Shape, n: int, dx, dy, dz) -> cq.Shape:
    """線性陣列:n 為總數量(含原件),各份以 (dx,dy,dz) 為間距,聯集成同一實體。"""
    if int(n) < 2:
        raise ValueError("陣列總數量至少 2")
    return _fuse_all([shape] + [translate(shape, k * dx, k * dy, k * dz) for k in range(1, int(n))])


def pattern_circular(shape: cq.Shape, n: int, total_angle: float, origin, direction) -> cq.Shape:
    """圓形陣列:繞通過 origin、方向 direction 的軸;總角度 360 時等分,否則首尾各一份。"""
    n = int(n)
    if n < 2:
        raise ValueError("陣列總數量至少 2")
    o = cq.Vector(*origin)
    d = cq.Vector(*direction)
    if d.Length < 1e-9:
        raise ValueError("旋轉軸方向不可為零向量")
    step = total_angle / n if abs(total_angle - 360.0) < 1e-9 else total_angle / (n - 1)
    return _fuse_all([shape] + [shape.rotate(o, o + d, k * step) for k in range(1, n)])


def mirror_shape(shape: cq.Shape, wp: dict) -> cq.Shape:
    """對工作平面(origin/normal)鏡射。"""
    return shape.mirror(cq.Vector(*wp["normal"]), cq.Vector(*wp["origin"]))


def hole_tool(kind: str, d: float, depth: float, cb_d=0.0, cb_depth=0.0, csk_d=0.0, csk_angle=90.0) -> cq.Shape:
    """孔的切削工具體:由 z=0 往 +Z 延伸(之後再用 to_plane 翻向實體內)。"""
    if d <= 0 or depth <= 0:
        raise ValueError("孔徑與孔深必須大於 0")
    parts = [cq.Solid.makeCylinder(d / 2, depth)]
    if kind == "沉頭孔":
        if cb_d <= d or cb_depth <= 0:
            raise ValueError("沉頭直徑必須大於孔徑,沉頭深度大於 0")
        parts.append(cq.Solid.makeCylinder(cb_d / 2, cb_depth))
    elif kind == "埋頭孔":
        if csk_d <= d or not 10 <= csk_angle < 180:
            raise ValueError("埋頭直徑必須大於孔徑,角度需在 10°~180°")
        h = (csk_d - d) / 2 / math.tan(math.radians(csk_angle / 2))
        parts.append(cq.Solid.makeCone(csk_d / 2, d / 2, h))
    return _fuse_all(parts)


def make_holes(body: cq.Shape, wp: dict, positions, kind, d, depth, flip=False, **kw) -> cq.Shape:
    """在工作平面上的多個位置(平面座標 u,v)鑽孔;depth=0 表通孔。預設朝實體內(平面法向反向)。"""
    if not positions:
        raise ValueError("請輸入至少一個孔位置,例如 0,0; 20,0")
    bb = body.BoundingBox()
    depth_eff = depth if depth > 0 else (bb.xlen + bb.ylen + bb.zlen) + 10
    tool0 = hole_tool(kind, d, depth_eff, **kw)
    tools = [to_plane(tool0.moved(cq.Location(cq.Vector(u, v, 0))), wp, flip=not flip) for u, v in positions]
    res = body.cut(*tools).clean() if len(tools) > 1 else body.cut(tools[0]).clean()
    if abs(res.Volume() - body.Volume()) < 1e-9:
        raise ValueError("孔沒有切到實體,請確認工作平面與孔位置")
    return res


def shell_shape(shape: cq.Shape, face_ids, thickness: float, inward: bool = True) -> cq.Shape:
    """抽殼:face_ids 為要開口的面(空 = 封閉空心);thickness 為壁厚。"""
    if thickness <= 0:
        raise ValueError("壁厚必須大於 0")
    solid = _single_solid(shape)
    faces = solid.Faces()
    try:
        res = solid.hollow([shape.Faces()[i] for i in sorted(face_ids)], -thickness if inward else thickness)
    except Exception as e:  # noqa: BLE001
        raise ValueError("抽殼失敗:壁厚可能過大或所選面不適用") from e
    if not res.isValid() or res.Volume() < 1e-9:
        raise ValueError("抽殼結果無效:請減小壁厚")
    return res


# --- 拔模斜度 / 加肋 ---
def draft_faces(shape: cq.Shape, face_ids, angle: float, neutral: dict, flip: bool = False) -> cq.Shape:
    """拔模:face_ids 為要傾斜的面;neutral 為中性面(origin/normal),其法向即拔模(脫模)方向。
    angle > 0 時,面沿拔模方向遠離中性面時向內收(實體變細);flip 反向。"""
    import math as _m
    from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    if not face_ids:
        raise ValueError("請先選取要拔模的面")
    if not 0 < abs(angle) < 89:
        raise ValueError("拔模角度需介於 0° 與 89° 之間")
    faces = shape.Faces()
    n = cq.Vector(*neutral["normal"]).normalized()
    pull = gp_Dir(n.x, n.y, n.z)
    plane = gp_Pln(gp_Pnt(*neutral["origin"]), pull)
    d = BRepOffsetAPI_DraftAngle(shape.wrapped)
    try:
        for i in sorted(face_ids):
            d.Add(faces[i].wrapped, pull, _m.radians(-angle if flip else angle), plane)
        d.Build()
    except Exception as e:  # noqa: BLE001
        raise ValueError("拔模失敗:所選面無法依此方向與角度傾斜(例如面與拔模方向垂直)") from e
    if not d.IsDone():
        raise ValueError("拔模失敗:請調整角度、中性面或所選面")
    res = cq.Shape.cast(d.Shape())
    if not res.isValid() or res.Volume() < 1e-9:
        raise ValueError("拔模結果無效")
    return res


def rib_solid(body: cq.Shape, wire: cq.Wire, normal, thickness: float, symmetric: bool = True,
              flip: bool = False) -> cq.Shape:
    """加肋:草圖開放輪廓(在平面內)為肋的外緣,朝實體方向延伸直到碰到實體,厚度沿草圖平面法向。
    延伸方向自動選取「較快碰到實體」的一側(體積較小者);flip 改選另一側。"""
    import numpy as np
    from .measure import min_distance
    if thickness <= 0:
        raise ValueError("肋厚必須大於 0")
    n = np.array(cq.Vector(*normal).normalized().toTuple())
    pts = []
    for e in wire.Edges():
        ps = [np.array(v.toTuple()) for v in e.positions(np.linspace(0, 1, 2 if e.geomType() == "LINE" else 24))]
        pts += ps if not pts else ps[1:]
    if len(pts) < 2:
        raise ValueError("肋的輪廓至少要有一段線")
    chord = pts[-1] - pts[0]
    if np.linalg.norm(chord) < 1e-9:
        raise ValueError("肋的輪廓起點與終點不可重合")
    d0 = np.cross(n, chord)
    d0 = d0 / np.linalg.norm(d0)
    bb = body.BoundingBox()
    diag = float(np.linalg.norm([bb.xlen, bb.ylen, bb.zlen]))
    L = diag * 1.5 + 1
    box = cq.Solid.makeBox(bb.xlen, bb.ylen, bb.zlen, pnt=cq.Vector(bb.xmin, bb.ymin, bb.zmin))
    air = box.cut(body)

    def candidate(d):
        poly = [cq.Vector(*p) for p in pts] + [cq.Vector(*(pts[-1] + d * L)), cq.Vector(*(pts[0] + d * L))]
        face = cq.Face.makeFromWires(cq.Wire.makePolygon(poly + [poly[0]]))
        if symmetric:
            face = face.moved(cq.Location(cq.Vector(*(-n * thickness / 2))))
        slab = cq.Solid.extrudeLinear(face, cq.Vector(*(n * thickness)))
        common = slab.intersect(air)
        keep = [s for s in common.Solids() if min_distance(s, wire)[0] < 1e-4]
        return keep

    cands = [candidate(d0), candidate(-d0)]
    vols = [sum(s.Volume() for s in c) if c else float("inf") for c in cands]
    order = sorted(range(2), key=lambda i: vols[i])
    pick = order[1 if flip else 0]
    if not cands[pick]:
        pick = order[0]
    if not cands[pick]:
        raise ValueError("肋沒有碰到實體:請把輪廓畫在實體附近,朝實體方向")
    rib = _fuse_all(cands[pick])
    res = body.fuse(rib).clean()
    if not res.isValid():
        raise ValueError("加肋結果無效")
    return res
