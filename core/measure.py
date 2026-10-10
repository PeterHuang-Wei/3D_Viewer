"""量測:距離、邊/面資訊、角度、實體屬性(皆為純 OpenCascade 計算,與介面無關)。"""
import math

import cadquery as cq
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
    return {"volume": shape.Volume(), "area": shape.Area(), "center": shape.Center(),
            "size": (bb.xlen, bb.ylen, bb.zlen),
            "min": (bb.xmin, bb.ymin, bb.zmin), "max": (bb.xmax, bb.ymax, bb.zmax)}
