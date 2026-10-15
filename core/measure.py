"""量測:距離、邊/面資訊、角度、實體屬性(皆為純 OpenCascade 計算,與介面無關)。"""
import math

import cadquery as cq
from .numfmt import fmtn
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.GeomAbs import (GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line,
                         GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus)

FACE_TYPES = {"PLANE": "平面", "CYLINDER": "圓柱面", "CONE": "圓錐面", "SPHERE": "球面",
              "TORUS": "環面", "BSPLINE": "B 曲面", "BEZIER": "Bezier 曲面", "REVOLUTION": "旋轉面",
              "EXTRUSION": "拉伸面", "OFFSET": "偏移面", "OTHER": "其他曲面"}
EDGE_TYPES = {"LINE": "直線", "CIRCLE": "圓/圓弧", "ELLIPSE": "橢圓", "BSPLINE": "B 曲線",
              "BEZIER": "Bezier 曲線", "OTHER": "其他曲線"}


def _vec(p) -> cq.Vector:
    return cq.Vector(p.X(), p.Y(), p.Z())


def min_distance(a: cq.Shape, b: cq.Shape):
    """兩個形狀(點/邊/面/實體)之間的最短距離。回傳 (距離, a 上最近點, b 上最近點)。"""
    ds = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    if not ds.IsDone() or ds.NbSolution() < 1:
        raise ValueError("無法計算最短距離")
    return ds.Value(), _vec(ds.PointOnShape1(1)), _vec(ds.PointOnShape2(1))


def point_distance(p: cq.Vector, q: cq.Vector) -> dict:
    d = q - p
    return {"distance": d.Length, "dx": d.x, "dy": d.y, "dz": d.z}


def edge_info(edge: cq.Edge) -> dict:
    """邊的資訊:長度、種類;圓/圓弧另含半徑、直徑、圓心。"""
    curve = BRepAdaptor_Curve(edge.wrapped)
    info = {"length": edge.Length(), "type": edge.geomType(),
            "start": edge.startPoint(), "end": edge.endPoint()}
    if curve.GetType() == GeomAbs_Circle:
        circ = curve.Circle()
        info.update(radius=circ.Radius(), diameter=2 * circ.Radius(), center=_vec(circ.Location()),
                    closed=edge.IsClosed())
    return info


def face_info(face: cq.Face) -> dict:
    """面的資訊:面積、種類、中心;平面另含法向,圓柱/球/圓錐/環另含半徑。"""
    surf = BRepAdaptor_Surface(face.wrapped)
    t = surf.GetType()
    info = {"area": face.Area(), "type": face.geomType(), "center": face.Center()}
    if t == GeomAbs_Plane:
        info["normal"] = face.normalAt()
    elif t == GeomAbs_Cylinder:
        info.update(radius=surf.Cylinder().Radius(), diameter=2 * surf.Cylinder().Radius())
    elif t == GeomAbs_Sphere:
        info.update(radius=surf.Sphere().Radius(), diameter=2 * surf.Sphere().Radius())
    elif t == GeomAbs_Cone:
        info.update(half_angle=math.degrees(surf.Cone().SemiAngle()), radius=surf.Cone().RefRadius())
    elif t == GeomAbs_Torus:
        info.update(major_radius=surf.Torus().MajorRadius(), minor_radius=surf.Torus().MinorRadius())
    return info


def _angle(u: cq.Vector, v: cq.Vector) -> float:
    c = max(-1.0, min(1.0, u.normalized().dot(v.normalized())))
    return math.degrees(math.acos(c))


def _line_dir(edge: cq.Edge):
    if BRepAdaptor_Curve(edge.wrapped).GetType() != GeomAbs_Line:
        return None
    return (edge.endPoint() - edge.startPoint()).normalized()


def _plane_normal(face: cq.Face):
    if BRepAdaptor_Surface(face.wrapped).GetType() != GeomAbs_Plane:
        return None
    return face.normalAt()


