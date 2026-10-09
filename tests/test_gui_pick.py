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
