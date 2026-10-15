import os

import cadquery as cq
import numpy as np
import pytest

from core import printprep as PP
from core.model import Document


def _tee():
    bar = cq.Workplane("XY").box(30, 10, 4, centered=(True, True, False)).translate((0, 0, 10))
    stem = cq.Workplane("XY").box(6, 10, 10, centered=(True, True, False))
    return bar.union(stem).val()


def test_check_mesh_cases(tmp_path):
    box = cq.Solid.makeBox(10, 10, 10)
    r = PP.check_shape(box)
    assert r["ok"] and r["watertight"] and r["shells"] == 1 and r["volume"] == pytest.approx(1000)
    V, T = PP.weld(*PP.shape_mesh(box))
    r2 = PP.check_mesh(V, T[:-1])                                   # 少一個三角形 -> 開放
    assert not r2["watertight"] and r2["boundary_edges"] == 3 and not r2["ok"]
    r3 = PP.check_mesh(V, T[:, ::-1])                               # 全部反向
    assert r3["inverted"] and any("朝內" in i for i in r3["issues"])
    Tm = T.copy()
    Tm[0] = Tm[0][::-1]                                             # 單個三角形反向 -> 法向不一致
    assert PP.check_mesh(V, Tm)["inconsistent_edges"] > 0
    Vd = np.vstack([V, V[:1]])
    Td = np.vstack([T, [[0, 0, len(V)]]])                           # 退化三角形
    assert PP.check_mesh(Vd, Td)["degenerate"] >= 1
    two = cq.Compound.makeCompound([box, cq.Solid.makeBox(5, 5, 5).moved(cq.Location(cq.Vector(30, 0, 0)))])
    assert PP.check_shape(two)["shells"] == 2
    big = cq.Solid.makeBox(300, 300, 300)
    rb = PP.check_shape(big)
    assert not rb["fits_bed"] and not rb["ok"]
    assert PP.check_shape(cq.Solid.makeBox(250, 100, 100))["fits_bed"]           # 轉個方向放得下
    with pytest.raises(ValueError):
        PP.check_shape(cq.Face.makePlane(5, 5))


def test_stl_roundtrip_check(tmp_path):
    box = cq.Solid.makeBox(10, 10, 10)
    p = str(tmp_path / "b.stl")
    box.exportStl(p, 0.01, 0.1, False, relative=False)               # 二進位
    r = PP.check_mesh(*PP.read_stl(p))
    assert r["ok"] and r["triangles"] == 12 and r["volume"] == pytest.approx(1000)
    pa = str(tmp_path / "a.stl")
    box.exportStl(pa, 0.01, 0.1, True, relative=False)               # ASCII
    assert PP.check_mesh(*PP.read_stl(pa))["ok"]
    bad = tmp_path / "bad.stl"
    bad.write_text("hello")
    with pytest.raises(ValueError):
        PP.read_stl(str(bad))


def test_support_estimate_matches_analytic():
    V, T = PP.shape_mesh(_tee())
    e = PP.support_estimate(V, T)
    assert e["overhang_area"] == pytest.approx(240)                  # 橫桿兩側底面 2×(12×10)
    assert e["support_volume"] == pytest.approx(240 * (10 - 0.2) * 0.15, rel=1e-6)
    assert e["height"] == pytest.approx(14) and e["base_area"] == pytest.approx(60)
    assert PP.support_estimate(V, T, support_type="樹狀")["support_volume"] == pytest.approx(e["support_volume"] * 0.5)
    assert PP.support_estimate(V, T, threshold=89)["overhang_area"] == pytest.approx(240)
    box_est = PP.support_estimate(*PP.shape_mesh(cq.Solid.makeBox(10, 10, 10)))
    assert box_est["overhang_area"] == 0 and box_est["support_volume"] == 0
    with pytest.raises(ValueError):
        PP.support_estimate(V, T, support_type="亂")


def test_support_scope_platform_only_when_overhang_over_model():
    base = cq.Workplane("XY").box(20, 20, 5, centered=(True, True, False))
    cap = cq.Workplane("XY").box(10, 10, 3, centered=(True, True, False)).translate((0, 0, 8)).union(
        cq.Workplane("XY").box(4, 4, 3, centered=(True, True, False)).translate((0, 0, 5)))
    shape = base.union(cap).val()               # 底座上方 5~8 為小柱,8~11 為較寬的帽(其下方是底座頂面)
    V, T = PP.shape_mesh(shape)
    all_ = PP.support_estimate(V, T, scope="全部")
    plat = PP.support_estimate(V, T, scope="僅平台")
    assert all_["support_volume"] > 0 and plat["support_volume"] == 0
    assert plat["unsupportable_area"] > 0


def test_orientation_prefers_less_support():
    V, T = PP.shape_mesh(_tee())
    rows = PP.analyze_orientations(V, T)
    orig = next(r for r in rows if r["name"] == "原方向") if any(r["name"] == "原方向" for r in rows) else None
    assert rows[0]["support_volume"] < 1e-6                           # 橫放(側躺)不需支撐
    if orig:
        assert rows[0]["cost"] <= orig["cost"]
    assert [r["cost"] for r in rows] == sorted(r["cost"] for r in rows)
    ax, ang = PP.axis_angle_from_matrix(rows[0]["rotation"])
    rot = PP.orient_shape(_tee(), ax, ang)
    assert rot.BoundingBox().zmin == pytest.approx(0, abs=1e-6)
    est = PP.support_estimate(*PP.shape_mesh(rot))
    assert est["support_volume"] == pytest.approx(rows[0]["support_volume"], abs=1e-3)


