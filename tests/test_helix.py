import math
import pytest
from core import sketch2d as S
from core import paths as PA
from core.model import Document

XY = {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, 0, 1]}
XZ = {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, -1, 0]}


def test_helix_wire_geometry():
    h = {"pitch": 2.0, "height": 10.0, "radius": 5.0}
    w = PA.helix_wire(h, XY)
    s, e = w.startPoint(), w.endPoint()
    assert abs(s.x - 5) < 1e-6 and abs(e.z - 10) < 1e-6
    # 放在 YZ 平面(法向 +X、X 軸=Y):軸向沿 +X,起點在 +Y 方向
    w2 = PA.helix_wire(h, {"origin": [1, 2, 3], "xdir": [0, 1, 0], "normal": [1, 0, 0]})
    s2, e2 = w2.startPoint(), w2.endPoint()
    assert abs(s2.y - 7) < 1e-6 and abs(s2.x - 1) < 1e-6 and abs(e2.x - 11) < 1e-6
    with pytest.raises(ValueError):
        PA.helix_wire({"pitch": 0, "height": 1, "radius": 1}, XY)
    frame = PA.helix_frame(w, XY)
    assert abs(frame.xDir.x - 1) < 1e-6 and abs(frame.yDir.z - 1) < 1e-6


def spring(d, **kw):
    assert d.add_feature("sketch", {"entities": [S.circle((0, 0), 0.8)], "wp": XZ}) is None
    assert d.add_feature("helix", {"pitch": 3.0, "height": 12.0, "radius": 5.0, "taper": 0.0, "left": False, **kw,
                                   "wp": XY}) is None
    return d.sketches[0][0], d.helices[0][0]


def test_spring_sweep_and_edit():
    d = Document()
    prof, hx = spring(d)
    # 輪廓畫在 XZ 平面且圓心在 (5,0):用 cx 偏移到螺旋起點
    d.edit_feature(0, {"entities": [S.circle((5, 0), 0.8)]})
    assert d.add_feature("sketch_sweep", {"profile": prof, "path": hx, "op": "新實體", "frenet": True}) is None
    v = d.bodies[0].shape.Volume()
    length = 4 * math.hypot(2 * math.pi * 5, 3)               # 4 圈
    assert abs(v - math.pi * 0.8**2 * length) / v < 0.02
    # 改螺距 -> 彈簧自動重算(圈數變少,長度變短)
    assert d.edit_feature(1, {"pitch": 4.0}) is None
    assert d.bodies[0].shape.Volume() < v


def test_align_and_left_and_taper():
    d = Document()
    prof, hx = spring(d)                                      # 圓心在原點 -> 需要自動對齊
    err = d.add_feature("sketch_sweep", {"profile": prof, "path": hx, "op": "新實體", "align": True})
    assert err is None
    right = d.bodies[0].shape.Volume()
    assert d.edit_feature(1, {"left": True}) is None and abs(d.bodies[0].shape.Volume() - right) / right < 0.01
    assert d.edit_feature(1, {"left": False, "taper": 10.0}) is None
    assert d.bodies[0].shape.Volume() > right                  # 錐形半徑變大,線較長


def test_thread_by_sweep_and_fuse():
    d = Document()
    d.add_feature("cylinder", {"r": 4, "h": 20})              # 中心在原點,z -10..10
    tri = [S.line((0, 0), (1.0, 0.5)), S.line((1.0, 0.5), (1.0, -0.5)), S.line((1.0, -0.5), (0, 0))]
    d.add_feature("sketch", {"entities": [S.line((3.8, -0.6), (5.0, 0.0)), S.line((5.0, 0.0), (3.8, 0.6)),
                                          S.line((3.8, 0.6), (3.8, -0.6))], "wp": XZ})
    d.add_feature("helix", {"pitch": 1.5, "height": 12.0, "radius": 4.0, "taper": 0.0, "left": False,
                            "wp": {"origin": [0, 0, -6], "xdir": [1, 0, 0], "normal": [0, 0, 1]}})
    # 牙型畫在 XZ 平面(z 軸向),但螺旋起點在 z=-6:改用自動對齊(以螺旋起點為原點的徑向/軸向座標)
    d.edit_feature(1, {"entities": [S.line((-0.2, -0.6), (1.0, 0.0)), S.line((1.0, 0.0), (-0.2, 0.6)),
                                    S.line((-0.2, 0.6), (-0.2, -0.6))]})
    sk, hx = d.sketches[0][0], d.helices[0][0]
    err = d.add_feature("sketch_sweep", {"profile": sk, "path": hx, "op": "聯集", "align": True,
                                         "target": d.bodies[0].id})
    assert err is None and d.bodies[0].shape.Volume() > math.pi * 16 * 20
