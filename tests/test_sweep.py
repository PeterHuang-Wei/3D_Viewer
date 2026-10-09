import math
import pytest
from core import sketch2d as S
from core.model import Document

XY = {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, 0, 1]}
XZ = {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, -1, 0]}


def sketch(d, ents, wp):
    assert d.add_feature("sketch", {"entities": ents, "wp": wp}) is None
    return d.sketches[-1][0]


def test_straight_pipe_and_hollow():
    d = Document()
    prof = sketch(d, [S.circle((0, 0), 3)], XY)
    path = sketch(d, [S.line((0, 0), (0, 20))], XZ)          # XZ 平面的 v 軸 = +Z
    assert d.add_feature("sketch_sweep", {"profile": prof, "path": path, "op": "新實體"}) is None
    assert abs(d.bodies[0].shape.Volume() - math.pi * 9 * 20) < 1e-3
    bb = d.bodies[0].shape.BoundingBox()
    assert abs(bb.zmin) < 1e-3 and abs(bb.zmax - 20) < 1e-3
    ring = sketch(d, [S.circle((0, 0), 3), S.circle((0, 0), 2)], XY)   # 空心管
    assert d.add_feature("sketch_sweep", {"profile": ring, "path": path, "op": "新實體"}) is None
    assert abs(d.bodies[1].shape.Volume() - math.pi * (9 - 4) * 20) < 1e-3


def test_bent_path_and_align():
    d = Document()
    # 路徑:向上 10 -> 圓弧轉向 +X(半徑 5)-> 直線 10
    path = sketch(d, [S.line((0, 0), (0, 10)), S.arc_from_3pts((0, 10), (5 - 5 * math.cos(math.pi / 4), 10 + 5 * math.sin(math.pi / 4)), (5, 15)),
                      S.line((5, 15), (15, 15))], XZ)
    prof = sketch(d, [S.circle((0, 0), 1.5)], XY)
    assert d.add_feature("sketch_sweep", {"profile": prof, "path": path, "op": "新實體", "frenet": True}) is None
    length = 10 + 5 * math.pi / 2 + 10
    assert abs(d.bodies[0].shape.Volume() - math.pi * 1.5**2 * length) < 0.5
    # 輪廓在別的位置:自動對齊
    far = sketch(d, [S.circle((0, 0), 1.5)], {"origin": [30, 30, 30], "xdir": [1, 0, 0], "normal": [0, 0, 1]})
    err = d.add_feature("sketch_sweep", {"profile": far, "path": path, "op": "新實體", "align": True})
    assert err is None and abs(d.bodies[1].shape.Volume() - d.bodies[0].shape.Volume()) < 0.5


def test_sweep_cut_and_errors():
    d = Document()
    d.add_feature("box", {"x": 20, "y": 20, "z": 20})          # 中心在原點
    prof = sketch(d, [S.circle((0, 0), 2)], {"origin": [0, 0, -10], "xdir": [1, 0, 0], "normal": [0, 0, 1]})
    path = sketch(d, [S.line((0, 0), (0, 20))], {"origin": [0, 0, -10], "xdir": [1, 0, 0], "normal": [0, -1, 0]})
    v0 = d.bodies[0].shape.Volume()
    err = d.add_feature("sketch_sweep", {"profile": prof, "path": path, "op": "切除", "target": d.bodies[0].id})
    assert err is None and abs(v0 - d.bodies[0].shape.Volume() - math.pi * 4 * 20) < 1e-2
    bad = sketch(d, [S.line((0, 0), (0, 5)), S.line((10, 0), (10, 5))], XZ)   # 分離線段
    err = d.add_feature("sketch_sweep", {"profile": prof, "path": bad, "op": "新實體"})
    assert err and "連續" in err
    with pytest.raises(ValueError):
        S.ordered_chain([S.circle((0, 0), 1)])