def test_rotation_helpers():
    for n in ((0, 0, 1), (1, 0, 0), (0, -1, 0), (1, 1, 1), (0, 0, -1)):
        ax, ang = PP.rotation_to_down(n)
        R = PP._rot_matrix(ax, ang)
        assert np.allclose(R @ (np.array(n) / np.linalg.norm(n)), [0, 0, -1], atol=1e-9)
        ax2, ang2 = PP.axis_angle_from_matrix(R)
        assert np.allclose(PP._rot_matrix(ax2, ang2), R, atol=1e-9)


def test_build_supports_and_features():
    d = Document()
    d.add_feature("box", {"x": 30, "y": 10, "z": 4})
    # 用 T 形:建立兩個方塊並聯集
    d.add_feature("box", {"x": 6, "y": 10, "z": 10})
    a, b = d.bodies
    d.add_feature("translate", {"body": a.id, "x": 0, "y": 0, "z": 15})
    d.add_feature("translate", {"body": b.id, "x": 0, "y": 0, "z": 8})
    d.add_feature("boolean", {"op": "聯集", "target": a.id, "tool": b.id, "keep": False})
    t = d.bodies[0]
    assert d.bodies[0].shape.BoundingBox().zmin == pytest.approx(3)
    assert d.add_feature("supports", {"body": t.id}) is not None            # 尚未落地 -> 提示
    assert d.add_feature("orient", {"body": t.id, "axis": [0, 0, 1], "angle": 0, "ground": True}) is None
    assert d.bodies[0].shape.BoundingBox().zmin == pytest.approx(0, abs=1e-6)
    assert d.add_feature("supports", {"body": t.id, "spacing": 4}) is None
    sup = d.bodies[1]
    assert sup.name.startswith("支撐") and len(sup.shape.Solids()) > 5
    bb, tb = sup.shape.BoundingBox(), d.bodies[0].shape.BoundingBox()
    assert bb.zmin == pytest.approx(0, abs=1e-6) and bb.zmax < tb.zmax and bb.zmax > 8
    # 支撐不碰到模型(留間隙)
    assert d.bodies[0].shape.intersect(sup.shape).Volume() < 1e-6
    for ty in ("線狀", "樹狀"):
        assert d.add_feature("supports", {"body": t.id, "type": ty, "spacing": 4}) is None
    assert d.add_feature("supports", {"body": t.id, "spacing": 0.5, "thickness": 1}) is not None
    assert d.add_feature("supports", {"body": t.id, "scope": "僅平台"}) is None


def test_mcp_print_tools(tmp_path):
    from mcp_server.engine import Engine
    e = Engine()
    r = e.dispatch("create_primitive", {"kind": "box", "params": {"x": 30, "y": 10, "z": 4}, "position": [0, 0, 12]})
    a = r["new_bodies"][0]
    b = e.dispatch("create_primitive", {"kind": "box", "params": {"x": 6, "y": 10, "z": 10}, "position": [0, 0, 5]})["new_bodies"][0]
    assert e.dispatch("add_feature", {"kind": "boolean", "params": {"op": "聯集", "target": a, "tool": b, "keep": False}})["ok"]
    chk = e.dispatch("print_check", {"body": a})
    assert chk["ok"] and chk["passed"] and chk["watertight"]
    sup = e.dispatch("print_support", {"body": a})
    assert sup["ok"] and sup["overhang_area"] == pytest.approx(240)
    o = e.dispatch("print_orient", {"body": a})
    assert o["ok"] and o["candidates"][0]["rank"] == 0
    assert not e.dispatch("print_orient", {"body": a, "apply": 99})["ok"]
    assert e.dispatch("print_orient", {"body": a, "apply": 0})["applied"]
    assert e.dispatch("print_support", {"body": a})["support_volume"] < 1e-6
    stl = tmp_path / "x.stl"
    e.dispatch("export_stl", {"path": str(stl)})
    assert e.dispatch("print_check", {"path": str(stl)})["passed"]
    assert not e.dispatch("print_check", {})["ok"]
    assert not e.dispatch("print_check", {"path": "/nope.stl"})["ok"]
    # 側躺後不需要支撐 -> 沒有可產生的支撐;還原到直立再產生
    assert not e.dispatch("build_supports", {"body": a})["ok"]


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="需要 X 顯示")
def test_gui_print_menu(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QApplication, QInputDialog, QMessageBox, QFileDialog
    from ui import main_window as mw
    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow()
    w.show()
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append("W:" + a[2]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    monkeypatch.setattr(mw, "ask", lambda title, fields, parent, initial=None, **k: {**{f[0]: (f[3][0] if f[2] == "combo" else f[3]) for f in fields}, **(initial or {})})
    d = w.doc
    d.add_feature("box", {"x": 30, "y": 10, "z": 4})
    d.add_feature("box", {"x": 6, "y": 10, "z": 10})
    a, b = d.bodies
    d.add_feature("translate", {"body": a.id, "x": 0, "y": 0, "z": 12})
    d.add_feature("translate", {"body": b.id, "x": 0, "y": 0, "z": 5})
    d.add_feature("boolean", {"op": "聯集", "target": a.id, "tool": b.id, "keep": False})
    w._update()
    w.tree.setCurrentRow(0)
    w.on_print_check()
    assert "全部通過" in shown[-1]
    w.on_print_support()
    assert "懸伸面積" in shown[-1] and any(it.get("mesh") is not None for it in w.scene.measure.items)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: (a[3][0], True))
    w.on_print_orient()
    assert d.features[-1].kind == "orient" and d.bodies[0].shape.BoundingBox().zmin == pytest.approx(0, abs=1e-6)
    stl = str(tmp_path / "t.stl")
    d.export_stl(stl)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (stl, ""))
    w.on_print_check_stl()
    assert "全部通過" in shown[-1]
