"""主視窗(繁體中文介面)。"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QActionGroup, QFileDialog, QMessageBox, QListWidget,
    QDockWidget, QLabel, QToolBar, QLineEdit, QCheckBox, QDoubleSpinBox,
    QInputDialog, QPushButton, QWidget, QVBoxLayout,
)

from core import features as F
from core import sketch_solver as K
from core.model import Document, STL_QUALITY
from core.ops import PLACEABLE
from viewer.scene import Scene, VIEWS
from viewer.sketch_editor import SketchEditor, TOOLS as SK_TOOLS, CONSTRAINT_TOOLS
from .dialogs import ask
from .schemas import SCHEMAS

STEP_FILTER = "STEP 檔案 (*.step *.stp *.STEP *.STP)"
STL_FILTER = "STL 檔案 (*.stl *.STL)"
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
        self.sketch_list = QListWidget()                # 草圖清單
        self.sketch_list.itemDoubleClicked.connect(lambda _: self.on_edit_sketch())
        docks = []
        for title, widget in (("實體", self.tree), ("特徵歷史(雙擊編輯參數)", self.history)):
            dock = QDockWidget(title, self)
            dock.setWidget(widget)
            self.addDockWidget(Qt.LeftDockWidgetArea, dock)
            docks.append(dock)
        self.helix_list = QListWidget()                 # 螺旋線路徑清單
        self.helix_list.itemDoubleClicked.connect(lambda _: self.on_edit_helix())
        hdock = QDockWidget("螺旋線(雙擊編輯)", self)
        hdock.setWidget(self.helix_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, hdock)
        sdock = QDockWidget("草圖(雙擊編輯)", self)
        sdock.setWidget(self.sketch_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, sdock)
        self.tabifyDockWidget(docks[0], sdock)
        self.tabifyDockWidget(docks[0], hdock)
        docks[0].raise_()
        self._sk = None                                 # 草圖編輯狀態
        self._build_sketch_bar()

        self.wp = None                                  # 鎖定的工作平面
        self.wp_id = None                               # 若鎖定的是參考面,其編號
        self.planes_list = QListWidget()                # 參考面清單
        pdock = QDockWidget("參考面(F3 鎖定所選)", self)
        pdock.setWidget(self.planes_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, pdock)
        self.tabifyDockWidget(docks[0], pdock)
        docks[0].raise_()
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
        m.addAction(self._action("匯出 STL...", self.on_export_stl))
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
        c.addAction(self._action("快速拉伸(輪廓參數)...", lambda _=None: self.on_create("extrude")))
        c.addAction(self._action("快速旋轉(輪廓參數)...", lambda _=None: self.on_create("revolve")))

        sk = bar.addMenu("草圖(&S)")
        sk.addAction(self._action("在鎖定平面上新建草圖", self.on_new_sketch, "F4"))
        sk.addAction(self._action("編輯所選草圖...", self.on_edit_sketch))
        sk.addSeparator()
        sk.addAction(self._action("草圖拉伸(實體/切除)...", lambda _=None: self.on_sketch_solid("sketch_extrude")))
        sk.addAction(self._action("草圖旋轉(實體/切除)...", lambda _=None: self.on_sketch_solid("sketch_revolve")))
        sk.addAction(self._action("草圖掃掠(實體/切除)...", self.on_sketch_sweep))
        sk.addSeparator()
        sk.addAction(self._action("在鎖定平面建立螺旋線路徑...", self.on_create_helix))
        sk.addAction(self._action("編輯所選螺旋線...", self.on_edit_helix))
        sk.addAction(self._action("刪除所選螺旋線", self.on_delete_helix))
        sk.addSeparator()
        sk.addAction(self._action("刪除所選草圖", self.on_delete_sketch))

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
        """另存新檔:依檔名或所選類型存成專案(.v3d)、STEP 或 STL。"""
        path, flt = QFileDialog.getSaveFileName(
            self, "另存新檔", "", f"{PROJ_FILTER};;{STEP_FILTER};;{STL_FILTER}")
        if not path:
            return
        low = path.lower()
        if low.endswith((".step", ".stp")):
            self._export_step(path)
        elif low.endswith(".stl"):
            self._export_stl(path)
        elif "STEP" in flt and not low.endswith(".v3d"):
            self._export_step(path + ".step")
        elif "STL" in flt and not low.endswith(".v3d"):
            self._export_stl(path + ".stl")
        else:
            self._save(path if low.endswith(".v3d") else path + ".v3d")

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
        if path:
            self._export_step(path if path.lower().endswith((".step", ".stp")) else path + ".step")

    def _export_step(self, path):
        try:
            self.doc.export_step(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "匯出失敗", str(e))
            return
        self.statusBar().showMessage(f"已匯出 {os.path.basename(path)}")

    def on_export_stl(self):
        path, _ = QFileDialog.getSaveFileName(self, "匯出 STL", "", STL_FILTER)
        if path:
            self._export_stl(path if path.lower().endswith(".stl") else path + ".stl")

    def _export_stl(self, path):
        if not self.doc.bodies:
            QMessageBox.information(self, "匯出 STL", "目前沒有可匯出的實體")
            return
        v = ask("STL 匯出設定", [
            ("q", "精細度", "combo", list(STL_QUALITY)),
            ("ascii", "ASCII 格式(預設為檔案較小的二進位)", "bool", False)], self, initial={"q": "高(預設)"})
        if not v:
            return
        tol, ang = STL_QUALITY[v["q"]]
        try:
            n = self.doc.export_stl(path, tol, ang, v["ascii"])
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "匯出失敗", str(e))
            return
        self.statusBar().showMessage(
            f"已匯出 {os.path.basename(path)}({n:,} 個三角形,弦高誤差 {tol} mm)")

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
        if feat.kind == "sketch":
            sk = next((x for i, _, x in self.doc.sketches if i in feat.out_ids), None)
            self._begin_sketch(sk["wp"] if sk else feat.params["wp"], feat.params["entities"], k,
                               feat.out_ids[0] if feat.out_ids else None,
                               feat.params.get("constraints", []))
            return
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

    # --- 草圖 ---
    def _build_sketch_bar(self):
        bar = QToolBar("草圖工具", self)
        bar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.sk_bar = bar
        grp = QActionGroup(self)
        self.sk_tool_actions = {}
        for tool in ("select", "line", "rect", "circle", "arc", "trim", "delete"):
            act = QAction(SK_TOOLS[tool], self)
            act.setCheckable(True)
            act.triggered.connect(lambda _, t=tool: self._sk and self._sk["ed"].set_tool(t))
            grp.addAction(act)
            bar.addAction(act)
            self.sk_tool_actions[tool] = act
        bar.addSeparator()
        for text, slot, key in (("鏡射...", self.on_sk_mirror, None), ("陣列...", self.on_sk_pattern, None),
                                ("刪除所選", lambda: self._sk["ed"].delete_selected(), "Del"),
                                ("復原", lambda: self._sk["ed"].undo(), "Ctrl+Z"),
                                ("重做", lambda: self._sk["ed"].redo(), "Ctrl+Y"),
                                ("正視於草圖", lambda: self._sk["ed"].view_normal(), None)):
            act = QAction(text, self)
            if key:
                act.setShortcut(key)
            act.triggered.connect(lambda _=None, f=slot: self._sk and f())
            bar.addAction(act)
        esc = QAction("取消目前操作", self)
        esc.setShortcut("Esc")
        esc.triggered.connect(lambda _=None: self._sk and self._sk["ed"].cancel_op())
        self.addAction(esc)
        bar.addSeparator()
        self.sk_grid = QCheckBox("格點吸附")
        self.sk_grid.setChecked(True)
        self.sk_grid.toggled.connect(lambda on: self._sk and setattr(self._sk["ed"], "grid", on))
        self.sk_step = QDoubleSpinBox()
        self.sk_step.setRange(0.01, 1000)
        self.sk_step.setValue(1.0)
        self.sk_step.valueChanged.connect(lambda v: self._sk and setattr(self._sk["ed"], "grid_step", v))
        self.sk_input = QLineEdit()
        self.sk_input.setPlaceholderText("數值輸入:x,y  @dx,dy  @長度<角度  半徑 → Enter")
        self.sk_input.setMinimumWidth(300)
        self.sk_input.returnPressed.connect(self.on_sk_typed)
        for w in (self.sk_grid, self.sk_step, self.sk_input):
            bar.addWidget(w)
        bar.addSeparator()
        bar.addAction(self._action("✔ 完成草圖", self.on_sk_finish))
        bar.addAction(self._action("✘ 取消", self.on_sk_cancel))
        bar.hide()
        self.addToolBarBreak(Qt.TopToolBarArea)
        bar2 = QToolBar("拘束與標註", self)
        bar2.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, bar2)
        self.sk_bar2 = bar2
        for tool, (label, ctype, _) in CONSTRAINT_TOOLS.items():
            if tool == "d_size":
                bar2.addSeparator()
            act = QAction(label.replace("尺寸:", "▭ "), self)
            act.setCheckable(True)
            act.triggered.connect(lambda _, t=tool: self._sk and self._sk["ed"].set_tool(t))
            grp.addAction(act)
            bar2.addAction(act)
            self.sk_tool_actions[tool] = act
        bar2.addSeparator()
        self.dof_label = QLabel("自由度: -")
        bar2.addWidget(self.dof_label)
        bar2.hide()
        # 拘束清單(草圖模式才顯示)
        box = QWidget()
        lay = QVBoxLayout(box)
        self.cons_list = QListWidget()
        self.cons_list.currentRowChanged.connect(self._on_cons_selected)
        self.cons_list.itemDoubleClicked.connect(lambda _: self.on_cons_edit())
        lay.addWidget(self.cons_list)
        for text, slot in (("編輯所選尺寸數值", self.on_cons_edit), ("刪除所選拘束/尺寸", self.on_cons_delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            lay.addWidget(b)
        self.cons_dock = QDockWidget("拘束與尺寸", self)
        self.cons_dock.setWidget(box)
        self.addDockWidget(Qt.RightDockWidgetArea, self.cons_dock)
        self.cons_dock.hide()

    def on_new_sketch(self):
        if not self.wp:
            QMessageBox.information(self, "草圖", "請先鎖定平面:選取一個面或參考面後按 F3,或用「平面」選單鎖定 XY/XZ/YZ")
            return
        self._begin_sketch(self.wp, [], None, None, [])

    def on_edit_sketch(self):
        r = self.sketch_list.currentRow()
        if r < 0 or r >= len(self.doc.sketches):
            QMessageBox.information(self, "草圖", "請先在「草圖」清單選取一個草圖")
            return
        sid, _, sk = self.doc.sketches[r]
        k = next(i for i, f in enumerate(self.doc.features) if f.kind == "sketch" and sid in f.out_ids)
        self._begin_sketch(sk["wp"], sk["entities"], k, sid, sk.get("constraints", []))

    def _begin_sketch(self, wp, entities, edit_index, sid, constraints):
        if self._sk:
            return
        ed = SketchEditor(self.scene, wp, entities, status=self.statusBar().showMessage,
                          constraints=constraints)
        ed.ask_value = self._ask_value
        ed.on_change = self._sk_changed
        self._sk = {"ed": ed, "edit": edit_index, "wp": wp, "plane_id": self.wp_id, "sid": sid}
        self.scene.sketch = ed
        self.scene.hide_sketch = sid
        self.scene._draw_sketches()
        self.menuBar().setEnabled(False)
        self.sk_bar.show()
        self.sk_bar2.show()
        self.cons_dock.show()
        self.sk_tool_actions["line"].setChecked(True)
        ed.tool = "line"
        ed.grid, ed.grid_step = self.sk_grid.isChecked(), self.sk_step.value()
        ed.start()
        self._sk_changed()

    def _end_sketch(self):
        if not self._sk:
            return
        self._sk["ed"].stop()
        self.scene.sketch, self.scene.hide_sketch = None, None
        self._sk = None
        self.sk_bar.hide()
        self.sk_bar2.hide()
        self.cons_dock.hide()
        self.menuBar().setEnabled(True)
        self._update(reset_camera=False)
        self.scene.set_view("等角視")

    def on_sk_finish(self):
        if not self._sk:
            return
        ed, ents = self._sk["ed"], self._sk["ed"].entities
        if not ents:
            QMessageBox.information(self, "草圖", "草圖是空的;要放棄請按「取消」")
            return
        if self._sk["edit"] is not None:
            ok = self._run(lambda: self.doc.edit_feature(
                self._sk["edit"], {"entities": ents, "constraints": ed.constraints}))
        else:
            params = {"entities": ents, "wp": self._sk["wp"], "constraints": ed.constraints}
            if self._sk["plane_id"] is not None:
                params["plane_id"] = self._sk["plane_id"]
            ok = self._run(lambda: self.doc.add_feature("sketch", params))
        if ok:
            self._end_sketch()

    def _ask_value(self, title, current):
        v, ok = QInputDialog.getDouble(self, f"尺寸:{title}", "數值:", current, -1e6, 1e6, 4)
        return v if ok else None

    def _sk_changed(self):
        """草圖內容變動:更新拘束清單與自由度顯示。"""
        if not self._sk:
            return
        ed = self._sk["ed"]
        row = self.cons_list.currentRow()
        self.cons_list.blockSignals(True)
        self.cons_list.clear()
        self.cons_list.addItems([ed.describe(c) for c in ed.constraints])
        if 0 <= row < len(ed.constraints):
            self.cons_list.setCurrentRow(row)
        self.cons_list.blockSignals(False)
        d = ed.dof()
        self.dof_label.setText("自由度: 0(完全定義)" if d == 0 else f"自由度: {d}")

    def _on_cons_selected(self, row):
        if self._sk:
            ed = self._sk["ed"]
            ed.highlight = ([q[0] for q in ed.constraints[row]["refs"]]
                            if 0 <= row < len(ed.constraints) else [])
            ed._redraw()

    def on_cons_edit(self):
        if not self._sk:
            return
        ed, row = self._sk["ed"], self.cons_list.currentRow()
        if row < 0 or row >= len(ed.constraints):
            return
        c = ed.constraints[row]
        if c["t"] not in K.DIMENSIONAL:
            QMessageBox.information(self, "拘束", "只有尺寸可以編輯數值;幾何拘束請刪除後重建")
            return
        v = self._ask_value(K.NAMES[c["t"]], c["v"])
        if v is not None and v > 0 or (v is not None and c["t"] == "angle"):
            ed.edit_value(c["id"], v)

    def on_cons_delete(self):
        if not self._sk:
            return
        ed, row = self._sk["ed"], self.cons_list.currentRow()
        if 0 <= row < len(ed.constraints):
            ed.highlight = []
            ed.delete_constraint(ed.constraints[row]["id"])

    def on_sk_cancel(self):
        if self._sk and (not self._sk["ed"].entities or
                         QMessageBox.question(self, "草圖", "放棄這次的草圖變更?") == QMessageBox.Yes):
            self._end_sketch()

    def on_sk_typed(self):
        if not self._sk:
            return
        try:
            self._sk["ed"].typed(self.sk_input.text())
        except ValueError as e:
            self.statusBar().showMessage(f"輸入無效:{e}")
            return
        self.sk_input.clear()

    def on_sk_mirror(self):
        v = ask("鏡射(對所選圖元;未選取則全部)", [
            ("axis", "鏡射軸", "combo", ["草圖 Y 軸(左右鏡射)", "草圖 X 軸(上下鏡射)", "點選兩點指定"])], self)
        if v:
            self._sk["ed"].mirror_axis({"草圖 Y": "Y", "草圖 X": "X"}.get(v["axis"][:4]))

    def on_sk_pattern(self):
        v = ask("陣列(對所選圖元;未選取則全部)", [
            ("kind", "陣列類型", "combo", ["線性", "圓形"]),
            ("n", "總數量(含原件)", "num", 3),
            ("dx", "線性:X 間距", "num", 10), ("dy", "線性:Y 間距", "num", 0),
            ("angle", "圓形:總角度", "num", 360),
            ("cx", "圓形:中心 X", "num", 0), ("cy", "圓形:中心 Y", "num", 0)], self)
        if v:
            self._sk["ed"].pattern("linear" if v["kind"] == "線性" else "circular", int(v["n"]),
                                   v["dx"], v["dy"], v["angle"], (v["cx"], v["cy"]))

    def on_sketch_solid(self, kind):
        sketches, bodies = self.doc.sketches, self.doc.bodies
        if not sketches:
            QMessageBox.information(self, "草圖", "還沒有草圖,請先建立草圖")
            return
        r = self.sketch_list.currentRow()
        items = [f"{i}: {n}" for i, n, _ in sketches]
        title, fields = SCHEMAS[kind]
        fields = [("sketch", "草圖", "combo", items)] + list(fields) + [
            ("target", "目標實體(聯集/切除用)", "combo", [f"{b.id}: {b.name}" for b in bodies] or ["(無)"])]
        v = ask(title, fields, self, initial={"sketch": items[r if 0 <= r < len(items) else -1]})
        if not v:
            return
        params = {k: val for k, val in v.items() if k not in ("sketch", "target")}
        params["sketch"] = int(v["sketch"].split(":")[0])
        if v["op"] != "新實體":
            if not bodies:
                QMessageBox.information(self, "草圖", "沒有可作為目標的實體")
                return
            params["target"] = int(v["target"].split(":")[0])
        self._run(lambda: self.doc.add_feature(kind, params))

    def on_sketch_sweep(self):
        sketches, bodies = self.doc.sketches, self.doc.bodies
        paths = [f"{i}: {n}" for i, n, _ in sketches] + [f"{i}: {n}" for i, n, _ in self.doc.helices]
        if not sketches or len(paths) < 2:
            QMessageBox.information(self, "草圖掃掠", "需要一個封閉輪廓草圖,以及一個路徑(相連的線/圓弧草圖,或螺旋線)")
            return
        items = [f"{i}: {n}" for i, n, _ in sketches]
        title, fields = SCHEMAS["sketch_sweep"]
        fields = [("profile", "輪廓草圖(封閉)", "combo", items), ("path", "路徑(草圖或螺旋線)", "combo", paths)] \
            + list(fields) + [("target", "目標實體(聯集/切除用)", "combo",
                               [f"{b.id}: {b.name}" for b in bodies] or ["(無)"])]
        v = ask(title, fields, self, initial={"profile": items[0], "path": paths[-1]})
        if not v:
            return
        params = {k: val for k, val in v.items() if k not in ("profile", "path", "target")}
        params["profile"], params["path"] = int(v["profile"].split(":")[0]), int(v["path"].split(":")[0])
        if params["profile"] == params["path"]:
            QMessageBox.warning(self, "草圖掃掠", "輪廓與路徑不可為同一個草圖")
            return
        if v["op"] != "新實體":
            if not bodies:
                QMessageBox.information(self, "草圖掃掠", "沒有可作為目標的實體")
                return
            params["target"] = int(v["target"].split(":")[0])
        self._run(lambda: self.doc.add_feature("sketch_sweep", params))

    def on_create_helix(self):
        if not self.wp:
            QMessageBox.information(self, "螺旋線", "請先鎖定平面(F3):軸線為該平面法向,起點在平面原點 + 半徑 × X 軸")
            return
        title, fields = SCHEMAS["helix"]
        v = ask(title, fields, self)
        if v:
            params = {**v, "wp": self.wp}
            if self.wp_id is not None:
                params["plane_id"] = self.wp_id
            self._run(lambda: self.doc.add_feature("helix", params))

    def _selected_helix(self):
        r = self.helix_list.currentRow()
        if r < 0 or r >= len(self.doc.helices):
            QMessageBox.information(self, "螺旋線", "請先在「螺旋線」清單選取一個螺旋線")
            return None
        return self.doc.helices[r][0]

    def on_edit_helix(self):
        hid = self._selected_helix()
        if hid is None:
            return
        k = next(i for i, f in enumerate(self.doc.features) if f.kind == "helix" and hid in f.out_ids)
        title, fields = SCHEMAS["helix"]
        v = ask("編輯:" + title, fields, self, initial=self.doc.features[k].params)
        if v:
            self._run(lambda: self.doc.edit_feature(k, v))

    def on_delete_helix(self):
        hid = self._selected_helix()
        if hid is not None:
            self._run(lambda: self.doc.add_feature("delete", {"body": hid}))

    def on_delete_sketch(self):
        r = self.sketch_list.currentRow()
        if r < 0 or r >= len(self.doc.sketches):
            QMessageBox.information(self, "草圖", "請先在「草圖」清單選取一個草圖")
            return
        sid = self.doc.sketches[r][0]
        self._run(lambda: self.doc.add_feature("delete", {"body": sid}))

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
        self.helix_list.clear()
        self.helix_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.helices])
        self.sketch_list.clear()
        self.sketch_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.sketches])
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
