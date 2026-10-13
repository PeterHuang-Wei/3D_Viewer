import math
import pytest
import cadquery as cq
from core import sketch2d as S
from core import sketch_solver as K
from core import features as F


def corner():
    return S.assign_ids([S.line((0, 0), (10, 0)), S.line((0, 0), (0, 10))])


def test_fillet_corner_geometry():
    out = S.fillet_corner(corner(), 0, 1, 2.0)
    arcs = [e for e in out if e["t"] == "arc"]
    lines = [e for e in out if e["t"] == "line"]
    assert len(arcs) == 1 and len(lines) == 2
    a = arcs[0]
    assert abs(a["r"] - 2) < 1e-9 and abs(a["c"][0] - 2) < 1e-9 and abs(a["c"][1] - 2) < 1e-9       # 圓心 (2,2)
    assert abs(S.span(a) - 90) < 1e-6
    ends = {tuple(round(v, 6) for v in p) for e in out for p in S.endpoints(e)}
    assert (2.0, 0.0) in ends and (0.0, 2.0) in ends and (0.0, 0.0) not in ends                      # 角點被圓弧取代
    # 非 90° 角
    ents = S.assign_ids([S.line((0, 0), (10, 0)), S.line((0, 0), (5, 5 * math.sqrt(3)))])           # 60°
    arc = next(e for e in S.fillet_corner(ents, 0, 1, 1.0) if e["t"] == "arc")
    assert abs(S.span(arc) - 120) < 1e-5 and abs(arc["r"] - 1) < 1e-9


def test_chamfer_and_errors():
    out = S.chamfer_corner(corner(), 0, 1, 3.0)
    ln = [e for e in out if e["t"] == "line"]
    assert len(ln) == 3
    diag = next(e for e in ln if e["p1"][0] > 0 and e["p1"][1] == 0 and e["p2"][0] == 0 or sorted([e["p1"], e["p2"]]) == [[0.0, 3.0], [3.0, 0.0]])
    assert math.isclose(math.dist(diag["p1"], diag["p2"]), 3 * math.sqrt(2))
    with pytest.raises(ValueError):
        S.fillet_corner(corner(), 0, 1, 20)                           # 半徑超過線長
    with pytest.raises(ValueError):
        S.fillet_corner(S.assign_ids([S.line((0, 0), (1, 0)), S.line((5, 5), (6, 5))]), 0, 1, 0.1)    # 不相接
    with pytest.raises(ValueError):
        S.chamfer_corner(corner(), 0, 0, 1)
    with pytest.raises(ValueError):
        S.fillet_corner(corner(), 0, 1, 0)


def test_offset_loop_and_entities():
    rect = S.assign_ids(S.rectangle((0, 0), (20, 10)))
    out = S.offset_loop(rect, 0, 2.0)                                  # 向外 2
    xs = [p[0] for e in out for p in S.endpoints(e)]
    ys = [p[1] for e in out for p in S.endpoints(e)]
    assert min(xs) == pytest.approx(-2, abs=1e-6) and max(xs) == pytest.approx(22, abs=1e-6)
    assert min(ys) == pytest.approx(-2, abs=1e-6) and max(ys) == pytest.approx(12, abs=1e-6)
    inn = S.offset_loop(rect, 0, -2.0)
    assert max(p[0] for e in inn for p in S.endpoints(e)) == pytest.approx(18, abs=1e-6)
    c = S.offset_entity(S.circle((0, 0), 5), 2)
    assert c["r"] == 7
    assert S.offset_entity(S.line((0, 0), (10, 0)), 3)["p1"] == [0.0, 3.0]                # 往左側(+y)
    with pytest.raises(ValueError):
        S.offset_entity(S.circle((0, 0), 5), -6)
    with pytest.raises(ValueError):
        S.offset_loop(S.assign_ids([S.line((0, 0), (1, 0))]), 0, 1)                      # 不是封閉輪廓
    with pytest.raises(ValueError):
        S.offset_entity(S.ellipse((0, 0), 5, 3), 1)


