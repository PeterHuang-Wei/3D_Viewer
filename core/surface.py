"""曲面建模:曲面拉伸、偏移面、修剪、縫合、加厚。
曲面體 = 沒有實體(Solid)、只有面的形狀(Face / Shell / 面的集合)。"""
import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GeomAbs import GeomAbs_Arc
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopTools import TopTools_ListOfShape
from OCP.gp import gp_Vec

from . import features as F
from . import sketch2d as SK


def is_surface(shape: cq.Shape) -> bool:
    return not shape.Solids() and bool(shape.Faces())


def _compound(shapes):
    shapes = [s for s in shapes if s is not None]
    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _cast(s):
    return cq.Shape.cast(s)


# --- 曲面拉伸 ---
def extrude_surface(entities, wp, depth: float, symmetric: bool = False) -> cq.Shape:
    """草圖輪廓(開放或封閉皆可,不封端)沿草圖法向拉伸成曲面。"""
    ents = SK.profile_entities(entities)
    if not ents:
        raise ValueError("草圖是空的")
    if abs(depth) < 1e-9:
        raise ValueError("拉伸距離不可為 0")
    wires = [cq.Wire.assembleEdges([SK._edge(e)]) for e in ents if SK.is_closed_by_itself(e)]
    rest = [e for e in ents if not SK.is_closed_by_itself(e)]
    if rest:
        wires.append(SK._wire(SK.ordered_chain(rest)))
    parts = []
    for w in wires:
        if symmetric:
            w = w.moved(cq.Location(cq.Vector(0, 0, -depth / 2)))
        mk = BRepPrimAPI_MakePrism(w.wrapped, gp_Vec(0, 0, depth))
        mk.Build()
        parts.append(_cast(mk.Shape()))
    return SK.to_global(_compound(parts), wp)


# --- 偏移面 ---
def offset_faces(shape: cq.Shape, face_ids, distance: float, tol: float = 1e-4) -> cq.Shape:
    """把所選面(空 = 全部面)沿法向偏移 distance(負值反向),回傳新的曲面。"""
    faces = shape.Faces()
    sel = [faces[i] for i in sorted(face_ids)] if face_ids else faces
    if face_ids and max(face_ids) >= len(faces):
        raise ValueError("所選的面不存在(模型已改變?)")
    if abs(distance) < 1e-9:
        raise ValueError("偏移距離不可為 0")
    out = []
    for f in sel:
        mk = BRepOffsetAPI_MakeOffsetShape()
        try:
            mk.PerformByJoin(f.wrapped, distance, tol)
        except Exception as e:  # noqa: BLE001
            raise ValueError("偏移面失敗(曲率半徑小於偏移距離?)") from e
        if not mk.IsDone():
            raise ValueError("偏移面失敗(曲率半徑小於偏移距離?)")
        out.append(_cast(mk.Shape()))
    return _compound(out)


# --- 修剪 ---
def _half_space(wp: dict, positive: bool, size: float) -> cq.Shape:
    n = cq.Vector(*wp["normal"]).normalized()
    pl = F.plane_from_dict(wp)
    box = cq.Solid.makeBox(size, size, size, cq.Vector(-size / 2, -size / 2, 0 if positive else -size))
    return box.transformShape(pl.rG)


def trim_by_plane(shape: cq.Shape, wp: dict, keep_positive: bool) -> cq.Shape:
    """用平面修剪曲面:保留平面法向的正側(或負側)。"""
    bb = shape.BoundingBox()
    size = 4 * max(bb.xlen, bb.ylen, bb.zlen, 1.0) + 4 * max(abs(c) for c in wp["origin"]) + 10
    res = shape.cut(_half_space(wp, not keep_positive, size))
    if not res.Faces():
        raise ValueError("修剪後沒有剩餘的面(修剪平面與曲面沒有交集或全部被切除)")
    return res