def angle_between(a: cq.Shape, b: cq.Shape) -> dict:
    """平面-平面、直線-直線、直線-平面 的夾角(度)。"""
    fa, fb = isinstance(a, cq.Face), isinstance(b, cq.Face)
    if fa and fb:
        n1, n2 = _plane_normal(a), _plane_normal(b)
        if n1 is None or n2 is None:
            raise ValueError("角度量測的面必須是平面")
        normals = _angle(n1, n2)
        return {"kind": "面-面", "angle": 180.0 - normals, "normals": normals}   # angle=兩面之間的內夾角
    if not fa and not fb:
        d1, d2 = _line_dir(a), _line_dir(b)
        if d1 is None or d2 is None:
            raise ValueError("角度量測的邊必須是直線")
        t = _angle(d1, d2)
        return {"kind": "線-線", "angle": min(t, 180 - t), "supplement": max(t, 180 - t)}
    edge, face = (a, b) if not fa else (b, a)
    d, n = _line_dir(edge), _plane_normal(face)
    if d is None or n is None:
        raise ValueError("角度量測需要直線與平面")
    t = _angle(d, n)
    return {"kind": "線-面", "angle": 90.0 - min(t, 180 - t)}


def body_properties(shape: cq.Shape) -> dict:
    bb = shape.BoundingBox(tolerance=1e-7)
    return {"volume": shape.Volume() if shape.Solids() else 0.0, "area": shape.Area(), "center": shape.Center(),
            "size": (bb.xlen, bb.ylen, bb.zlen),
            "min": (bb.xmin, bb.ymin, bb.zmin), "max": (bb.xmax, bb.ymax, bb.zmax)}


# --- 半徑 / 直徑標註 ---
def _perpendicular(n: cq.Vector) -> cq.Vector:
    ref = cq.Vector(1, 0, 0) if abs(n.x) < 0.9 else cq.Vector(0, 1, 0)
    return n.cross(ref).normalized()


def circular_geometry(shape: cq.Shape, kind: str, index: int, at) -> dict:
    """由圓/圓弧邊、圓柱面或球面(含點選位置 at)取得標註用的圓: 圓心、半徑、法向與標註方向。"""
    at = cq.Vector(*[float(c) for c in at])
    if kind == "edge":
        edges = shape.Edges()
        if index >= len(edges):
            raise ValueError("找不到標註所指的邊(模型已改變)")
        curve = BRepAdaptor_Curve(edges[index].wrapped)
        if curve.GetType() != GeomAbs_Circle:
            raise ValueError("所選的邊不是圓或圓弧")
        c = curve.Circle()
        center, radius, normal = _vec(c.Location()), c.Radius(), _vec(c.Axis().Direction())
    else:
        faces = shape.Faces()
        if index >= len(faces):
            raise ValueError("找不到標註所指的面(模型已改變)")
        surf = BRepAdaptor_Surface(faces[index].wrapped)
        t = surf.GetType()
        if t == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            o, d = _vec(cyl.Axis().Location()), _vec(cyl.Axis().Direction())
            center, radius, normal = o + d * (at - o).dot(d), cyl.Radius(), d
        elif t == GeomAbs_Sphere:
            sph = surf.Sphere()
            center, radius = _vec(sph.Location()), sph.Radius()
            v = at - center
            normal = _perpendicular(v.normalized() if v.Length > 1e-9 else cq.Vector(0, 0, 1))
        else:
            raise ValueError("只支援圓/圓弧邊、圓柱面與球面")
    v = at - center
    v = v - normal * v.dot(normal)
    d = (v if v.Length > 1e-9 else _perpendicular(normal)).normalized()
    return {"center": center.toTuple(), "radius": radius, "normal": normal.toTuple(), "dir": d.toTuple()}


def annotation_geometry(ann: dict):
    """標註的圖形: (折線清單[numpy], 文字, 文字位置)。ann 需含 mode(半徑/直徑)與 circular_geometry 的欄位。"""
    import numpy as np
    c, n, d = (np.array(ann[k], float) for k in ("center", "normal", "dir"))
    r = float(ann["radius"])
    perp = np.cross(n, d)
    perp = perp / (np.linalg.norm(perp) or 1.0)
    a = r * 0.18

    def arrow(tip, inward):
        return np.array([tip - inward * a + perp * a * 0.35, tip, tip - inward * a - perp * a * 0.35])

    tip = c + d * r
    num = fmtn(r * (2 if ann["mode"] == "直徑" else 1))
    if ann["mode"] == "直徑":
        tip2 = c - d * r
        lines = [np.array([tip2, tip]), arrow(tip, -d), arrow(tip2, d)]
        return lines, f"Ø{num}", tip + d * r * 0.15
    lines = [np.array([c, tip]), arrow(tip, -d)]
    return lines, f"R{num}", tip + d * r * 0.15
