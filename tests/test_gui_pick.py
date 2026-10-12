"""以真實視窗(需 OpenGL,例如 xvfb)模擬滑鼠點選;無 OpenGL 環境自動略過。"""
import os
import time

import pytest

pytest.importorskip("PyQt5")
if not os.environ.get("DISPLAY"):
    pytest.skip("需要 X 顯示(例如 xvfb-run)", allow_module_level=True)

from PyQt5.QtCore import Qt, QPoint  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from ui.main_window import MainWindow  # noqa: E402


def test_click_selects_face():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.doc.add_feature("box", {"x": 20, "y": 20, "z": 20})
    w._update()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    pl, r = w.scene.plotter, w.scene.plotter.renderer
    w.scene.set_view("等角視")
    pl.render()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    r.SetWorldPoint(0, 0, 10, 1.0)
    r.WorldToDisplay()
    x, y, _ = r.GetDisplayPoint()
    w.on_mode("face")
    QTest.mouseClick(pl, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(pl.height() - y)))
    app.processEvents()
    assert len(w.scene.sel_faces) == 1
    face = w.doc.bodies[0].shape.Faces()[next(iter(w.scene.sel_faces))]
    assert abs(face.Center().z - 10) < 1e-6


def test_sketch_drawing_and_cut():
    """在鎖定平面上以滑鼠畫矩形、圓、修整,完成草圖後拉伸切除。"""
    import math
    from core import sketch2d as S
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.doc.add_feature("box", {"x": 40, "y": 40, "z": 10})
    w._update()
    w._set_lock({"origin": [0, 0, 5], "xdir": [1, 0, 0], "normal": [0, 0, 1]})

    def pump(n=10):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    pump(30)
    w.on_new_sketch()
    ed, pl = w._sk["ed"], w.scene.plotter
    pump(10)

    def click(u, v):
        P = ed.to3d((u, v))
        r = pl.renderer
        r.SetWorldPoint(*P, 1.0)
        r.WorldToDisplay()
        x, y, _ = r.GetDisplayPoint()
        pt = QPoint(int(round(x)), int(round(pl.height() - y)))
        QTest.mouseMove(pl, pt)
        pump(3)
        QTest.mouseClick(pl, Qt.LeftButton, Qt.NoModifier, pt)
        pump(4)

    ed.set_tool("rect")
    click(-10, -10)
    click(10, 10)
    ed.set_tool("circle")
    click(0, 0)
    click(4, 0)
    assert [e["t"] for e in ed.entities] == ["line"] * 4 + ["circle"]
    assert abs(ed.entities[-1]["r"] - 4) < 1e-6
    ed.set_tool("line")
    click(-10, 0)
    click(10, 0)
    ed.cancel_op()
    ed.set_tool("trim")
    n = len(ed.entities)
    click(7, 0)              # 修整 y=0 橫線在圓與右邊框之間的那一段
    assert len(ed.entities) == n + 1          # 橫線被圓與右邊框切成三段,刪掉右段
    w.on_sk_finish()
    assert w._sk is None and len(w.doc.sketches) == 1
    sk = w.doc.sketches[0]
    assert S.profiles(sk[2]["entities"])


def test_sketch_constraints_and_dimensions():
    """矩形自動加拘束 -> 以尺寸標註驅動 -> 修改尺寸後幾何跟著更新 -> 存回文件再開啟。"""
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.doc.add_feature("box", {"x": 60, "y": 60, "z": 10})
    w._update()
    w._set_lock({"origin": [0, 0, 5], "xdir": [1, 0, 0], "normal": [0, 0, 1]})

    def pump(n=10):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    pump(30)
    w.on_new_sketch()
    ed, pl = w._sk["ed"], w.scene.plotter
    ed.grid = False
    pump(10)

    def click(uv):
        P = ed.to3d(uv)
        r = pl.renderer
        r.SetWorldPoint(*P, 1.0)
        r.WorldToDisplay()
        x, y, _ = r.GetDisplayPoint()
        pt = QPoint(int(round(x)), int(round(pl.height() - y)))
        QTest.mouseMove(pl, pt)
        pump(2)
        QTest.mouseClick(pl, Qt.LeftButton, Qt.NoModifier, pt)
        pump(3)

    ed.set_tool("rect")
    click((-20, -10))
    click((19, 12))
    types = sorted(c["t"] for c in ed.constraints)
    assert types == ["coincident"] * 4 + ["horizontal"] * 2 + ["vertical"] * 2
    assert ed.dof() == 4

    answers = [40.0, 25.0]
    ed.ask_value = lambda title, cur: answers.pop(0)
    ed.set_tool("d_size")
    click((0, -10))           # 下邊 -> 長度 40
    ed.set_tool("d_size")
    click(tuple(ed.entities[1]["p1"][i] * .5 + ed.entities[1]["p2"][i] * .5 for i in (0, 1)))
    assert ed.dof() == 2
    e0, e1 = ed.entities[0], ed.entities[1]
    assert abs(abs(e0["p2"][0] - e0["p1"][0]) - 40) < 1e-6
    assert abs(abs(e1["p2"][1] - e1["p1"][1]) - 25) < 1e-6
    ed.set_tool("c_fix")
    click(tuple(ed.entities[0]["p1"]))
    assert ed.dof() == 0 and "完全定義" in (w._sk_changed() or w.dof_label.text())

    cid = next(c["id"] for c in ed.constraints if c["t"] == "length")
    assert ed.edit_value(cid, 55.0)
    assert abs(abs(ed.entities[0]["p2"][0] - ed.entities[0]["p1"][0]) - 55) < 1e-6
    # 與既有尺寸衝突時會被拒絕
    n = len(ed.constraints)
    ed.ask_value = lambda title, cur: 10.0
    ed.set_tool("d_size")
    click(tuple(ed.entities[0]["p1"][i] * .5 + ed.entities[0]["p2"][i] * .5 for i in (0, 1)))
    assert len(ed.constraints) == n

    w.on_sk_finish()
    sk = w.doc.sketches[0][2]
    assert len(sk["constraints"]) == n and sk["constraints"][-1]["t"] == "fix"
    w.sketch_list.setCurrentRow(0)
    w.on_edit_sketch()
    assert len(w._sk["ed"].constraints) == n and w._sk["ed"].dof() == 0
    w._end_sketch()


