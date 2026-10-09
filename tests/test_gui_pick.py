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
