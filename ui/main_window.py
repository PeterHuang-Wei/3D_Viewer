"""主視窗(繁體中文介面)。"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QActionGroup, QFileDialog, QMessageBox, QListWidget,
    QDockWidget, QLabel,
)

from core import features as F
from core.model import Document
from core.ops import PLACEABLE
from viewer.scene import Scene, VIEWS
from .dialogs import ask
from .schemas import SCHEMAS

STEP_FILTER = "STEP 檔案 (*.step *.stp *.STEP *.STP)"
PROJ_FILTER = "3D Viewer 專案 (*.v3d)"
APP = "3D Viewer"
PLACED = set(PLACEABLE) | {"extrude", "revolve", "thread_hole"}   # 可放在鎖定平面上的特徵


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.scene = Scene(self)
        self.setCentralWidget(self.scene.widget)
        self.resize(1360, 820)

        self.tree = QListWidget()                       # 目前實體
        self.history = QListWidget()                    # 特徵歷史
        self.history.itemDoubleClicked.connect(lambda _: self.on_edit_feature())
        for title, widget in (("實體", self.tree), ("特徵歷史(雙擊編輯參數)", self.history)):
            dock = QDockWidget(title, self)
            dock.setWidget(widget)
            self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        self.wp = None                                  # 鎖定的工作平面
        self.wp_id = None                               # 若鎖定的是參考面,其編號
        self.planes_list = QListWidget()                # 參考面清單
        pdock = QDockWidget("參考面(F3 鎖定所選)", self)
        pdock.setWidget(self.planes_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, pdock)
        self.lock_label = QLabel("平面:未鎖定")
        self.statusBar().addPermanentWidget(self.lock_label)
        self.scene.on_selection = self._show_selection
        self.scene.on_move = self._on_drag_move
        self._build_menus()
        self._update()

    # --- 選單 ---
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
        m.addAction(self._action("開啟專案...", self.on_open, "Ctrl+O"))
        m.addAction(self._action("儲存專案", self.on_save, "Ctrl+S"))
        m.addAction(self._action("另存專案...", self.on_save_as, "Ctrl+Shift+S"))
        m.addSeparator()
        m.addAction(self._action("匯入 STEP...", self.on_import_step))
        m.addAction(self._action("匯出 STEP...", self.on_export_step))
        m.addSeparator()
        m.addAction(self._action("結束", self.close, "Ctrl+Q"))

        e = bar.addMenu("編輯(&E)")
        self.act_undo = self._action("復原", self.on_undo, "Ctrl+Z")
        self.act_redo = self._action("重做", self.on_redo, "Ctrl+Y")
        e.addAction(self.act_undo)
        e.addAction(self.act_redo)
        e.addSeparator()
        e.addAction(self._action("編輯所選特徵參數...", self.on_edit_feature, "F2"))
        e.addAction(self._action("刪除所選特徵", self.on_delete_feature))

        c = bar.addMenu("建立(&C)")
        for kind in ("box", "cylinder", "sphere", "cone", "torus"):
            c.addAction(self._action(SCHEMAS[kind][0] + "...", lambda _, k=kind: self.on_create(k)))
        c.addSeparator()
        c.addAction(self._action("草圖拉伸...", lambda _=None: self.on_create("extrude")))
        c.addAction(self._action("草圖旋轉...", lambda _=None: self.on_create("revolve")))

        t = bar.addMenu("變換(&T)")
        t.addAction(self._action("平移...", lambda: self.on_modify("translate")))
        t.addAction(self._action("旋轉...", lambda: self.on_modify("rotate")))
        t.addAction(self._action("縮放...", lambda _=None: self.on_modify("scale")))
        t.addSeparator()
        t.addAction(self._action("刪除實體", self.on_delete_body, "Del"))

        m2 = bar.addMenu("修飾(&M)")
        grp = QActionGroup(self)
        for text, mode in (("選取模式:關閉", "off"), ("移動模式:拖曳物件", "move"), ("選取模式:邊", "edge"), ("選取模式:面", "face")):
            act = self._action(text, lambda _, md=mode: self.on_mode(md), checkable=True,
                               checked=(mode == "off"))
            grp.addAction(act)
            m2.addAction(act)
        m2.addAction(self._action("清除選取", self.scene.clear_selection, "Esc"))
        m2.addSeparator()
        m2.addAction(self._action("圓角...", lambda: self.on_edge_feature("fillet")))
        m2.addAction(self._action("倒角...", lambda: self.on_edge_feature("chamfer")))

        th = bar.addMenu("螺牙(&H)")
        th.addAction(self._action("外螺紋螺桿...", lambda: self.on_create("rod")))
        th.addAction(self._action("內螺紋切削工具體...", lambda: self.on_create("thread_tool")))
        th.addAction(self._action("在實體上開螺紋孔...", lambda: self.on_modify("thread_hole")))

        b = bar.addMenu("布林運算(&B)")
        for op in ("聯集", "差集", "交集"):
            b.addAction(self._action(f"{op}...", lambda _, o=op: self.on_boolean(o)))

        pl = bar.addMenu("平面(&P)")
        pl.addAction(self._action("鎖定所選面或參考面 / 解除鎖定", self.on_lock_toggle, "F3"))
        for name in F.WORLD_PLANES:
            pl.addAction(self._action(f"鎖定 {name} 平面", lambda _, n=name: self._set_lock(F.WORLD_PLANES[n])))
        pl.addSeparator()
        pl.addAction(self._action("以鎖定平面建立參考面(平行/傾斜)...", self.on_create_refplane))
        pl.addAction(self._action("移動/編輯所選參考面...", self.on_edit_refplane))
        pl.addAction(self._action("刪除所選參考面", self.on_delete_refplane))

        v = bar.addMenu("檢視(&V)")
        for name in VIEWS:
            v.addAction(self._action(name, lambda _, n=name: self.scene.set_view(n)))
        v.addSeparator()
        v.addAction(self._action("線框模式", self.on_wireframe, checkable=True))
        v.addAction(self._action("顯示邊線", self.on_edges, checkable=True, checked=True))

    # --- 檔案 ---
    def _confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, APP, "目前專案尚未儲存,確定要放棄變更嗎?")
        return r == QMessageBox.Yes

    def closeEvent(self, ev):
        ev.accept() if self._confirm_discard() else ev.ignore()

    def on_new(self):
        if self._confirm_discard():
            self.doc.clear()
            self._update()

    def on_open(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "開啟專案", "", PROJ_FILTER)
        if path:
            self.load(path)

    def load(self, path):
        """開啟 .v3d 專案;若為 STEP 則匯入到新專案。"""
        try:
            if path.lower().endswith((".step", ".stp")):
                self.doc.clear()
                err = self.doc.import_step(path)
                if err:
                    raise ValueError(err)
                self.doc.dirty = True
            else:
                self.doc.load_project(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "開啟失敗", str(e))
            return
        self._report_errors()
        self._update()

    def on_save(self):
        if self.doc.path:
            self._save(self.doc.path)
        else:
            self.on_save_as()

    def on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "另存專案", "", PROJ_FILTER)
        if path:
            self._save(path if path.lower().endswith(".v3d") else path + ".v3d")

    def _save(self, path):
        try:
            self.doc.save_project(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "儲存失敗", str(e))
            return
        self._update(reset_camera=False)

    def on_import_step(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入 STEP", "", STEP_FILTER)
        if path:
            self._run(lambda: self.doc.import_step(path))

    def on_export_step(self):
        path, _ = QFileDialog.getSaveFileName(self, "匯出 STEP", "", STEP_FILTER)
        if not path:
            return
        if not path.lower().endswith((".step", ".stp")):
            path += ".step"
        try:
            self.doc.export_step(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "匯出失敗", str(e))
            return
        self.statusBar().showMessage(f"已匯出 {os.path.basename(path)}")

    # --- 編輯 / 歷史 ---
    def _run(self, fn):
        """執行會改變文件的操作;fn 回傳錯誤訊息或 None。"""
        try:
            err = fn()
        except Exception as e:  # noqa: BLE001
            err = str(e)
        if err:
            QMessageBox.critical(self, "操作失敗", err)
            return False
        self._update(reset_camera=False)
        return True

    def on_undo(self):
        self.doc.undo()
        self._update(reset_camera=False)

    def on_redo(self):
        self.doc.redo()
        self._update(reset_camera=False)

    def _report_errors(self):
        bad = [f"{f.label}: {f.error}" for f in self.doc.features if f.error]
        if bad:
            QMessageBox.warning(self, "部分特徵重算失敗", "\n".join(bad))

    def on_edit_feature(self):
        k = self.history.currentRow()
        if k < 0:
            QMessageBox.information(self, "提示", "請先在特徵歷史選取一個特徵")
            return
        feat = self.doc.features[k]
        if feat.kind not in SCHEMAS:
            QMessageBox.information(self, "提示", f"「{feat.label}」沒有可編輯的參數")
            return
        title, fields = self._fields(feat.kind, bool(feat.params.get("wp")))
        v = ask("編輯:" + title, fields, self, initial=feat.params)
        if v and self._run(lambda: self.doc.edit_feature(k, v)):
            self.history.setCurrentRow(k)

    def on_delete_feature(self):
        k = self.history.currentRow()
        if k < 0:
            QMessageBox.information(self, "提示", "請先在特徵歷史選取一個特徵")
            return
        self.doc.delete_feature(k)
        self._update(reset_camera=False)
        self._report_errors()

    # --- 鎖定平面 ---
    def _set_lock(self, wp, plane_id=None):
        self.wp, self.wp_id = wp, plane_id
        self.scene.set_lock(wp, plane_id)
        if wp:
            o = ", ".join(f"{c:g}" for c in wp["origin"])
            n = ", ".join(f"{c:g}" for c in wp["normal"])
            tag = f"參考面{plane_id}" if plane_id is not None else "已鎖定"
            self.lock_label.setText(f"平面:{tag} 原點({o}) 法向({n})")
        else:
            self.lock_label.setText("平面:未鎖定")

    def on_lock_toggle(self):
        if self.wp:
            self._set_lock(None)
            return
        s = self.scene
        if s.sel_body is None and (r := self.planes_list.currentRow()) >= 0:
            pid, _, wp = self.doc.planes[r]               # 沒選面時,鎖定清單中選取的參考面
            self._set_lock(wp, pid)
            return
        if s.sel_body is None or len(s.sel_faces) != 1:
            QMessageBox.information(
                self, "鎖定平面",
                "請先在 3D 視窗用「選取模式:面」選一個平面,或在「參考面」清單選一個參考面,再按 F3")
            return
        face = self.doc.bodies[s.sel_body].shape.Faces()[next(iter(s.sel_faces))]
        try:
            wp = F.plane_from_face(face)
        except ValueError as e:
            QMessageBox.warning(self, "鎖定平面", str(e))
            return
        s.clear_selection()
        self._set_lock(wp)

    # --- 參考面 ---
    def on_create_refplane(self):
        if not self.wp:
            QMessageBox.information(self, "參考面", "請先鎖定一個面或平面(F3 或「平面」選單)作為基準")
            return
        title, fields = SCHEMAS["refplane"]
        v = ask(title, fields, self)
        if not v:
            return
        params = {**v, "wp": self.wp}
        if self.wp_id is not None:
            params["plane_id"] = self.wp_id
        if self._run(lambda: self.doc.add_feature("refplane", params)):
            pid, _, wp = self.doc.planes[-1]
            self._set_lock(wp, pid)                       # 新參考面自動成為鎖定面
            self._update(reset_camera=False)

    def _selected_plane_id(self):
        r = self.planes_list.currentRow()
        if r < 0 or r >= len(self.doc.planes):
            QMessageBox.information(self, "參考面", "請先在「參考面」清單選取一個參考面")
            return None
        return self.doc.planes[r][0]

    def on_edit_refplane(self):
        pid = self._selected_plane_id()
        if pid is None:
            return
        k = next(i for i, f in enumerate(self.doc.features) if f.kind == "refplane" and pid in f.out_ids)
        title, fields = SCHEMAS["refplane"]
        v = ask("移動/編輯:" + title, fields, self, initial=self.doc.features[k].params)
        if v:
            self._run(lambda: self.doc.edit_feature(k, v))

    def on_delete_refplane(self):
        pid = self._selected_plane_id()
        if pid is not None:
            if self.wp_id == pid:
                self._set_lock(None)
            self._run(lambda: self.doc.add_feature("delete", {"body": pid}))

    @staticmethod
    def _fields(kind, placed):
        """placed=True(在鎖定平面上)時,隱藏原本的平面/座標欄位並加入「反向」。"""
        title, fields = SCHEMAS[kind]
        if not placed or kind not in PLACED:
            return title, fields
        drop = {"extrude": ("plane", "offset"), "revolve": ("plane", "offset"),
                "thread_hole": ("axis", "x", "y", "z")}.get(kind, ())
        fields = [f for f in fields if f[0] not in drop]
        if kind != "revolve":
            label = "反向(朝實體外)" if kind == "thread_hole" else "反向(朝平面法向反側,如往實體內)"
            fields.append(("flip", label, "bool", False))
        return title + "(鎖定平面)", fields

    # --- 建立 / 修改 ---
    def on_create(self, kind):
        title, fields = self._fields(kind, bool(self.wp))
        v = ask(title, fields, self)
        if v:
            if self.wp and kind in PLACED:
                v["wp"] = self.wp
                if self.wp_id is not None:
                    v["plane_id"] = self.wp_id
            self._run(lambda: self.doc.add_feature(kind, v))
            self.scene.set_view("等角視") if len(self.doc.bodies) == 1 else None

    def _current_id(self):
        i = self.tree.currentRow()
        if i < 0 or i >= len(self.doc.bodies):
            QMessageBox.information(self, "提示", "請先在左側「實體」清單選取一個實體")
            return None
        return self.doc.bodies[i].id

    def on_modify(self, kind):
        bid = self._current_id()
        if bid is None:
            return
        title, fields = self._fields(kind, bool(self.wp))
        v = ask(title, fields, self)
        if v:
            if self.wp and kind in PLACED:
                v["wp"] = self.wp
                if self.wp_id is not None:
                    v["plane_id"] = self.wp_id
            self._run(lambda: self.doc.add_feature(kind, {**v, "body": bid}))

    def on_delete_body(self):
        bid = self._current_id()
        if bid is not None:
            self._run(lambda: self.doc.add_feature("delete", {"body": bid}))

    def on_boolean(self, op):
        bodies = self.doc.bodies
        if len(bodies) < 2:
            QMessageBox.information(self, "提示", "至少需要兩個實體才能進行布林運算")
            return
        items = [f"{b.id}: {b.name}" for b in bodies]
        v = ask(f"布林{op}", [("a", "目標實體", "combo", items), ("b", "工具實體", "combo", items),
                              ("keep", "保留原工具實體", "bool", False)], self)
        if not v:
            return
        a, b = int(v["a"].split(":")[0]), int(v["b"].split(":")[0])
        if a == b:
            QMessageBox.warning(self, "提示", "目標與工具不可為同一實體")
            return
        self._run(lambda: self.doc.add_feature(
            "boolean", {"op": op, "target": a, "tool": b, "keep": v["keep"]}))

    # --- 選取 / 倒角 / 圓角 ---
    def on_mode(self, mode):
        self.scene.set_mode(mode)
        if mode == "move":
            self.statusBar().showMessage("拖曳物件移動(沿視角平面);按住 X / Y / Z 鍵可限制軸向")
        elif mode != "off":
            self.statusBar().showMessage("在 3D 視窗點選" + ("邊" if mode == "edge" else "面")
                                         + "(再點一次取消),完成後到「修飾」選單")

    def _on_drag_move(self, index, delta):
        dx, dy, dz = delta
        bid = self.doc.bodies[index].id
        if not self._run(lambda: self.doc.add_feature(
                "translate", {"body": bid, "x": dx, "y": dy, "z": dz})):
            self._update(reset_camera=False)

    def _show_selection(self):
        s = self.scene
        self.statusBar().showMessage(f"已選取 {len(s.sel_edges)} 條邊、{len(s.sel_faces)} 個面")

    def on_edge_feature(self, kind):
        s = self.scene
        if s.sel_body is None or not (s.sel_edges or s.sel_faces):
            QMessageBox.information(self, "提示", "請先用「選取模式」在 3D 視窗選取邊或面")
            return
        body = self.doc.bodies[s.sel_body]
        edges = sorted(set(s.sel_edges) | F.face_edge_ids(body.shape, s.sel_faces))
        title, fields = SCHEMAS[kind]
        v = ask(title, fields, self)
        if v:
            self._run(lambda: self.doc.add_feature(kind, {**v, "body": body.id, "edges": edges}))

    # --- 檢視 ---
    def on_wireframe(self, on):
        self.scene.wireframe = on
        self.scene.refresh(self.doc, reset_camera=False)

    def on_edges(self, on):
        self.scene.show_edges = on
        self.scene.refresh(self.doc, reset_camera=False)

    def _update(self, reset_camera=True):
        if self.wp_id is not None:                         # 鎖定的參考面被移動/刪除時同步
            plane = next((p for p in self.doc.planes if p[0] == self.wp_id), None)
            if plane:
                self.wp = plane[2]
            else:
                self.wp_id = None
            self.scene.locked, self.scene.lock_id = self.wp, self.wp_id
            self._set_lock(self.wp, self.wp_id)
        self.scene.refresh(self.doc, reset_camera and bool(self.doc.bodies))
        self.tree.clear()
        self.tree.addItems([f"{b.id}: {b.name}" for b in self.doc.bodies])
        self.planes_list.clear()
        self.planes_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.planes])
        self.history.clear()
        for k, f in enumerate(self.doc.features):
            self.history.addItem(f"{k + 1}. {f.label}" + (f"  ⚠ {f.error}" if f.error else ""))
        self.act_undo.setEnabled(self.doc.can_undo())
        self.act_redo.setEnabled(self.doc.can_redo())
        name = os.path.basename(self.doc.path) if self.doc.path else "未命名"
        self.setWindowTitle(f"{APP} - {name}{' *' if self.doc.dirty else ''}")
        self.statusBar().showMessage(f"共 {len(self.doc.bodies)} 個實體、{len(self.doc.features)} 個特徵")
