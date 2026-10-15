"""組合件:插入零件(.v3d 專案)與配合(面貼合 / 同軸 / 平行 / 垂直 / 角度 / 距離)。"""
import numpy as np
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder

from . import features as F

EPS = 1e-7
MATE_TYPES = ("面貼合", "同軸", "平行", "垂直", "角度", "距離")


def project_shapes(data: dict, dx=0.0, dy=0.0, dz=0.0):
    """由專案資料 dict 重算並回傳 [(名稱, 形狀)],整體平移 (dx,dy,dz)。"""
    from .model import Document
    doc = Document()
    doc.load_data(data)
    bad = [f.title for f in doc.features if f.error]
    out = [(b.name, F.translate(b.shape, dx, dy, dz)) for b in doc.bodies]
    if not out:
        raise ValueError("零件專案中沒有實體" + (f"(特徵錯誤:{'、'.join(bad)})" if bad else ""))
    return out


def _np(v):
    return np.array([v.x, v.y, v.z], float)


def face_frame(face: cq.Face):
    """回傳 (類型, 基準點, 單位方向):平面 -> 面中心與外法向;圓柱/圓錐 -> 軸上一點與軸向。"""
    ad = BRepAdaptor_Surface(face.wrapped)
    t = ad.GetType()
    if t in (GeomAbs_Cylinder, GeomAbs_Cone):
        ax = ad.Cylinder().Axis() if t == GeomAbs_Cylinder else ad.Cone().Axis()
        loc, d = ax.Location(), ax.Direction()
        return "axis", np.array([loc.X(), loc.Y(), loc.Z()]), np.array([d.X(), d.Y(), d.Z()])
    if face.geomType() == "PLANE":
        return "plane", _np(face.Center()), _np(face.normalAt())
    raise ValueError("配合只支援平面、圓柱面與圓錐面")


def _rot_to(shape, c, src, dst):
    """繞 c 把方向 src 轉到 dst;回傳新形狀與旋轉函式(作用於點)。"""
    cr = np.cross(src, dst)
    s = np.linalg.norm(cr)
    dot = float(np.dot(src, dst))
    if s < EPS:
        if dot > 0:
            return shape, lambda p: p
        helper = np.array([1.0, 0, 0]) if abs(src[0]) < 0.9 else np.array([0, 1.0, 0])
        axis, ang = np.cross(src, helper), 180.0
    else:
        axis, ang = cr, float(np.degrees(np.arctan2(s, dot)))
    axis = axis / np.linalg.norm(axis)
    cv = cq.Vector(*c)
    new = shape.rotate(cv, cv + cq.Vector(*axis), ang)
    return new, lambda p: c + F._rot(np.asarray(p, float) - c, axis, ang)


def _turn(shape, pivot, nb, na, delta_deg):
    """繞 pivot、軸 nb×na,把 nb 朝 na 轉 delta 度;回傳新形狀與點變換函式。"""
    cr = np.cross(nb, na)
    if np.linalg.norm(cr) < EPS:
        helper = np.array([1.0, 0, 0]) if abs(nb[0]) < 0.9 else np.array([0, 1.0, 0])
        cr = np.cross(nb, helper)
    axis = cr / np.linalg.norm(cr)
    if abs(delta_deg) < 1e-9:
        return shape, lambda p: np.asarray(p, float)
    pv = cq.Vector(*pivot)
    new = shape.rotate(pv, pv + cq.Vector(*axis), delta_deg)
    return new, lambda p: pivot + F._rot(np.asarray(p, float) - pivot, axis, delta_deg)


def _angle_between(u, v):
    return float(np.degrees(np.arctan2(np.linalg.norm(np.cross(u, v)), np.dot(u, v))))


def _want(kind, angle, phi, ta, tb):
    """方向向量 nb 與 na 之間期望的夾角(度)。同類(面-面 / 軸-軸)與混合(面-軸)的語意不同。"""
    near = 0.0 if phi <= 90 else 180.0
    if ta == tb:
        plane_pair = ta == "plane"
        return {"平行": near, "垂直": 90.0}.get(kind, 180.0 - angle if plane_pair else angle)
    return {"平行": 90.0, "垂直": near}.get(kind, 90.0 - angle)        # 軸線與平面:平行 = 軸線 ⟂ 法向


