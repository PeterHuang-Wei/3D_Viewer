import cadquery as cq
import pytest

from core.model import Document


def _box_doc(x, y, z):
    d = Document()
    d.add_feature("box", {"x": x, "y": y, "z": z})
    return d


def _face_idx(shape, normal, pick=max):
    """取法向約等於 normal 的面,依 normal 方向座標挑最前者。"""
    n = cq.Vector(*normal)
    cands = [(i, f.Center().dot(n)) for i, f in enumerate(shape.Faces())
             if f.geomType() == "PLANE" and f.normalAt().dot(n) > 0.99]
    return pick(cands, key=lambda t: t[1])[0]


def test_insert_part_and_plane_mate(tmp_path):
    part = _box_doc(10, 10, 5)
    part.save_project(str(tmp_path / "p.v3d"))
    doc = Document()
    assert doc.add_feature("box", {"x": 40, "y": 40, "z": 10}) is None
    err = doc.add_feature("insert", {"project": part.to_data(), "source": "p.v3d", "x": 100, "y": 0, "z": 0})
    assert err is None and len(doc.bodies) == 2
    base, ins = doc.bodies
    assert ins.shape.BoundingBox().xmin == pytest.approx(95)
    # 零件底面(-Z)貼到底座頂面(+Z),offset 0
    fa = _face_idx(base.shape, (0, 0, 1))
    fb = _face_idx(ins.shape, (0, 0, -1), pick=min)
    assert doc.add_feature("mate", {"fixed": base.id, "face_a": fa, "moving": ins.id, "face_b": fb,
                                    "type": "面貼合", "offset": 0, "flip": False}) is None
    bb = doc.bodies[1].shape.BoundingBox()
    top = base.shape.BoundingBox().zmax
    assert bb.zmin == pytest.approx(top, abs=1e-6) and bb.zmax == pytest.approx(top + 5, abs=1e-6)
    assert bb.xmin == pytest.approx(95)                     # 面內位置不被改動


def test_plane_mate_rotates_and_offset():
    doc = Document()
    doc.add_feature("box", {"x": 20, "y": 20, "z": 20})
    doc.add_feature("box", {"x": 6, "y": 6, "z": 3})
    a, b = doc.bodies
    fa = _face_idx(a.shape, (0, 0, 1))
    fb = _face_idx(b.shape, (0, 0, 1))                       # 頂面對頂面 -> 需翻轉 180°
    assert doc.add_feature("mate", {"fixed": a.id, "face_a": fa, "moving": b.id, "face_b": fb,
                                    "type": "面貼合", "offset": 2.5, "flip": False}) is None
    bb = doc.bodies[1].shape.BoundingBox()
    top = a.shape.BoundingBox().zmax
    assert bb.zmin == pytest.approx(top + 2.5, abs=1e-6) and bb.zmax == pytest.approx(top + 5.5, abs=1e-6)


def test_concentric_pin_in_hole():
    doc = Document()
    doc.add_feature("box", {"x": 30, "y": 30, "z": 10})
    doc.add_feature("cylinder", {"r": 3, "h": 20})
    plate, pin = doc.bodies
    # 板上挖孔 R4 於 (20,10)
    doc.add_feature("cylinder", {"r": 4, "h": 10})
    tool = doc.bodies[2]
    doc.add_feature("translate", {"body": tool.id, "x": 5, "y": 3, "z": 0})
    doc.add_feature("boolean", {"op": "差集", "target": plate.id, "tool": tool.id, "keep": False})
    plate = doc.bodies[0]
    pin = next(b for b in doc.bodies if b.id != plate.id)
    cf = lambda sh: next(i for i, f in enumerate(sh.Faces()) if f.geomType() == "CYLINDER")  # noqa: E731
    err = doc.add_feature("mate", {"fixed": plate.id, "face_a": cf(plate.shape), "moving": pin.id,
                                   "face_b": cf(pin.shape), "type": "同軸", "offset": 0, "flip": False})
    assert err is None
    c = doc.bodies[1].shape.Center()
    hc = tool.shape.Center()
    z0 = pin.shape.BoundingBox().zmin
    assert (c.x, c.y) == pytest.approx((hc.x + 5, hc.y + 3), abs=1e-6)
    assert doc.bodies[1].shape.BoundingBox().zmin == pytest.approx(z0, abs=1e-6)   # 軸向位置不變


def test_mate_errors_and_edit():
    doc = Document()
    doc.add_feature("box", {"x": 10, "y": 10, "z": 10})
    doc.add_feature("box", {"x": 10, "y": 10, "z": 10})
    a, b = doc.bodies
    assert "不可相同" in doc.add_feature("mate", {"fixed": a.id, "face_a": 0, "moving": a.id, "face_b": 1,
                                                  "type": "面貼合"})
    assert "圓柱" in doc.add_feature("mate", {"fixed": a.id, "face_a": 0, "moving": b.id, "face_b": 1, "type": "同軸"})
    assert doc.add_feature("mate", {"fixed": a.id, "face_a": 99, "moving": b.id, "face_b": 1, "type": "面貼合"})


def test_gui_insert_and_mate(tmp_path, monkeypatch):
    import os
    if not os.environ.get("DISPLAY"):
        pytest.skip("需要 X 顯示")
    from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox
    from ui import main_window as mw
    app = QApplication.instance() or QApplication([])
    part = _box_doc(10, 10, 5)
    pth = str(tmp_path / "part.v3d")
    part.save_project(pth)
    w = mw.MainWindow()
    w.show()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2])))
    w.doc.add_feature("box", {"x": 40, "y": 40, "z": 10})
    w._update()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (pth, ""))
    monkeypatch.setattr(mw, "ask", lambda title, fields, parent, **k: {f[0]: f[3] if f[2] != "combo" else f[3][0]
                                                                         for f in fields} | ({"x": 100} if title == "插入零件" else {}))
    w.on_insert_part()
    from ui.dialogs import ParamDialog
    monkeypatch.setattr(ParamDialog, "exec_", lambda self: ParamDialog.Accepted)      # 配合對話框直接接受預設值
    assert len(w.doc.bodies) == 2
    base, ins = w.doc.bodies
    # 步驟 1:零件底面;步驟 2:底座頂面
    w.scene.sel_body, w.scene.sel_faces = 1, {_face_idx(ins.shape, (0, 0, -1), pick=min)}
    w.on_mate_pick_moving()
    w.scene.sel_body, w.scene.sel_faces = 0, {_face_idx(base.shape, (0, 0, 1))}
    w.on_mate_apply()
    bb = w.doc.bodies[1].shape.BoundingBox()
    assert bb.zmin == pytest.approx(base.shape.BoundingBox().zmax, abs=1e-6)
    # 未記錄移動面時提示(information 被攔截成 AssertionError)
    with pytest.raises(AssertionError):
        w.on_mate_apply()