def test_view_cube_and_home():
    import numpy as np
    from viewer.viewcube import classify, view_for_direction
    # 純計算:面中央=單軸、靠邊=兩軸、靠角=三軸
    assert classify((0, 0, 1), (0.1, -0.2, 1)) == (0, 0, 1)
    assert classify((0, 0, 1), (0.9, 0.1, 1)) == (1, 0, 1)
    assert classify((0, -1, 0), (-0.9, -1, 0.9)) == (-1, -1, 1)
    assert view_for_direction((0, 0, -1))[1] == (0.0, -1.0, 0.0)

    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.doc.add_feature("box", {"x": 30, "y": 20, "z": 10})
    w._update()

    def pump(n=8):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    pump(30)
    pl, cube = w.scene.plotter, w.scene.cube

    def cam_dir():
        c = pl.renderer.GetActiveCamera()
        v = np.array(c.GetPosition()) - np.array(c.GetFocalPoint())
        return tuple(np.round(v / np.linalg.norm(v), 2))

    def click_face(n):
        cube.ren.SetWorldPoint(*n, 1.0)
        cube.ren.WorldToDisplay()
        x, y, _ = cube.ren.GetDisplayPoint()
        QTest.mouseClick(pl, Qt.LeftButton, Qt.NoModifier, QPoint(int(round(x)), int(round(pl.height() - y))))
        pump()

    for normal, expect in (((0, 0, 1), (0, 0, 1)), ):
        w.scene.go_home()
        pump()
        click_face(normal)
        assert cam_dir() == expect                      # 點頂面 -> 上視圖
    for normal, expect in (((0, -1, 0), (0, -1, 0)), ((1, 0, 0), (1, 0, 0))):
        w.scene.set_view("等角視")
        pump()
        # 等角視下看得到的面: 頂(+Z)、前(-Y)、右(+X);點面中心略偏向相機一側以避開邊的判定
        click_face(tuple(0.9 * v for v in normal))
        assert cam_dir() == expect
    QTest.mouseClick(cube.home, Qt.LeftButton)            # HOME 回到初始(等角)視角
    pump()
    assert cam_dir() == (0.58, -0.58, 0.58)


def test_display_quality_menu():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.doc.add_feature("cylinder", {"r": 10, "h": 5})
    w._update()
    n = {}
    for name in ("低", "超高"):
        w.on_quality(name)
        actor = w.scene.plotter.renderer.actors["body0"]
        n[name] = actor.GetMapper().GetInput().GetNumberOfCells()
    assert n["低"] < n["超高"]
    w.on_quality("高")


