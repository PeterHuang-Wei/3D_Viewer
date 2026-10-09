import math
import pytest
from core import sketch2d as S
from core import features as F


def test_arc_from_3pts():
    a = S.arc_from_3pts((1, 0), (0, 1), (-1, 0))          # 上半圓,逆時針
    assert abs(a["r"] - 1) < 1e-9 and abs(S.span(a) - 180) < 1e-6
    b = S.arc_from_3pts((1, 0), (0, -1), (-1, 0))         # 下半圓(順時針經過 p2)
    assert abs(S.span(b) - 180) < 1e-6 and abs(b["a0"] - 180) < 1e-6
    with pytest.raises(ValueError):
        S.arc_from_3pts((0, 0), (1, 1), (2, 2))


def test_intersections_and_trim():
    a, b = S.line((0, 0), (10, 0)), S.line((5, -5), (5, 5))
    assert S.intersections(a, b) == [[5.0, 0.0]]
    c = S.circle((0, 0), 5)
    assert len(S.intersections(S.line((-10, 0), (10, 0)), c)) == 2
    assert len(S.intersections(c, S.circle((5, 0), 5))) == 2
    # 修整:十字線,點右側那一段 -> 剩下三段中不含右段
    ents = [a, b]
    out = S.trim(ents, 0, (8, 0))
    assert len(out) == 2
    xs = sorted(round(max(e["p1"][0], e["p2"][0]), 3) for e in out if e["p1"][1] == e["p2"][1] == 0)
    assert xs == [5.0]                                       # 只留下 0~5
    assert len(S.trim([a], 0, (3, 0))) == 0                   # 沒交點:整條刪除


def test_split_circle_and_arc():
    c = S.circle((0, 0), 5)
    pieces = S.split_entity(c, [[5, 0], [-5, 0]])
    assert len(pieces) == 2 and all(abs(S.span(p) - 180) < 1e-6 for p in pieces)
    a = S.arc((0, 0), 5, 0, 180)
    parts = S.split_entity(a, [[0, 5]])
    assert len(parts) == 2 and abs(S.span(parts[0]) - 90) < 1e-6


def test_mirror_pattern():
    ln = S.line((1, 1), (3, 2))
    m = S.mirror_entity(ln, (0, 0), (0, 1))                    # 對 Y 軸
    assert m["p1"] == [-1, 1] and m["p2"] == [-3, 2]
    ar = S.arc((0, 0), 1, 0, 90)                               # 第一象限
    mr = S.mirror_entity(ar, (0, 0), (0, 1))                   # 鏡到第二象限
    assert abs(mr["a0"] - 90) < 1e-6 and abs(mr["a1"] - 180) < 1e-6
    ents = [ln]
    assert len(S.linear_pattern(ents, [0], 4, 10, 0)) == 4
    cp = S.circular_pattern([S.line((5, 0), (6, 0))], [0], 4, 360, (0, 0))
    assert len(cp) == 4 and abs(cp[1]["p1"][1] - 5) < 1e-9     # 轉 90 度


def test_parse_input():
    assert S.parse_input("3,4") == ("point", (3.0, 4.0))
    assert S.parse_input("@1,2", last=(10, 10)) == ("point", (11.0, 12.0))
    k, p = S.parse_input("@10<90", last=(0, 0))
    assert k == "point" and abs(p[0]) < 1e-9 and abs(p[1] - 10) < 1e-9
    assert S.parse_input("5") == ("number", 5.0)
    assert S.parse_input("5", last=(0, 0), direction=(0, 1)) == ("point", (0.0, 5.0))


def test_profiles_and_solids():
    ents = S.rectangle((0, 0), (20, 10)) + [S.circle((10, 5), 3)]
    profs = S.profiles(ents)
    assert len(profs) == 1 and len(profs[0][1]) == 1             # 一個外框、一個孔
    wp = F.WORLD_PLANES["XY"]
    solid = S.extrude_solid(ents, wp, 4)
    assert abs(solid.Volume() - (200 - math.pi * 9) * 4) < 1e-3
    sym = S.extrude_solid(ents, wp, 4, symmetric=True)
    assert abs(sym.BoundingBox().zmin + 2) < 1e-2
    # 旋轉:矩形離開 Y 軸
    rv = S.revolve_solid(S.rectangle((5, 0), (7, 3)), wp, 360, "Y")
    assert abs(rv.Volume() - math.pi * (49 - 25) * 3) < 1e-3
    with pytest.raises(ValueError):
        S.local_faces([S.line((0, 0), (1, 0))])


def test_arc_profile():
    # 半圓形輪廓:直線 + 半圓弧
    ents = [S.line((-5, 0), (5, 0)), S.arc((0, 0), 5, 0, 180)]
    solid = S.extrude_solid(ents, F.WORLD_PLANES["XY"], 2)
    assert abs(solid.Volume() - math.pi * 25 / 2 * 2) < 1e-2
    # 修整後仍可成形:兩線交叉、修掉多餘端後形成封閉三角形
    tri = [S.line((0, 0), (10, 0)), S.line((10, 0), (5, 8)), S.line((5, 8), (0, 0))]
    assert len(S.profiles(tri)) == 1


def test_sketch_features_in_document():
    from core.model import Document
    d = Document()
    d.add_feature("box", {"x": 20, "y": 20, "z": 10})
    top = {"origin": [0, 0, 5], "xdir": [1, 0, 0], "normal": [0, 0, 1]}
    ents = [S.circle((0, 0), 3)]
    assert d.add_feature("sketch", {"entities": ents, "wp": top}) is None
    sid = d.sketches[0][0]
    v0 = d.bodies[0].shape.Volume()
    err = d.add_feature("sketch_extrude", {"sketch": sid, "depth": 4, "flip": True, "sym": False,
                                           "op": "切除", "target": d.bodies[0].id})
    assert err is None and abs(d.bodies[0].shape.Volume() - (v0 - math.pi * 9 * 4)) < 1e-2
    assert d.add_feature("sketch_extrude", {"sketch": sid, "depth": 4, "op": "新實體"}) is None
    assert len(d.bodies) == 2
    # 修改草圖 -> 重算
    assert d.edit_feature(1, {"entities": [S.circle((0, 0), 2)]}) is None
    assert abs(d.bodies[0].shape.Volume() - (v0 - math.pi * 4 * 4)) < 1e-2
    # 切除未重疊 -> 報錯並還原
    n = len(d.features)
    err = d.add_feature("sketch_extrude", {"sketch": sid, "depth": 1, "flip": False, "op": "切除",
                                           "target": d.bodies[0].id})
    assert err and len(d.features) == n
    assert d.add_feature("sketch_revolve", {"sketch": sid, "angle": 360, "axis": "Y", "op": "新實體"}) \
        is not None                                             # 圓跨過旋轉軸 -> 失敗