def _orient(moving, pivot, nb, na, kind, angle, flip, ta, tb):
    """平行 / 垂直 / 角度:只旋轉(繞 pivot),使 nb 與 na 的夾角達到目標;flip 取另一側的解。
    面對面的「角度」是兩平面之間的夾角(0° = 貼平,法向夾角 = 180° − 夾角)。"""
    phi = _angle_between(nb, na)
    want = _want(kind, angle, phi, ta, tb)
    return _turn(moving, pivot, nb, na, (phi + want) if flip else (phi - want))


def mate_shape(fixed: cq.Shape, face_a: int, moving: cq.Shape, face_b: int, kind: str,
               offset: float = 0.0, flip: bool = False, angle: float = 0.0) -> cq.Shape:
    """移動 moving 使其第 face_b 面與 fixed 的第 face_a 面配合。
    面貼合:兩平面法向相反並相距 offset(flip 則同向);同軸:圓柱/圓錐軸線重合(僅平行者不再旋轉)。
    已經滿足的自由度(例如已反向的法向、同軸時的軸向位置)不會被改動,方便連續配合。"""
    fa, fb = fixed.Faces(), moving.Faces()
    if not (0 <= face_a < len(fa)) or not (0 <= face_b < len(fb)):
        raise ValueError("配合的面不存在(模型已改變?)")
    ta, pa, na = face_frame(fa[face_a])
    tb, pb, nb = face_frame(fb[face_b])
    c = _np(moving.Center())
    if kind == "面貼合":
        if ta != "plane" or tb != "plane":
            raise ValueError("面貼合需要兩個平面")
        target = na if flip else -na
        moving, rot = _rot_to(moving, c, nb, target)
        pb = rot(pb)
        delta = na * (float(np.dot(pa - pb, na)) + offset)
        return F.translate(moving, *delta)
    if kind == "同軸":
        if ta != "axis" or tb != "axis":
            raise ValueError("同軸需要兩個圓柱面或圓錐面")
        if np.linalg.norm(np.cross(na, nb)) > EPS:
            moving, rot = _rot_to(moving, c, nb, na if np.dot(na, nb) > 0 else -na)
            pb = rot(pb)
        d = pa - pb
        d = d - na * float(np.dot(d, na))             # 只做垂直軸向的平移
        return F.translate(moving, *d)
    if kind in ("平行", "垂直", "角度"):
        if not -180 <= angle <= 180:
            raise ValueError("角度需介於 -180° 與 180°")
        return _orient(moving, pb, nb, na, kind, angle, flip, ta, tb)[0]
    if kind == "距離":
        if ta != tb:
            raise ValueError("距離配合需要兩個平面,或兩個圓柱/圓錐面")
        if ta == "plane":
            moving, rot = _turn(moving, pb, nb, na, _angle_between(nb, na) - (0.0 if flip else 180.0))
            pb = rot(pb)
            return F.translate(moving, *(na * (float(np.dot(pa - pb, na)) + offset)))
        # 軸線:先平行,再讓兩軸線相距 offset
        phi = _angle_between(nb, na)
        moving, rot = _turn(moving, pb, nb, na, phi if phi <= 90 else phi - 180.0)
        pb = rot(pb)
        d = pa - pb
        d = d - na * float(np.dot(d, na))
        n = np.linalg.norm(d)
        if offset > 1e-9:
            if n > EPS:
                d = d - d / n * offset
            else:
                helper = np.array([1.0, 0, 0]) if abs(na[0]) < 0.9 else np.array([0, 1.0, 0])
                d = -np.cross(na, helper) / np.linalg.norm(np.cross(na, helper)) * offset
        return F.translate(moving, *d)
    raise ValueError(f"未知配合類型:{kind}")