def test_ellipse_and_spline_entities():
    e = S.ellipse((1, 2), 4, 6, 0)                                      # b > a:自動交換
    assert e["a"] == 6 and e["b"] == 4 and e["rot"] == 90.0
    with pytest.raises(ValueError):
        S.ellipse((0, 0), 0, 1)
    solid = S.extrude_solid([S.ellipse((0, 0), 10, 5, 30)], F.WORLD_PLANES["XY"], 2)
    assert abs(solid.Volume() - math.pi * 10 * 5 * 2) < 1e-6
    m = S.mirror_entity(S.ellipse((5, 0), 10, 5, 30), (0, 0), (0, 1))                   # 對 Y 軸鏡射
    assert m["c"] == [-5.0, 0.0] and abs(m["rot"] - 150) < 1e-9
    sp = S.spline([(0, 0), (5, 4), (10, 0)])
    assert S.endpoints(sp) == [[0.0, 0.0], [10.0, 0.0]] and len(S.sample(sp)) >= 36
    assert S.dist_point(sp, (5, 4)) < 1e-2
    # 樣條 + 直線形成封閉輪廓
    prof = S.profiles([sp, S.line((10, 0), (0, 0))])
    assert len(prof) == 1
    vol = S.extrude_solid([sp, S.line((10, 0), (0, 0))], F.WORLD_PLANES["XY"], 1).Volume()
    assert 20 < vol < 40
    path = S.path_wire([S.line((0, 0), (5, 0)), S.spline([(5, 0), (8, 3), (12, 3)])], F.WORLD_PLANES["XY"])
    assert path.Length() > 12
    # 修整對橢圓/樣條 = 整條刪除;求交不支援
    assert S.trim([e, S.line((0, 0), (1, 1))], 0, (0, 0)) == [S.line((0, 0), (1, 1))] or len(S.trim([e, S.line((0, 0), (1, 1))], 0, (0, 0))) == 1
    assert S.intersections(e, S.line((0, 0), (10, 0))) == []


def test_solver_passes_through_unsupported_entities():
    ents = S.assign_ids([S.line((0, 0), (9, 1)), S.ellipse((20, 20), 5, 3), S.spline([(0, 5), (3, 8), (6, 5)])])
    cons = [{"t": "horizontal", "refs": [[ents[0]["id"]]]}, {"t": "length", "refs": [[ents[0]["id"]]], "v": 10.0}]
    ok, out, dof, err = K.solve(ents, cons)
    assert ok and out[1] == ents[1] and out[2] == ents[2]
    assert abs(math.dist(out[0]["p1"], out[0]["p2"]) - 10) < 1e-6 and abs(out[0]["p1"][1] - out[0]["p2"][1]) < 1e-6
    assert K.solve([ents[1]], [])[0]


def test_construction_entities_are_not_profiles():
    rect = S.rectangle((0, 0), (10, 10))
    guide = S.circle((5, 5), 3)
    guide["construction"] = True
    assert len(S.profiles(rect + [guide])) == 1 and len(S.profiles(rect + [guide])[0][1]) == 0     # 構造圓不是孔
    vol = S.extrude_solid(rect + [guide], F.WORLD_PLANES["XY"], 2).Volume()
    assert abs(vol - 200) < 1e-6
    with pytest.raises(ValueError):
        S.local_faces([guide])
    with pytest.raises(ValueError):
        S.ordered_chain([guide])


def test_project_shape_edges():
    shape = cq.Workplane().box(20, 10, 6).faces(">Z").workplane().hole(4).val()
    top = {"origin": [0, 0, 3], "xdir": [1, 0, 0], "normal": [0, 0, 1]}
    ents = S.project_shape_edges(shape, top)
    kinds = [e["t"] for e in ents]
    assert kinds.count("line") == 4 and kinds.count("circle") == 1                       # 外框 4 邊 + 孔 1 圓(重複的底邊已去重)
    assert all(e["construction"] for e in ents)
    circ = next(e for e in ents if e["t"] == "circle")
    assert circ["r"] == 2.0 and circ["c"] == [0.0, 0.0]
    side = {"origin": [0, 0, 0], "xdir": [1, 0, 0], "normal": [0, -1, 0]}               # 前視平面
    s2 = S.project_shape_edges(shape, side, construction=False)
    assert not any("construction" in e for e in s2)
    assert len([e for e in s2 if e["t"] == "line"]) >= 4
