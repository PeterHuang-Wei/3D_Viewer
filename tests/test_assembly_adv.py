import numpy as np
import pytest

from core.model import Document
from core import assembly as A


def _doc2(a=(20, 20, 20), b=(10, 10, 10)):
    d = Document()
    d.add_feature("box", {"x": a[0], "y": a[1], "z": a[2]})
    d.add_feature("box", {"x": b[0], "y": b[1], "z": b[2]})
    return d


def _face(shape, normal):
    n = np.array(normal, float)
    best = max(range(len(shape.Faces())),
               key=lambda i: (np.dot([*shape.Faces()[i].normalAt().toTuple()], n)
                              if shape.Faces()[i].geomType() == "PLANE" else -9, shape.Faces()[i].Center().dot(__import__("cadquery").Vector(*n))))
    return best


def _n(shape, i):
    return np.array(shape.Faces()[i].normalAt().toTuple())


def test_parallel_perpendicular_angle_between_planes():
    d = _doc2()
    a, b = d.bodies
    fa, fb = _face(a.shape, (0, 0, 1)), _face(b.shape, (1, 0, 0))
    # 先把 b 繞 Y 轉 30° 讓它不平行
    d.add_feature("rotate", {"body": b.id, "x": 0, "y": 30, "z": 20, "c": True})
    b = d.bodies[1]
    fb = _face(b.shape, (0, 0, 1))
    assert d.add_feature("mate", {"fixed": a.id, "face_a": fa, "moving": b.id, "face_b": fb, "type": "平行"}) is None
    nb = _n(d.bodies[1].shape, fb)
    assert abs(abs(np.dot(nb, _n(a.shape, fa))) - 1) < 1e-6
    # 垂直
    assert d.add_feature("mate", {"fixed": a.id, "face_a": fa, "moving": b.id, "face_b": fb, "type": "垂直"}) is None
    assert abs(np.dot(_n(d.bodies[1].shape, fb), _n(a.shape, fa))) < 1e-6
    # 角度 60°(兩平面夾角)
    assert d.add_feature("mate", {"fixed": a.id, "face_a": fa, "moving": b.id, "face_b": fb, "type": "角度",
                                  "angle": 60}) is None
    cosn = float(np.dot(_n(d.bodies[1].shape, fb), _n(a.shape, fa)))
    assert np.degrees(np.arccos(cosn)) == pytest.approx(120, abs=1e-5)           # 法向夾角 = 180 − 60
    # 反向解:另一側
    d.add_feature("mate", {"fixed": a.id, "face_a": fa, "moving": b.id, "face_b": fb, "type": "角度",
                           "angle": 60, "flip": True})
    n1 = _n(d.bodies[1].shape, fb)
    assert np.degrees(np.arccos(float(np.dot(n1, _n(a.shape, fa))))) == pytest.approx(120, abs=1e-5)


def test_rotation_pivot_keeps_face_in_place():
    d = _doc2()
    a, b = d.bodies
    fb = _face(b.shape, (0, 0, 1))
    c0 = b.shape.Faces()[fb].Center()
    d.add_feature("mate", {"fixed": a.id, "face_a": _face(a.shape, (1, 0, 0)), "moving": b.id, "face_b": fb,
                           "type": "垂直"})
    c1 = d.bodies[1].shape.Faces()[fb].Center()
    assert (c1 - c0).Length < 1e-6                         # 繞所選面中心旋轉,該面位置不動


def test_distance_mate_planes():
    d = _doc2()
    a, b = d.bodies
    fa, fb = _face(a.shape, (0, 0, 1)), _face(b.shape, (0, 0, 1))
    assert d.add_feature("mate", {"fixed": a.id, "face_a": fa, "moving": b.id, "face_b": fb, "type": "距離",
                                  "offset": 7}) is None
    za = a.shape.BoundingBox().zmax
    bb = d.bodies[1].shape.BoundingBox()
    assert bb.zmin == pytest.approx(za + 7, abs=1e-6)       # 預設面對面,間距 7


