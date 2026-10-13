"""最近檔案、自動備份/恢復、顯示單位。"""
import os

import pytest

pytest.importorskip("PyQt5")
if not os.environ.get("DISPLAY"):
    pytest.skip("需要 X 顯示(例如 xvfb-run)", allow_module_level=True)

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import numfmt  # noqa: E402
from ui import session as S  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def test_unit_formatting():
    numfmt.set_unit("in")
    try:
        assert numfmt.fmtl(25.4) == "1"
        assert numfmt.fmta(645.16) == "1"
        assert numfmt.fmtv(16387.064) == "1"
    finally:
        numfmt.set_unit("mm")
    assert numfmt.fmtl(25.4) == "25.4"
    with pytest.raises(ValueError):
        numfmt.set_unit("ft")


def test_recent_files(tmp_path):
    S.clear_recent()
    paths = []
    for i in range(12):
        p = tmp_path / f"a{i}.v3d"
        p.write_text("{}")
        S.add_recent(str(p))
        paths.append(str(p))
    r = S.recent_files()
    assert len(r) == S.MAX_RECENT and r[0] == paths[-1]
    S.add_recent(paths[5])                                   # 重複者移到最前
    assert S.recent_files()[0] == paths[5] and len(S.recent_files()) == S.MAX_RECENT
    S.clear_recent()
    assert S.recent_files() == []


def test_recent_menu_save_open_and_missing(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    S.clear_recent()
    w = MainWindow()
    w.show()
    w.doc.add_feature("box", {"x": 10, "y": 10, "z": 10})
    p = str(tmp_path / "m.v3d")
    w._save(p)
    assert S.recent_files()[0] == os.path.abspath(p)
    w._fill_recent()
    assert any(os.path.abspath(p) in a.text() for a in w.recent_menu.actions())
    w2 = MainWindow()
    w2.open_recent(p)
    assert len(w2.doc.bodies) == 1
    os.remove(p)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    w2.doc.dirty = False
    w2.open_recent(p)
    assert S.recent_files() == []                            # 不存在者自動移除


def test_autosave_and_recovery(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    S.clear_backup()
    w = MainWindow()
    w.show()
    assert w.autosave_now() is False                         # 空專案不備份
    w.doc.add_feature("box", {"x": 10, "y": 20, "z": 30})
    w._update()
    assert w.autosave_now() is True and S.read_backup_info()["source"] is None
    # 模擬當機:新視窗偵測備份並恢復
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w2 = MainWindow()
    assert w2.check_recovery() is True
    assert len(w2.doc.bodies) == 1 and w2.doc.dirty
    # 儲存後備份清除
    w2._save(str(tmp_path / "r.v3d"))
    assert S.read_backup_info() is None
    # 拒絕恢復 -> 備份被丟棄
    w.doc.dirty = True
    w.autosave_now()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    assert MainWindow().check_recovery() is False and S.read_backup_info() is None


def test_unit_in_measure_text():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.set_unit("in")
    try:
        assert numfmt.UNIT == "in" and w.unit_actions["in"].isChecked()
        from viewer import measure_tool as MT
        assert MT._L(50.8) == "2"
    finally:
        w.set_unit("mm")
