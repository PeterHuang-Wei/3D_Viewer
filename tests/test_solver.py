import math
import pytest
from core import sketch2d as S
from core import sketch_solver as K


def rect():
    ents = S.assign_ids(S.rectangle((0, 0), (19, 11)))      # 故意不準的矩形
    ids = [e["id"] for e in ents]
    cons = [
        {"t": "coincident", "refs": [[ids[0], "p2"], [ids[1], "p1"]]},
        {"t": "coincident", "refs": [[ids[1], "p2"], [ids[2], "p1"]]},
        {"t": "coincident", "refs": [[ids[2], "p2"], [ids[3], "p1"]]},
        {"t": "coincident", "refs": [[ids[3], "p2"], [ids[0], "p1"]]},
        {"t": "horizontal", "refs": [[ids[0]]]}, {"t": "horizontal", "refs": [[ids[2]]]},
        {"t": "vertical", "refs": [[ids[1]]]}, {"t": "vertical", "refs": [[ids[3]]]},
    ]
    return ents, cons, ids


def test_rect_dimensions_and_dof():
    ents, cons, ids = rect()
    ok, out, dof, err = K.solve(ents, cons)
    assert ok and dof == 4                        # 矩形:平移 2 + 長 + 寬 = 4 自由度
    cons += [{"t": "length", "refs": [[ids[0]]], "v": 20.0}, {"t": "length", "refs": [[ids[1]]], "v": 10.0}]
    ok, out, dof, err = K.solve(ents, cons)
    assert ok and dof == 2                        # 還剩位置(平移)兩個自由度
    assert abs(math.hypot(*[a - b for a, b in zip(out[0]["p2"], out[0]["p1"])]) - 20) < 1e-6
    cons.append({"t": "fix", "refs": [[ids[0], "p1"]], "vals": [0.0, 0.0]})
    ok, out, dof, err = K.solve(ents, cons)
    assert ok and dof == 0
    assert [round(v, 6) for v in out[2]["p1"]] == [20.0, 10.0]


def test_conflict_and_redundant():
    ents, cons, ids = rect()
    bad = cons + [{"t": "length", "refs": [[ids[0]]], "v": 10.0}, {"t": "length", "refs": [[ids[0]]], "v": 20.0}]
    ok, out, dof, err = K.solve(ents, bad)
    assert not ok and out is ents
    red = cons + [{"t": "horizontal", "refs": [[ids[0]]]}]       # 重複拘束仍可解
    assert K.solve(ents, red)[0]


def test_circle_tangent_equal_concentric():
    ents = S.assign_ids([S.line((0, 3), (10, 3.5)), S.circle((5, 0), 2.5), S.circle((5.2, 0.1), 4)])
    l, c1, c2 = (e["id"] for e in ents)
    cons = [{"t": "tangent", "refs": [[l], [c1]]}, {"t": "diameter", "refs": [[c1]], "v": 6.0},
            {"t": "concentric", "refs": [[c1], [c2]]}, {"t": "equal", "refs": [[c1], [c2]]},
            {"t": "horizontal", "refs": [[l]]}]
    ok, out, dof, err = K.solve(ents, cons)
    assert ok
    assert abs(out[1]["r"] - 3) < 1e-6 and abs(out[2]["r"] - 3) < 1e-6 and math.dist(out[1]["c"], out[2]["c"]) < 1e-9
    assert abs(abs(out[0]["p1"][1] - out[1]["c"][1]) - 3) < 1e-6   # 水平線與圓相切


def test_parallel_perp_angle_midpoint_pointon():
    ents = S.assign_ids([S.line((0, 0), (10, 1)), S.line((0, 5), (9, 8)), S.line((2, 0), (3, 6)),
                         S.line((5, -4), (6, -3))])
    a, b, c, d = (e["id"] for e in ents)
    cons = [{"t": "horizontal", "refs": [[a]]}, {"t": "parallel", "refs": [[a], [b]]},
            {"t": "perpendicular", "refs": [[a], [c]]},
            {"t": "angle", "refs": [[a], [d]], "v": 45.0},
            {"t": "midpoint", "refs": [[d, "p1"], [a]]},
            {"t": "point_on", "refs": [[c, "p1"], [a]]}]
    ok, out, dof, err = K.solve(ents, cons)
    assert ok
    assert abs(out[0]["p1"][1] - out[0]["p2"][1]) < 1e-6
    assert abs(out[1]["p1"][1] - out[1]["p2"][1]) < 1e-6
    assert abs(out[2]["p1"][0] - out[2]["p2"][0]) < 1e-6
    mid = [(out[0]["p1"][i] + out[0]["p2"][i]) / 2 for i in (0, 1)]
    assert all(abs(out[3]["p1"][i] - mid[i]) < 1e-6 for i in (0, 1))
    d1 = [out[0]["p2"][i] - out[0]["p1"][i] for i in (0, 1)]
    d2 = [out[3]["p2"][i] - out[3]["p1"][i] for i in (0, 1)]
    ang = math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
    assert abs(ang - 45) < 1e-6


def test_arc_constraints_and_measure():
    ents = S.assign_ids([S.arc((0, 0), 5, 0, 90), S.line((5, 0), (9, 0))])
    arc, ln = ents[0]["id"], ents[1]["id"]
    cons = [{"t": "coincident", "refs": [[arc, "s"], [ln, "p1"]]}, {"t": "radius", "refs": [[arc]], "v": 7.0}]
    ok, out, dof, err = K.solve(ents, cons)
    assert ok and abs(out[0]["r"] - 7) < 1e-6
    assert abs(K.measure(out, {"t": "radius", "refs": [[arc]]}) - 7) < 1e-6
    assert abs(K.measure(ents, {"t": "length", "refs": [[ln]]}) - 4) < 1e-9
    assert abs(K.measure(ents, {"t": "distance", "refs": [[ln, "p1"], [ln, "p2"]]}) - 4) < 1e-9


def test_prune_and_ids():
    ents = S.assign_ids([S.line((0, 0), (1, 0)), S.line((1, 0), (1, 1))])
    cons = [{"t": "coincident", "refs": [[ents[0]["id"], "p2"], [ents[1]["id"], "p1"]]}]
    assert K.prune(ents[:1], cons) == []
    m = S.mirror_entity(ents[0], (0, 0), (0, 1))
    assert "id" not in m                                      # 複製的圖元不帶舊編號