def test_measure_tools():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.resize(1300, 850)
    w.show()
    w.doc.add_feature("box", {"x": 40, "y": 30, "z": 20})
    w._update()

    def pump(n=8):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    pump(30)
    w.scene.go_home()
    pump(10)
    pl, r = w.scene.plotter, w.scene.plotter.renderer

    def click(P):
        r.SetWorldPoint(*P, 1.0)
        r.WorldToDisplay()
        x, y, _ = r.GetDisplayPoint()
        QTest.mouseClick(pl, Qt.LeftButton, Qt.NoModifier, QPoint(int(round(x)), int(round(pl.height() - y))))
        pump(4)

    w.on_measure("point")                              # 兩個可見頂點:對角線 50
    click((20, -15, 10))
    click((-20, 15, 10))
    assert "點到點距離 = 50 mm" in w.measure_text.toPlainText()
    w.on_measure("face")
    click((0, 0, 10))
    assert "面積 = 1200 mm²" in w.measure_text.toPlainText()
    w.on_measure("angle")                              # 頂面與右面(+X)
    click((5, 5, 10))
    click((20, 2, 3))
    assert "角度(面-面) = 90°" in w.measure_text.toPlainText()
    w.on_measure("edge")
    click((20, -15, 0))
    assert "長度 = 20 mm" in w.measure_text.toPlainText()
    assert len(w.scene.measure.items) == 4
    w.on_measure_clear()
    assert w.scene.measure.items == []
    w.on_measure_exit()
    assert w.scene.mode == "off"


def test_radius_diameter_annotation():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.resize(1300, 850)
    w.show()
    for kind, params in (("box", {"x": 40, "y": 30, "z": 20}), ("cylinder", {"r": 6, "h": 40})):
        w.doc.add_feature(kind, params)
    w.doc.add_feature("boolean", {"op": "差集", "target": 1, "tool": 2, "keep": False})
    w._update()

    def pump(n=8):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    pump(30)
    w.scene.go_home()
    pump(10)
    pl, r = w.scene.plotter, w.scene.plotter.renderer

    def click(P):
        r.SetWorldPoint(*P, 1.0)
        r.WorldToDisplay()
        x, y, _ = r.GetDisplayPoint()
        QTest.mouseClick(pl, Qt.LeftButton, Qt.NoModifier, QPoint(int(round(x)), int(round(pl.height() - y))))
        pump(5)

    w.on_annotate_tool("ann_diameter")
    click((6, 0, 10))                                      # 孔口的圓邊
    assert len(w.doc.annotations) == 1
    ann = w.doc.annotations[0][2]
    assert ann["mode"] == "直徑" and abs(ann["radius"] - 6) < 1e-6
    click((20, -15, 10))                                   # 頂點:不建立
    assert len(w.doc.annotations) == 1
    w.on_annotate_tool("ann_radius")
    click((-6, 0, 10))
    assert [a[2]["mode"] for a in w.doc.annotations] == ["直徑", "半徑"]
    assert w.ann_list.count() == 2
    # 改孔徑:標註自動跟著
    k = next(i for i, f in enumerate(w.doc.features) if f.kind == "cylinder")
    assert w.doc.edit_feature(k, {"r": 7}) is None
    assert abs(w.doc.annotations[0][2]["radius"] - 7) < 1e-6
    w.on_measure_exit()


def test_history_suppress_rollback_ui():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    for kind, params in (("box", {"x": 10, "y": 10, "z": 10}), ("cylinder", {"r": 2, "h": 30})):
        w.doc.add_feature(kind, params)
    w.doc.add_feature("boolean", {"op": "差集", "target": 1, "tool": 2, "keep": False})
    w._update()
    assert len(w.doc.bodies) == 1
    w.history.setCurrentRow(2)
    w.on_suppress_feature()
    assert len(w.doc.bodies) == 2 and "[已抑制]" in w.history.item(2).text()
    w.on_suppress_feature()
    assert len(w.doc.bodies) == 1
    w.history.setCurrentRow(1)
    w.on_rollback()
    assert len(w.doc.bodies) == 2 and "回溯點" in w.history.item(1).text()
    w.on_rollback_end()
    assert w.doc.rollback is None and len(w.doc.bodies) == 1
    from PyQt5.QtWidgets import QMessageBox
    QMessageBox.warning = staticmethod(lambda *a, **k: None)        # 移動後布林會失敗並彈出警告,測試中略過
    w.history.setCurrentRow(1)
    w.on_move_feature(1)
    assert w.doc.features[2].kind == "cylinder" and "找不到被參照" in w.doc.features[1].error


