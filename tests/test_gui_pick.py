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
