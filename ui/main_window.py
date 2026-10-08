"""主視窗(繁體中文介面)。"""
import os

from PyQt5.QtWidgets import (
    QMainWindow, QAction, QActionGroup, QFileDialog, QMessageBox, QListWidget, QDockWidget,
)

from core import features as F
from core.model import Document
from .dialogs import ask
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

        self.scene.on_selection = self._show_selection
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

        c = bar.addMenu("建立(&C)")
        for text, slot in (("方塊...", self.on_box), ("圓柱...", self.on_cylinder),
                           ("球...", self.on_sphere), ("圓錐...", self.on_cone),
                           ("環...", self.on_torus)):
            c.addAction(self._action(text, slot))
        c.addSeparator()
        c.addAction(self._action("草圖拉伸...", self.on_extrude))
        c.addAction(self._action("草圖旋轉...", self.on_revolve))

        t = bar.addMenu("變換(&T)")
        t.addAction(self._action("平移...", self.on_translate))
        t.addAction(self._action("旋轉...", self.on_rotate))
        t.addSeparator()
        t.addAction(self._action("刪除", self.on_delete, "Del"))

        m2 = bar.addMenu("修飾(&M)")
        grp = QActionGroup(self)
        for text, mode in (("選取模式:關閉", "off"), ("選取模式:邊", "edge"), ("選取模式:面", "face")):
            act = self._action(text, lambda _, md=mode: self.on_mode(md), checkable=True,
                               checked=(mode == "off"))
            grp.addAction(act)
            m2.addAction(act)
        m2.addAction(self._action("清除選取", self.scene.clear_selection, "Esc"))
        m2.addSeparator()
        m2.addAction(self._action("圓角...", self.on_fillet))
        m2.addAction(self._action("倒角...", self.on_chamfer))

        b = bar.addMenu("布林運算(&B)")
        for op in ("聯集", "差集", "交集"):
            b.addAction(self._action(f"{op}...", lambda _, o=op: self.on_boolean(o)))

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

    # --- 建立 ---
    def _add(self, fn, name):
        """執行建模函式並加入文件;失敗時顯示訊息。"""
        try:
            self.doc.add(fn(), name)
        except Exception as e:
            QMessageBox.critical(self, "操作失敗", str(e))
            return
        self._update()

    def _num(self, title, fields):
        return ask(title, [(k, l, "num", d) for k, l, d in fields], self)

    def on_box(self):
        v = self._num("方塊", [("x", "長 X", 20), ("y", "寬 Y", 20), ("z", "高 Z", 20)])
        if v:
            self._add(lambda: F.make_box(v["x"], v["y"], v["z"]), "方塊")

    def on_cylinder(self):
        v = self._num("圓柱", [("r", "半徑", 10), ("h", "高度", 20)])
        if v:
            self._add(lambda: F.make_cylinder(v["r"], v["h"]), "圓柱")

    def on_sphere(self):
        v = self._num("球", [("r", "半徑", 10)])
        if v:
            self._add(lambda: F.make_sphere(v["r"]), "球")

    def on_cone(self):
        v = self._num("圓錐", [("r1", "底半徑", 10), ("r2", "頂半徑", 0), ("h", "高度", 20)])
        if v:
            self._add(lambda: F.make_cone(v["r1"], v["r2"], v["h"]), "圓錐")

    def on_torus(self):
        v = self._num("環", [("R", "大半徑", 15), ("r", "小半徑", 3)])
        if v:
            self._add(lambda: F.make_torus(v["R"], v["r"]), "環")

    def _sketch_dialog(self, title, extra):
        fields = [
            ("plane", "草圖平面", "combo", list(F.PLANES)),
            ("offset", "平面偏移", "num", 0),
            ("kind", "輪廓", "combo", ["矩形", "圓", "正多邊形", "自訂多邊形"]),
            ("w", "矩形寬", "num", 20), ("h", "矩形高", "num", 10),
            ("r", "圓/多邊形半徑", "num", 10), ("n", "多邊形邊數", "num", 6),
            ("pts", "自訂點(x,y; x,y; ...)", "text", "0,0; 20,0; 10,15"),
            ("cx", "輪廓中心偏移 X", "num", 0), ("cy", "輪廓中心偏移 Y", "num", 0),
        ] + extra
        v = ask(title, fields, self)
        if not v:
            return None
        try:
            params = dict(w=v["w"], h=v["h"], r=v["r"], n=v["n"], cx=v["cx"], cy=v["cy"],
                          pts=F.parse_points(v["pts"]) if v["kind"] == "自訂多邊形" else [])
        except ValueError:
            QMessageBox.critical(self, "輸入錯誤", "自訂點格式應為 x,y; x,y; ...")
            return None
        return F.PLANES[v["plane"]], v["offset"], v["kind"], params, v

    def on_extrude(self):
        r = self._sketch_dialog("草圖拉伸", [
            ("depth", "拉伸距離", "num", 10), ("sym", "雙向對稱", "bool", False)])
        if r:
            plane, off, kind, params, v = r
            self._add(lambda: F.sketch_extrude(plane, off, kind, params, v["depth"], v["sym"]),
                      "拉伸體")

    def on_revolve(self):
        r = self._sketch_dialog("草圖旋轉(繞草圖局部 Y 軸)", [("angle", "旋轉角度", "num", 360)])
        if r:
            plane, off, kind, params, v = r
            self._add(lambda: F.sketch_revolve(plane, off, kind, params, v["angle"]), "旋轉體")

    # --- 變換 / 布林 ---
    def _current(self):
        i = self.tree.currentRow()
        if i < 0 or i >= len(self.doc.bodies):
            QMessageBox.information(self, "提示", "請先在左側特徵樹選取一個實體")
            return None
        return i

    def _apply(self, i, fn):
        try:
            self.doc.bodies[i].shape = fn(self.doc.bodies[i].shape)
        except Exception as e:
            QMessageBox.critical(self, "操作失敗", str(e))
            return
        self._update(reset_camera=False)
        self.tree.setCurrentRow(i)

    def on_translate(self):
        i = self._current()
        v = i is not None and self._num("平移", [("x", "ΔX", 0), ("y", "ΔY", 0), ("z", "ΔZ", 0)])
        if v:
            self._apply(i, lambda s: F.translate(s, v["x"], v["y"], v["z"]))

    def on_rotate(self):
        i = self._current()
        v = i is not None and ask("旋轉(度)", [
            ("x", "繞 X", "num", 0), ("y", "繞 Y", "num", 0), ("z", "繞 Z", "num", 0),
            ("c", "繞物件中心(否則繞原點)", "bool", True)], self)
        if v:
            self._apply(i, lambda s: F.rotate(s, v["x"], v["y"], v["z"], v["c"]))

    def on_delete(self):
        i = self._current()
        if i is not None:
            del self.doc.bodies[i]
            self._update(reset_camera=False)

    def on_boolean(self, op):
        names = [b.name for b in self.doc.bodies]
        if len(names) < 2:
            QMessageBox.information(self, "提示", "至少需要兩個實體才能進行布林運算")
            return
        v = ask(f"布林{op}", [
            ("a", "目標實體", "combo", [f"{i}: {n}" for i, n in enumerate(names)]),
            ("b", "工具實體", "combo", [f"{i}: {n}" for i, n in enumerate(names)]),
            ("keep", "保留原工具實體", "bool", False)], self)
        if not v:
            return
        a, b = int(v["a"].split(":")[0]), int(v["b"].split(":")[0])
        if a == b:
            QMessageBox.warning(self, "提示", "目標與工具不可為同一實體")
            return
        try:
            res = F.boolean(op, self.doc.bodies[a].shape, self.doc.bodies[b].shape)
        except Exception as e:
            QMessageBox.critical(self, "布林運算失敗", str(e))
            return
        self.doc.bodies[a].shape = res
        if not v["keep"]:
            del self.doc.bodies[b]
        self._update(reset_camera=False)

    # --- 選取 / 倒角 / 圓角 ---
    def on_mode(self, mode):
        self.scene.set_mode(mode)
        if mode != "off":
            self.statusBar().showMessage("在 3D 視窗點選" + ("邊" if mode == "edge" else "面")
                                         + "(再點一次取消),完成後到「修飾」選單")

    def _show_selection(self):
        s = self.scene
        self.statusBar().showMessage(f"已選取 {len(s.sel_edges)} 條邊、{len(s.sel_faces)} 個面")

    def _selected_edge_ids(self):
        s = self.scene
        if s.sel_body is None or not (s.sel_edges or s.sel_faces):
            QMessageBox.information(self, "提示", "請先用「選取模式」在 3D 視窗選取邊或面")
            return None, None
        shape = self.doc.bodies[s.sel_body].shape
        return s.sel_body, set(s.sel_edges) | F.face_edge_ids(shape, s.sel_faces)

    def on_fillet(self):
        i, ids = self._selected_edge_ids()
        v = ids and self._num("圓角", [("r", "半徑", 2)])
        if v:
            self._apply(i, lambda s: F.fillet(s, ids, v["r"]))

    def on_chamfer(self):
        i, ids = self._selected_edge_ids()
        v = ids and ask("倒角", [("d", "距離 1", "num", 2), ("d2", "距離 2(0 = 同距離 1)", "num", 0)], self)
        if v:
            self._apply(i, lambda s: F.chamfer(s, ids, v["d"], v["d2"] or None))

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