def test_hole_pattern_mirror_shell_dialogs():
    import ui.main_window as mw
    from PyQt5.QtWidgets import QMessageBox
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.doc.add_feature("box", {"x": 40, "y": 40, "z": 20})
    w._update()
    w.tree.setCurrentRow(0)
    orig = mw.ask
    try:
        w._set_lock({"origin": [0, 0, 10], "xdir": [1, 0, 0], "normal": [0, 0, 1]})
        mw.ask = lambda t, f, p=None, initial=None: {
            "type": "簡單孔", "d": 6.0, "depth": 0.0, "cb_d": 14.0, "cb_depth": 5.0, "csk_d": 16.0,
            "csk_angle": 90.0, "pts": "0,0; 10,0", "flip": False}
        w.on_hole()
        assert w.doc.features[-1].kind == "hole" and w.doc.features[-1].error is None
        v_holes = w.doc.bodies[0].shape.Volume()
        assert v_holes < 32000
        mw.ask = lambda t, f, p=None, initial=None: {"plane": "YZ", "op": "另建新實體"}
        w.tree.setCurrentRow(0)
        w.on_mirror()
        assert len(w.doc.bodies) == 2
        mw.ask = lambda t, f, p=None, initial=None: {
            "kind": "線性", "n": 2.0, "dx": 50.0, "dy": 0.0, "dz": 0.0, "angle": 360.0, "axis": "Z 軸",
            "cx": 0.0, "cy": 0.0, "cz": 0.0}
        w.tree.setCurrentRow(1)
        w.on_pattern()
        assert w.doc.features[-1].kind == "pattern" and w.doc.features[-1].error is None
        w.scene.set_mode("face")
        top = next(i for i, f in enumerate(w.doc.bodies[0].shape.Faces()) if f.Center().z > 9 and f.Area() > 1000)
        w.scene.sel_body, w.scene.sel_faces = 0, {top}
        mw.ask = lambda t, f, p=None, initial=None: {"thickness": 0.5, "dir": "向內"}
        w.on_shell()
        assert w.doc.features[-1].kind == "shell" and w.doc.features[-1].error is None
        assert w.doc.bodies[0].shape.Volume() < v_holes
    finally:
        mw.ask = orig


def test_appearance_and_section_view():
    import ui.main_window as mw
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.doc.add_feature("box", {"x": 40, "y": 40, "z": 20})
    w.doc.add_feature("cylinder", {"r": 4, "h": 10})
    w.doc.add_feature("translate", {"body": 2, "x": 60, "y": 0, "z": 0})
    w._update()
    w.tree.setCurrentRow(1)
    w.on_body_toggle()                                          # 隱藏圓柱
    assert "(隱藏)" in w.tree.item(1).text() and w.scene._meshes[1].n_cells == 0
    assert w.scene._meshes[0].n_cells > 0
    w.on_show_all()
    assert w.scene._meshes[1].n_cells > 0 and "(隱藏)" not in w.tree.item(1).text()
    w.tree.setCurrentRow(0)
    w._appearance(color="#ff0000", opacity=0.5)
    actor = w.scene.plotter.renderer.actors["body0"]
    assert abs(actor.GetProperty().GetOpacity() - 0.5) < 1e-6 and actor.GetProperty().GetColor() == (1.0, 0.0, 0.0)
    orig = mw.ask
    try:
        mw.ask = lambda t, f, p=None, initial=None: {"plane": "YZ", "offset": 0.0, "flip": False}
        w.on_section()
        assert w.scene.section is not None
        assert actor.GetMapper().GetNumberOfClippingPlanes() == 1
        w.on_section_off()
        assert w.scene.section is None
        assert w.scene.plotter.renderer.actors["body0"].GetMapper().GetNumberOfClippingPlanes() == 0
    finally:
        mw.ask = orig


def test_expression_fields_and_loft_dialog():
    from ui.dialogs import ParamDialog, parse_num, fmt_num
    import pytest
    app = QApplication.instance() or QApplication([])
    assert parse_num("12.5") == 12.5 and parse_num(" =w/2 ") == "=w/2" and fmt_num(3.0) == "3"
    with pytest.raises(ValueError):
        parse_num("abc")
    dlg = ParamDialog("t", [("x", "X", "num", 5.0), ("c", "C", "combo", ["a", "b"])])
    dlg.set_values({"x": "=寬/2", "c": "b"})
    assert dlg.values() == {"x": "=寬/2", "c": "b"}
    w = MainWindow()
    w.show()                                   # 未顯示的 OpenGL 視窗做繪製會間歇性崩潰
    w.doc.set_variables({"寬": 30})
    w._run(lambda: w.doc.add_feature("box", {"x": "=寬", "y": 10, "z": 10}))
    assert abs(w.doc.bodies[0].shape.BoundingBox().xlen - 30) < 1e-2


def test_drawing_dialog_builds_sheet(monkeypatch):
    import ui.main_window as mw
    from PyQt5.QtWidgets import QDialog
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.doc.add_feature("box", {"x": 60, "y": 40, "z": 30})
    w._update()
    monkeypatch.setattr(mw, "ask", lambda t, f, p=None, initial=None: {
        "paper": "A4", "proj": "第一角法", "scale": "自動", "front": True, "top": True, "right": False,
        "iso": False, "hidden": True, "dims": True, "hole_pos": True, "radii": True, "chain": False,
        "section": "前剖(XZ 平面)", "sec_off": 0.0, "title": "T", "part": "P", "author": "A"})
    shown = {}
    monkeypatch.setattr(QDialog, "exec_", lambda self: shown.setdefault("title", self.windowTitle()) and 0)
    w.on_drawing()
    assert "工程圖預覽" in shown["title"]