def trim_by_tool(shape: cq.Shape, tool: cq.Shape, keep: str) -> cq.Shape:
    """用另一個實體/曲面修剪。tool 為實體:keep='外側'/'內側';tool 為曲面:keep='正側'/'負側'(依該面法向)。"""
    if tool.Solids():
        res = shape.cut(tool) if keep == "外側" else shape.intersect(tool)
        if not res.Faces():
            raise ValueError("修剪後沒有剩餘的面")
        return res
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(shape.wrapped)
    tools.Append(tool.wrapped)
    sp = BRepAlgoAPI_Splitter()
    sp.SetArguments(args)
    sp.SetTools(tools)
    sp.Build()
    if not sp.IsDone():
        raise ValueError("曲面分割失敗")
    pieces = _cast(sp.Shape()).Faces()
    if len(pieces) <= len(shape.Faces()):
        raise ValueError("兩曲面沒有相交,無法修剪")
    from . import measure as MS
    tfaces = tool.Faces()
    keep_pos = keep == "正側"
    kept = []
    for f in pieces:
        c = f.Center()
        v = cq.Vertex.makeVertex(c.x, c.y, c.z)
        best = min(tfaces, key=lambda tf: tf.distance(v))
        _, _, pt = MS.min_distance(v, best)
        side = (c - pt).dot(best.normalAt(pt))               # 該片在工具面法向的哪一側
        if (side >= 0) == keep_pos:
            kept.append(f)
    if not kept:
        raise ValueError("修剪後沒有剩餘的面")
    return _compound(kept)


# --- 縫合 ---
def knit(shapes, tol: float = 1e-3) -> cq.Shape:
    """把多個曲面縫合;縫成封閉的殼會自動變成實體。tol 為縫合容差。"""
    if not shapes:
        raise ValueError("沒有要縫合的曲面")
    sew = BRepBuilderAPI_Sewing(tol)
    for s in shapes:
        for f in s.Faces():
            sew.Add(f.wrapped)
    sew.Perform()
    res = _cast(sew.SewedShape())
    shells = res.Shells()
    if len(shells) == 1 and len(res.Faces()) == len(shells[0].Faces()) and shells[0].Closed():
        sf = ShapeFix_Solid()
        sol = _cast(sf.SolidFromShell(shells[0].wrapped))
        if sol.Volume() < 0:
            sol = _cast(sol.wrapped.Reversed())
        if sol.Volume() > 1e-9:
            return sol
    return res


# --- 加厚 ---
def _thicken_one(shape: cq.Shape, offset: float, tol: float = 1e-4) -> cq.Shape:
    mk = BRepOffset_MakeOffset()
    mk.Initialize(shape.wrapped, offset, tol, BRepOffset_Skin, True, False, GeomAbs_Arc, True)
    mk.MakeOffsetShape()
    if not mk.IsDone():
        raise ValueError("加厚失敗(厚度大於曲面曲率半徑?請減小厚度)")
    res = _cast(mk.Shape())
    if not res.Solids() or res.Volume() < 1e-9:
        raise ValueError("加厚失敗(厚度大於曲面曲率半徑?請減小厚度)")
    return res


def thicken(shape: cq.Shape, thickness: float, mode: str = "單側") -> cq.Shape:
    """曲面 -> 實體。mode: 單側(沿面法向)/ 反側 / 對稱。"""
    if thickness <= 0:
        raise ValueError("厚度必須大於 0")
    if not is_surface(shape):
        raise ValueError("加厚只能用在曲面(此物件已是實體)")
    if mode == "對稱":
        a, b = _thicken_one(shape, thickness / 2), _thicken_one(shape, -thickness / 2)
        res = a.fuse(b).clean()
    else:
        res = _thicken_one(shape, thickness if mode == "單側" else -thickness)
    if not res.isValid():
        raise ValueError("加厚結果無效(曲面有自交或厚度過大)")
    return res
