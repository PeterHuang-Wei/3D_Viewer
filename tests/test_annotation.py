import math
import pytest
from core import measure as MS
from core.model import Document


def make():
    d = Document()
    d.add_feature("box", {"x": 40, "y": 30, "z": 20})
    d.add_feature("cylinder", {"r": 6, "h": 40})
    d.add_feature("boolean", {"op": "差集", "target": 1, "tool": 2, "keep": False})
    return d


def hole_edge(d):
    shape = d.bodies[0].shape
    i = next(i for i, e in enumerate(shape.Edges()) if e.geomType() == "CIRCLE" and abs(e.Center().z - 10) < 1e-6)
    j = next(j for j, f in enumerate(shape.Faces()) if f.geomType() == "CYLINDER")
    return i, j


def test_geometry_edge_and_face():
    d = make()
    i, j = hole_edge(d)
    g = MS.circular_geometry(d.bodies[0].shape, "edge", i, (6, 0, 10))
    assert abs(g["radius"] - 6) < 1e-9 and abs(g["center"][2] - 10) < 1e-9 and abs(abs(g["normal"][2]) - 1) < 1e-9
    assert abs(g["dir"][0] - 1) < 1e-9
    g2 = MS.circular_geometry(d.bodies[0].shape, "face", j, (0, 6, 3))      # 圓柱面,取在 z=3 的剖面
    assert abs(g2["radius"] - 6) < 1e-9 and abs(g2["center"][2] - 3) < 1e-9 and abs(g2["dir"][1] - 1) < 1e-9
    with pytest.raises(ValueError):
        MS.circular_geometry(d.bodies[0].shape, "face", next(k for k, f in enumerate(d.bodies[0].shape.Faces()) if f.geomType() == "PLANE"), (0, 0, 0))


def test_annotation_geometry_text():
    ann = {"center": (0, 0, 0), "radius": 6.0, "normal": (0, 0, 1), "dir": (1, 0, 0), "mode": "直徑"}
    lines, text, pos = MS.annotation_geometry(ann)
    assert text == "Ø12" and abs(lines[0][0][0] + 6) < 1e-9 and abs(lines[0][1][0] - 6) < 1e-9
    lines, text, pos = MS.annotation_geometry({**ann, "mode": "半徑"})
    assert text == "R6" and abs(lines[0][0][0]) < 1e-9


def test_annotation_feature_follows_geometry_and_fails_safely():
    d = make()
    i, j = hole_edge(d)
    bid = d.bodies[0].id
    assert d.add_feature("annotation", {"body": bid, "kind": "edge", "index": i, "mode": "直徑", "at": [6, 0, 10]}) is None
    assert len(d.annotations) == 1 and abs(d.annotations[0][2]["radius"] - 6) < 1e-9
    assert len(d.bodies) == 1                              # 標註不是實體
    assert d.edit_feature(1, {"r": 8}) is None             # 改圓柱半徑:孔變大 -> 標註自動更新
    assert abs(d.annotations[0][2]["radius"] - 8) < 1e-9
    assert d.edit_feature(3, {"mode": "半徑"}) is None and d.annotations[0][1].startswith("半徑")
    err = d.add_feature("annotation", {"body": bid, "kind": "face", "index": 0, "mode": "半徑", "at": [0, 0, 0]})
    assert err and len(d.annotations) == 1                 # 非圓柱面 -> 拒絕並還原


def test_annotation_saved_in_project(tmp_path):
    d = make()
    i, _ = hole_edge(d)
    d.add_feature("annotation", {"body": d.bodies[0].id, "kind": "edge", "index": i, "mode": "半徑", "at": [6, 0, 10]})
    p = str(tmp_path / "a.v3d")
    d.save_project(p)
    e = Document()
    e.load_project(p)
    assert len(e.annotations) == 1 and abs(e.annotations[0][2]["radius"] - 6) < 1e-9
