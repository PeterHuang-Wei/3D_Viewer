"""主視窗(繁體中文介面)。"""
import os

from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QListWidget, QDockWidget,
)

from core.model import Document
from viewer.scene import Scene, VIEWS

STEP_FILTER = "STEP 檔案 (*.step *.stp *.STEP *.STP)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.scene = Scene(self)
        self.setCentralWidget(self.scene.widget)
        self.resize(1280, 800)

        self.tree = QListWidget()
        dock = QDockWidget("特徵樹", self)
        dock.setWidget(self.tree)
        self.addDockWidget(0x1, dock)  # 左側

        self._build_menus()
        self._update()

    def _action(self, text, slot, shortcut=None, checkable=False, checked=False):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(shortcut)
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)
        return act

    def _build_menus(self):
        bar = self.menuBar()
        m = bar.addMenu("檔案(&F)")
        m.addAction(self._action("新建", self.on_new, "Ctrl+N"))
        m.addAction(self._action("開啟 STEP...", self.on_open, "Ctrl+O"))
        m.addAction(self._action("儲存", self.on_save, "Ctrl+S"))
        m.addAction(self._action("另存為 STEP...", self.on_save_as, "Ctrl+Shift+S"))
        m.addSeparator()
        m.addAction(self._action("結束", self.close, "Ctrl+Q"))

        v = bar.addMenu("檢視(&V)")
        for name in VIEWS:
            v.addAction(self._action(name, lambda _, n=name: self.scene.set_view(n)))
        v.addSeparator()
        v.addAction(self._action("線框模式", self.on_wireframe, checkable=True))
        v.addAction(self._action("顯示邊線", self.on_edges, checkable=True, checked=True))

    # --- 檔案 ---
    def on_new(self):
        self.doc.clear()
        self._update()

    def on_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟 STEP", "", STEP_FILTER)
        if path:
            self.load(path)

    def load(self, path):
        try:
            self.doc.open_step(path)
        except Exception as e:
            QMessageBox.critical(self, "開啟失敗", str(e))
            return
        self._update()

    def on_save(self):
        if self.doc.path:
            self._save(self.doc.path)
        else:
            self.on_save_as()

    def on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "另存為 STEP", "", STEP_FILTER)
        if path:
            if not path.lower().endswith((".step", ".stp")):
                path += ".step"
            self._save(path)

    def _save(self, path):
        try:
            self.doc.save_step(path)
        except Exception as e:
            QMessageBox.critical(self, "儲存失敗", str(e))
            return
        self._update(reset_camera=False)

    # --- 檢視 ---
    def on_wireframe(self, on):
        self.scene.wireframe = on
        self.scene.refresh(self.doc, reset_camera=False)

    def on_edges(self, on):
        self.scene.show_edges = on
        self.scene.refresh(self.doc, reset_camera=False)

    def _update(self, reset_camera=True):
        self.scene.refresh(self.doc, reset_camera)
        self.tree.clear()
        self.tree.addItems([b.name for b in self.doc.bodies])
        name = os.path.basename(self.doc.path) if self.doc.path else "未命名"
        self.setWindowTitle(f"3D Viewer - {name}")
        self.statusBar().showMessage(f"共 {len(self.doc.bodies)} 個實體")