def test_axis_parallel_and_distance_and_mixed():
    d = Document()
    d.add_feature("cylinder", {"r": 3, "h": 20})
    d.add_feature("cylinder", {"r": 2, "h": 20})
    a, b = d.bodies
    d.add_feature("rotate", {"body": b.id, "x": 0, "y": 40, "z": 0, "c": True})
    b = d.bodies[1]
    cf = lambda sh: next(i for i, f in enumerate(sh.Faces()) if f.geomType() == "CYLINDER")  # noqa: E731
    assert d.add_feature("mate", {"fixed": a.id, "face_a": cf(a.shape), "moving": b.id, "face_b": cf(b.shape),
                                  "type": "距離", "offset": 10}) is None
    ca, cb = d.bodies[0].shape.Center(), d.bodies[1].shape.Center()
    assert np.hypot(cb.x - ca.x, cb.y - ca.y) == pytest.approx(10, abs=1e-5)
    # 面-軸:軸線平行於平面(軸 ⟂ 法向)
    d2 = _doc2()
    cyl = Document()
    d2.add_feature("cylinder", {"r": 2, "h": 10})
    box, cy = d2.bodies[0], d2.bodies[2]
    assert d2.add_feature("mate", {"fixed": box.id, "face_a": _face(box.shape, (0, 0, 1)), "moving": cy.id,
                                   "face_b": cf(cy.shape), "type": "平行"}) is None
    ax = A.face_frame(d2.bodies[2].shape.Faces()[cf(cy.shape)])[2]
    assert abs(ax[2]) < 1e-6                                # 圓柱軸線水平
    assert d2.add_feature("mate", {"fixed": box.id, "face_a": 0, "moving": cy.id, "face_b": cf(cy.shape),
                                   "type": "距離"}) is not None   # 面 vs 軸 的距離不支援
    assert d2.add_feature("mate", {"fixed": box.id, "face_a": 0, "moving": cy.id, "face_b": cf(cy.shape),
                                   "type": "角度", "angle": 999}) is not None


def test_gui_mate_preview_ghost(monkeypatch):
    import os
    if not os.environ.get("DISPLAY"):
        pytest.skip("需要 X 顯示")
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from ui import main_window as mw
    from ui.dialogs import ParamDialog
    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow()
    w.show()
    d = w.doc
    d.add_feature("box", {"x": 20, "y": 20, "z": 20})
    d.add_feature("box", {"x": 10, "y": 10, "z": 10})
    w._update()
    a, b = d.bodies
    fa, fb = _face(a.shape, (0, 0, 1)), _face(b.shape, (0, 0, 1))
    seen = {}

    def fake_exec(self):
        names = [n for n in w.scene.plotter.renderer.actors if n == "ghost"]
        seen["initial"] = bool(names)
        self._w["offset"][1].setText("5")             # 改動欄位 -> 預覽更新
        seen["after"] = "ghost" in w.scene.plotter.renderer.actors
        self._w["type"][1].setCurrentText("角度")
        self._w["angle"][1].setText("999")             # 無效 -> 預覽清除
        seen["bad"] = "ghost" in w.scene.plotter.renderer.actors
        self._w["angle"][1].setText("45")
        return ParamDialog.Accepted

    monkeypatch.setattr(ParamDialog, "exec_", fake_exec)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    w._mate_moving = (b.id, fb)
    w.scene.sel_body, w.scene.sel_faces = 0, {fa}
    w.on_mate_apply()
    assert seen["initial"] and seen["after"] and not seen["bad"]
    assert "ghost" not in w.scene.plotter.renderer.actors          # 關閉後清除
    assert d.features[-1].kind == "mate" and d.features[-1].params["type"] == "角度"


