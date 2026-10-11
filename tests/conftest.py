"""測試共用設定:讓 MainWindow 活到測試結束後才統一關閉。

局部變數在測試函式結束時被回收,會立刻銷毀(尤其是從未 show() 過的)OpenGL 視窗,
這在 CI 上會造成間歇性的 Segmentation fault;改由 fixture 先關閉再回收。"""
import gc

import pytest

_ALIVE: list = []


@pytest.fixture(autouse=True)
def _keep_and_close_windows(monkeypatch):
    try:
        import ui.main_window as mw
        orig = mw.MainWindow.__init__

        def init(self, *a, **k):
            orig(self, *a, **k)
            _ALIVE.append(self)

        monkeypatch.setattr(mw.MainWindow, "__init__", init)
    except Exception:  # noqa: BLE001   (沒有 Qt 的環境略過)
        pass
    yield
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        for w in list(_ALIVE):
            w.doc.dirty = False                        # 避免關閉時跳出「未儲存」對話框
            w.close()
            w.deleteLater()
        if app is not None:
            app.processEvents()
        _ALIVE.clear()
    except Exception:  # noqa: BLE001
        pass
    gc.collect()
