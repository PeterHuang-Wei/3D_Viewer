import pytest

from core.model import Document


def _sketch(doc, ents, plane="XY"):
    from core import features as F, sketch2d as SK
    assert doc.add_feature("sketch", {"entities": SK.assign_ids(ents), "wp": F.WORLD_PLANES[plane], "constraints": []}) is None
    return doc.sketches[-1][0]


def test_surface_pipeline_extrude_offset_thicken():
    from core import sketch2d as SK
    d = Document()
    sid = _sketch(d, [SK.line((0, 0), (10, 0)), SK.arc((10, 5), 5, 270, 90)])
    assert d.add_feature("surface_extrude", {"sketch": sid, "depth": 8}) is None
    b = d.bodies[0]
    assert not b.shape.Solids() and b.shape.Area() == pytest.approx(205.66, abs=0.05)
    assert d.add_feature("surface_offset", {"body": b.id, "faces": [0], "distance": 3}) is None
    assert len(d.bodies) == 2
    assert d.add_feature("thicken", {"body": b.id, "thickness": 2, "mode": "對稱"}) is None
    assert d.bodies[0].shape.Solids() and d.bodies[0].shape.Volume() > 300
    # 已是實體不可再加厚;實體不可圓角以外的曲面操作
    assert "曲面" in d.add_feature("thicken", {"body": b.id, "thickness": 1})
    assert d.add_feature("thicken", {"body": d.bodies[1].id, "thickness": 0}) is not None


def test_surface_trim_and_knit_closed_solid():
    from core import sketch2d as SK
    d = Document()
    sid = _sketch(d, [SK.line((-20, 0), (20, 0))])
    assert d.add_feature("surface_extrude", {"sketch": sid, "depth": 40, "sym": True}) is None
    s = d.bodies[0]
    area = s.shape.Area()
    assert area == pytest.approx(1600)
    assert d.add_feature("surface_trim", {"body": s.id, "plane": "YZ", "offset": 0, "tool": 0, "keep": "正側"}) is None
    assert d.bodies[0].shape.Area() == pytest.approx(800)
    assert d.add_feature("surface_trim", {"body": s.id, "plane": "YZ", "offset": 100, "tool": 0, "keep": "正側"}) is not None
    # 6 個面縫成封閉 -> 實體
    d2 = Document()
    d2.add_feature("box", {"x": 10, "y": 10, "z": 10})
    box = d2.bodies[0].shape
    d3 = Document()
    from core.ops import SURFACE_KINDS
    assert "surface_knit" in SURFACE_KINDS
    import cadquery as cq
    from core import surface as SF
    k = SF.knit([cq.Compound.makeCompound(box.Faces()[:3]), cq.Compound.makeCompound(box.Faces()[3:])])
    assert k.Solids() and k.Volume() == pytest.approx(1000)
    k2 = SF.knit([cq.Compound.makeCompound(box.Faces()[:5])])
    assert not k2.Solids()                                      # 缺一面 -> 仍是殼
    # 經由特徵:兩個曲面體縫合
    d3.add_feature("box", {"x": 10, "y": 10, "z": 10})
    assert d3.add_feature("surface_knit", {"bodies": "99", "tol": 0.001}) is not None


def test_trim_by_surface_body_and_solid_ops_guard():
    import cadquery as cq
    from core import surface as SF
    big = cq.Face.makePlane(40, 40, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
    cut = cq.Face.makePlane(100, 100, cq.Vector(0, 0, 0), cq.Vector(1, 0, 0))
    assert SF.trim_by_tool(big, cut, "正側").Area() == pytest.approx(800)
    assert SF.trim_by_tool(big, cut, "負側").Area() == pytest.approx(800)
    with pytest.raises(ValueError):
        SF.trim_by_tool(big, cq.Face.makePlane(5, 5, cq.Vector(0, 0, 50), cq.Vector(1, 0, 0)), "正側")
    # 曲面體不能圓角 / 抽殼
    d4 = Document()
    from core import sketch2d as SK
    sid = _sketch(d4, [SK.line((0, 0), (10, 0))])
    d4.add_feature("surface_extrude", {"sketch": sid, "depth": 5})
    assert d4.add_feature("fillet", {"body": d4.bodies[0].id, "edges": [0], "r": 1}) is not None


def test_mcp_surface_and_guard():
    from mcp_server.engine import Engine
    e = Engine()
    sk = e.dispatch("create_sketch", {"plane": "XY", "entities": [{"t": "line", "p1": [0, 0], "p2": [10, 0]},
                                                                  {"t": "line", "p1": [10, 0], "p2": [10, 10]}]})
    r = e.dispatch("add_feature", {"kind": "surface_extrude", "params": {"sketch": sk["new_ids"][0], "depth": 5}})
    assert r["ok"], r
    sid = r["new_bodies"][0]
    st = e.dispatch("get_state")
    assert st["bodies"][0]["type"] == "surface" and st["bodies"][0]["volume"] == 0
    assert not e.dispatch("measure", {"kind": "mass"})["ok"]                      # 只有曲面 -> 沒有質量
    assert e.dispatch("add_feature", {"kind": "thicken", "params": {"body": sid, "thickness": 1}})["ok"]
    assert e.dispatch("get_state")["bodies"][0]["type"] == "solid"


import os


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="需要 X 顯示")
def test_gui_surface_menu(monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from ui import main_window as mw
    from core import sketch2d as SK
    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow()
    w.show()
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    sid = _sketch(w.doc, [SK.line((0, 0), (10, 0)), SK.line((10, 0), (10, 10))])
    w._update()
    answers = {"曲面拉伸": {"depth": 6, "sym": False, "flip": False}, "曲面加厚": {"thickness": 1.5, "mode": "單側"},
               "縫合曲面": {"tol": 0.001, "keep": True}}
    monkeypatch.setattr(mw, "ask", lambda title, fields, parent, initial=None, **k: {**{f[0]: f[3] for f in fields},
                                                                                      **(initial or {}), **answers[title]})
    w.on_surface_extrude()
    assert len(w.doc.bodies) == 1 and not w.doc.bodies[0].shape.Solids()
    w.on_surface_knit()                                                  # 兩片以上才有意義,單片也應成功
    assert len(w.doc.bodies) == 2
    w.tree.setCurrentRow(0)
    w._surface_modify("thicken")
    assert w.doc.bodies[0].shape.Solids()