def test_explode_and_groups_model():
    d = Document()
    for x in (10, 10, 10):
        d.add_feature("box", {"x": 10, "y": 10, "z": 10})
    ids = [b.id for b in d.bodies]
    d.add_feature("translate", {"body": ids[1], "x": 20, "y": 0, "z": 0})
    d.add_feature("translate", {"body": ids[2], "x": -20, "y": 0, "z": 0})
    assert d.explode is None and d.explode_offsets() == {}
    assert d.add_feature("explode", {"mode": "沿 X", "factor": 0.5}) is None
    off = d.explode_offsets()
    assert off[ids[1]][0] == pytest.approx(10) and off[ids[2]][0] == pytest.approx(-10)
    assert off[ids[0]] == pytest.approx((0, 0, 0)) and off[ids[1]][1] == 0
    assert d.add_feature("explode", {"mode": "放射", "factor": -1}) is not None
    assert d.add_feature("explode", {"mode": "亂", "factor": 1}) is not None
    d.add_feature("explode", {"mode": "放射", "factor": 0})
    assert d.explode is None
    # 群組
    assert d.add_feature("group", {"name": "邊", "bodies": f"{ids[1]}, {ids[2]}", "visible": True}) is None
    assert d.groups["邊"]["bodies"] == [ids[1], ids[2]]
    assert d.add_feature("group", {"name": "壞", "bodies": [999]}) is not None
    d.edit_feature(d.groups["邊"]["index"], {"visible": False})
    ap = d.appearance
    assert ap[ids[1]]["visible"] is False and ap[ids[2]]["visible"] is False and ids[0] not in ap
    d.undo()
    assert d.groups["邊"]["visible"] is True
    d.add_feature("group", {"name": "邊", "bodies": []})
    assert "邊" not in d.groups
    d.undo()
    d.delete_feature(0)                                          # 刪掉第一個方塊建立 -> 成員仍可解析
    assert isinstance(d.groups, dict)


def test_gui_explode_and_group_dock(monkeypatch):
    import os
    if not os.environ.get("DISPLAY"):
        pytest.skip("需要 X 顯示")
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    from ui import main_window as mw
    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow()
    w.show()
    for _ in range(2):
        w.doc.add_feature("box", {"x": 10, "y": 10, "z": 10})
    w.doc.add_feature("translate", {"body": w.doc.bodies[1].id, "x": 20, "y": 0, "z": 0})
    w._update()
    c0 = w.scene._meshes[1].center[0]
    w.doc.add_feature("explode", {"mode": "沿 X", "factor": 1.0})
    w._update(reset_camera=False)
    assert w.scene._meshes[1].center[0] > c0 + 5                 # 顯示網格被推開,幾何不變
    assert w.doc.bodies[1].shape.Center().x == pytest.approx(c0)
    w.doc.add_feature("group", {"name": "G", "bodies": [w.doc.bodies[1].id], "visible": True})
    w._update(reset_camera=False)
    assert w.group_list.count() == 1
    w.group_list.item(0).setCheckState(Qt.Unchecked)             # 取消勾選 -> 隱藏
    assert w.scene._meshes[1].n_cells == 0
    w.group_list.item(0).setCheckState(Qt.Checked)
    assert w.scene._meshes[1].n_cells > 0


def test_mcp_group_explode():
    from mcp_server.engine import Engine
    e = Engine()
    a = e.dispatch("create_primitive", {"kind": "box"})["new_bodies"][0]
    b = e.dispatch("create_primitive", {"kind": "box", "position": [30, 0, 0]})["new_bodies"][0]
    assert e.dispatch("set_explode", {"factor": 1, "mode": "沿 X"})["ok"]
    assert e.dispatch("create_group", {"name": "g", "bodies": [b]})["ok"]
    assert e.dispatch("show_group", {"name": "g", "visible": False})["ok"]
    assert e.dispatch("list_groups")["groups"]["g"]["visible"] is False
    assert not e.dispatch("show_group", {"name": "zz"})["ok"]
