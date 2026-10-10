"""3D 路徑:螺旋線。軸線為工作平面法向,起點在平面原點 + 半徑 × 平面 X 軸。"""
import cadquery as cq
import numpy as np

from .features import plane_from_dict


def helix_wire(h: dict, wp: dict) -> cq.Wire:
    """h: {"pitch","height","radius","taper"(錐角度,0=圓柱),"left"(左旋)}。"""
    pitch, height, radius = h["pitch"], h["height"], h["radius"]
    if pitch <= 0 or height <= 0 or radius <= 0:
        raise ValueError("螺距、高度、半徑必須大於 0")
    taper = h.get("taper", 0.0)
    if not -80 < taper < 80:
        raise ValueError("錐角需介於 -80° 與 80° 之間")
    wire = cq.Wire.makeHelix(pitch, height, radius, angle=360.0 if abs(taper) < 1e-9 else taper,
                             lefthand=bool(h.get("left", False)))
    return cq.Wire(wire.transformShape(plane_from_dict(wp).rG).wrapped)


def helix_frame(wire: cq.Wire, wp: dict) -> cq.Plane:
    """螺旋線起點的剖面平面:X 軸為徑向向外、Y 軸沿螺旋軸,供掃掠輪廓自動對齊。"""
    pl = plane_from_dict(wp)
    start = wire.startPoint()
    axis = pl.zDir
    radial = start - pl.origin
    radial = radial - axis * radial.dot(axis)
    radial = radial.normalized()
    return cq.Plane(origin=start.toTuple(), xDir=radial.toTuple(), normal=radial.cross(axis).toTuple())


def polylines(wire: cq.Wire, n: int = 240):
    """顯示用折線。"""
    return [np.array([v.toTuple() for v in e.positions(np.linspace(0, 1, n))]) for e in wire.Edges()]
