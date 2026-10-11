import math
import pytest
from core import features as F
from core.model import Document

TOP = {"origin": [0, 0, 10], "xdir": [1, 0, 0], "normal": [0, 0, 1]}


def doc_box():
    d = Document()
    d.add_feature("box", {"x": 40, "y": 40, "z": 20})          # z -10..10
    return d, d.bodies[0].id


def test_pattern_linear_and_circular():
    d = Document()
    d.add_feature("box", {"x": 4, "y": 4, "z": 4})
    bid = d.bodies[0].id
    assert d.add_feature("pattern", {"body": bid, "kind": "線性", "n": 4, "dx": 10, "dy": 0, "dz": 0}) is None
    assert abs(d.bodies[0].shape.Volume() - 4 * 64) < 1e-6
    assert abs(d.bodies[0].shape.BoundingBox().xlen - 34) < 1e-2
    d2 = Document()
    d2.add_feature("box", {"x": 2, "y": 2, "z": 2})
    d2.add_feature("translate", {"body": 1, "x": 10, "y": 0, "z": 0})
    err = d2.add_feature("pattern", {"body": 1, "kind": "圓形", "n": 6, "angle": 360.0, "axis": "Z 軸",
                                     "cx": 0, "cy": 0, "cz": 0, "dx": 0, "dy": 0, "dz": 0})
    assert err is None and abs(d2.bodies[0].shape.Volume() - 6 * 8) < 1e-6
    assert d2.add_feature("pattern", {"body": 1, "kind": "線性", "n": 1, "dx": 1, "dy": 0, "dz": 0}) is not None
    # 鎖定平面法向當軸
    err = d2.add_feature("pattern", {"body": 1, "kind": "圓形", "n": 2, "angle": 180.0, "axis": "鎖定平面法向",
                                     "wp": TOP, "cx": 0, "cy": 0, "cz": 0, "dx": 0, "dy": 0, "dz": 0})
    assert err is None


def test_mirror():
    d = Document()
    d.add_feature("box", {"x": 4, "y": 4, "z": 4})
    d.add_feature("translate", {"body": 1, "x": 10, "y": 0, "z": 0})
    assert d.add_feature("mirror", {"body": 1, "plane": "YZ", "op": "聯集到原實體"}) is None
    bb = d.bodies[0].shape.BoundingBox()
    assert abs(bb.xmin + 12) < 1e-2 and abs(bb.xmax - 12) < 1e-2 and abs(d.bodies[0].shape.Volume() - 128) < 1e-6
    assert d.add_feature("mirror", {"body": 1, "plane": "鎖定平面", "op": "另建新實體", "wp": TOP}) is None
    assert len(d.bodies) == 2                               # 以 z=10 平面鏡射,產生新實體
    assert abs(d.bodies[1].shape.Center().z - 20) < 1e-6


def test_holes():
    d, bid = doc_box()
    base = d.bodies[0].shape.Volume()
    p = {"body": bid, "wp": TOP, "type": "簡單孔", "d": 6, "depth": 10, "pts": "0,0; 10,10", "flip": False}
    assert d.add_feature("hole", p) is None
    assert abs(base - d.bodies[0].shape.Volume() - 2 * math.pi * 9 * 10) < 1e-3
    d.undo()
    thru = {**p, "depth": 0}                                # 通孔
    assert d.add_feature("hole", thru) is None
    assert abs(base - d.bodies[0].shape.Volume() - 2 * math.pi * 9 * 20) < 1e-3
    d.undo()
    cb = {**p, "type": "沉頭孔", "cb_d": 12, "cb_depth": 4, "pts": "0,0"}
    assert d.add_feature("hole", cb) is None
    assert abs(base - d.bodies[0].shape.Volume() - (math.pi * 9 * 10 + math.pi * (36 - 9) * 4)) < 1e-2
    d.undo()
    csk = {**p, "type": "埋頭孔", "csk_d": 12, "csk_angle": 90, "pts": "0,0"}
    assert d.add_feature("hole", csk) is None
    assert d.bodies[0].shape.Volume() < base - math.pi * 9 * 10
    assert d.add_feature("hole", {**p, "pts": ""}) is not None
    assert d.add_feature("hole", {**p, "wp": {"origin": [0, 0, 50], "xdir": [1, 0, 0], "normal": [0, 0, 1]}}) is not None
    assert d.add_feature("hole", {**p, "type": "沉頭孔", "cb_d": 3, "cb_depth": 1}) is not None


def test_shell():
    d, bid = doc_box()
    top = next(i for i, f in enumerate(d.bodies[0].shape.Faces()) if f.Center().z > 9)
    assert d.add_feature("shell", {"body": bid, "faces": [top], "thickness": 2.0, "dir": "向內"}) is None
    assert abs(d.bodies[0].shape.Volume() - (40 * 40 * 20 - 36 * 36 * 18)) < 1e-3
    d.undo()
    assert d.add_feature("shell", {"body": bid, "faces": [], "thickness": 2.0, "dir": "向內"}) is None
    assert abs(d.bodies[0].shape.Volume() - (32000 - 36 * 36 * 16)) < 1e-3
    assert d.add_feature("shell", {"body": bid, "faces": [top], "thickness": 30.0, "dir": "向內"}) is not None
    assert d.add_feature("shell", {"body": bid, "faces": [top], "thickness": 0, "dir": "向內"}) is not None
