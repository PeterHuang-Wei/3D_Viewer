import math
import pytest
import cadquery as cq
from core import features as F
from core import sketch2d as S
from core.model import Document

XZ = {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, -1, 0]}
BOTTOM = {"origin": [0, 0, -10], "xdir": [1, 0, 0], "normal": [0, 0, 1]}


def side_ids(shape):
    return [i for i, f in enumerate(shape.Faces()) if abs(f.normalAt().z) < 0.1]


def test_draft_box_sides():
    b = F.make_box(20, 20, 20)
    r = F.draft_faces(b, side_ids(b), 5, BOTTOM)
    top = max(r.Faces(), key=lambda f: f.Center().z)
    side = 20 - 2 * 20 * math.tan(math.radians(5))
    assert abs(top.Area() - side * side) < 1e-6
    bot = min(r.Faces(), key=lambda f: f.Center().z)
    assert abs(bot.Area() - 400) < 1e-6                           # 中性面上的底面不變
    out = F.draft_faces(b, side_ids(b), 5, BOTTOM, flip=True)      # 反向:往外擴
    assert max(out.Faces(), key=lambda f: f.Center().z).Area() > 400
    for bad in (0, 90, -95):
        with pytest.raises(ValueError):
            F.draft_faces(b, side_ids(b), bad, BOTTOM)
    with pytest.raises(ValueError):
        F.draft_faces(b, [], 5, BOTTOM)


def test_draft_feature_and_edit():
    d = Document()
    d.add_feature("box", {"x": 20, "y": 20, "z": 20})
    ids = side_ids(d.bodies[0].shape)
    assert d.add_feature("draft", {"body": 1, "faces": ids, "angle": 3.0, "plane": "鎖定平面", "wp": BOTTOM, "flip": False}) is None
    v3 = d.bodies[0].shape.Volume()
    assert d.edit_feature(1, {"angle": 6.0}) is None and d.bodies[0].shape.Volume() < v3      # 角度越大越細
    assert d.add_feature("draft", {"body": 1, "faces": ids, "angle": 3.0, "plane": "XY", "offset": -10.0, "flip": False}) is None
    assert d.add_feature("draft", {"body": 1, "faces": ids, "angle": 3.0, "plane": "鎖定平面", "flip": False}) is not None   # 缺少工作平面


def bracket_doc():
    d = Document()
    d.add_feature("box", {"x": 40, "y": 20, "z": 4})                                  # 底板 z -2..2
    d.add_feature("translate", {"body": 1, "x": 0, "y": 0, "z": 2})                   # z 0..4
    d.add_feature("box", {"x": 4, "y": 20, "z": 30})
    d.add_feature("translate", {"body": 2, "x": 18, "y": 0, "z": 15})                 # x 16..20, z 0..30
    d.add_feature("boolean", {"op": "聯集", "target": 1, "tool": 2, "keep": False})
    return d


def test_rib_gusset_fills_corner_triangle():
    d = bracket_doc()
    base = d.bodies[0].shape.Volume()
    sk = [S.line((4, 4), (16, 16))]
    assert d.add_feature("sketch", {"entities": sk, "wp": XZ}) is None
    sid = d.sketches[0][0]
    assert d.add_feature("rib", {"body": 1, "sketch": sid, "thickness": 3.0, "symmetric": True, "flip": False}) is None
    added = d.bodies[0].shape.Volume() - base
    assert abs(added - 72 * 3) < 1e-3                                                 # 三角形 12×12/2 = 72,厚 3
    bb = d.bodies[0].shape.BoundingBox()
    assert abs(bb.ylen - 20) < 1e-3
    k = next(i for i, f in enumerate(d.features) if f.kind == "rib")
    assert d.edit_feature(k, {"thickness": 5.0}) is None and abs(d.bodies[0].shape.Volume() - base - 72 * 5) < 1e-3
    # 輪廓離實體太遠:拒絕
    far = [S.line((100, 100), (110, 110))]
    d.add_feature("sketch", {"entities": far, "wp": XZ})
    assert d.add_feature("rib", {"body": 1, "sketch": d.sketches[-1][0], "thickness": 3.0, "symmetric": True, "flip": False}) is not None
    with pytest.raises(ValueError):
        F.rib_solid(F.make_box(5, 5, 5), S.path_wire([S.line((0, 0), (1, 1))], XZ), (0, -1, 0), 0)      # 肋厚為 0
