"""主視窗(繁體中文介面)。"""
import os

from PyQt5.QtCore import Qt, QSettings, QTimer, QStandardPaths
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QActionGroup, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QDockWidget, QLabel, QToolBar, QLineEdit, QCheckBox, QDoubleSpinBox,
    QInputDialog, QMenu, QColorDialog, QPushButton, QWidget, QVBoxLayout, QPlainTextEdit, QApplication,
)

import numpy as np
from core import features as F
from core import sketch_solver as K
from core.model import Document, STL_QUALITY
from core.ops import PLACEABLE
from viewer.quality import QUALITY, DEFAULT as DEFAULT_QUALITY
from viewer.scene import Scene, VIEWS
from core import measure as MS
from core import numfmt
from ui import session as S
from core import materials as MAT
from core import interference as IFC
from core.numfmt import fmtn, fmtl, fmta, fmtv
from viewer.measure_tool import TOOLS as MS_TOOLS, ANN_TOOLS
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
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._body_menu)
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._history_menu)
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
        self.ann_list = QListWidget()                   # 半徑/直徑標註清單
        self.ann_list.itemDoubleClicked.connect(lambda _: self.on_edit_annotation())
        adock = QDockWidget("標註(雙擊切換半徑/直徑)", self)
        adock.setWidget(self.ann_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, adock)
        hdock = QDockWidget("螺旋線(雙擊編輯)", self)
        hdock.setWidget(self.helix_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, hdock)
        sdock = QDockWidget("草圖(雙擊編輯)", self)
        sdock.setWidget(self.sketch_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, sdock)
        self.tabifyDockWidget(docks[0], sdock)
        self.tabifyDockWidget(docks[0], hdock)
        self.tabifyDockWidget(docks[0], adock)
        docks[0].raise_()
        self._build_measure_dock()
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
        numfmt.set_precision(int(QSettings("3DViewer", "3DViewer").value("precision", 3)))   # 量測精度預設 .3f
        u = QSettings("3DViewer", "3DViewer").value("unit", "mm")
        numfmt.set_unit(u if u in numfmt.UNITS else "mm")
        self.autosave_interval_ms = 60_000
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave_now)
        self.autosave_timer.start(self.autosave_interval_ms)
        self.quality_actions = {}
        saved = QSettings("3DViewer", "3DViewer").value("quality", DEFAULT_QUALITY)
        if saved in QUALITY:
            self.scene.quality = saved
            self.scene.set_quality(saved)
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
        self.recent_menu = m.addMenu("最近開啟的檔案")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        self._fill_recent()
        m.addSeparator()
        m.addAction(self._action("匯入 STEP...", self.on_import_step))
        m.addAction(self._action("匯出 STEP...", self.on_export_step))
        m.addAction(self._action("匯出 STL...", self.on_export_stl))
        m.addAction(self._action("輸出工程圖(PDF/SVG/PNG/DXF)...", self.on_drawing))
        m.addSeparator()
        m.addAction(self._action("結束", self.close, "Ctrl+Q"))

        e = bar.addMenu("編輯(&E)")
        self.act_undo = self._action("復原", self.on_undo, "Ctrl+Z")
        self.act_redo = self._action("重做", self.on_redo, "Ctrl+Y")
        e.addAction(self.act_undo)
        e.addAction(self.act_redo)
        e.addSeparator()
        e.addAction(self._action("變數與公式...", self.on_variables))
        e.addSeparator()
        e.addAction(self._action("編輯所選特徵參數...", self.on_edit_feature, "F2"))
        e.addAction(self._action("刪除所選特徵", self.on_delete_feature))
        e.addSeparator()
        e.addAction(self._action("抑制 / 取消抑制所選特徵", self.on_suppress_feature, "Ctrl+Shift+X"))
        e.addAction(self._action("重新命名所選特徵...", self.on_rename_feature))
        e.addAction(self._action("上移所選特徵", lambda _=None: self.on_move_feature(-1)))
        e.addAction(self._action("下移所選特徵", lambda _=None: self.on_move_feature(1)))
        e.addAction(self._action("回溯到所選特徵之後", self.on_rollback))
        e.addAction(self._action("回到最新(解除回溯)", self.on_rollback_end))

        c = bar.addMenu("建立(&C)")
        for kind in ("box", "cylinder", "sphere", "cone", "torus"):
            c.addAction(self._action(SCHEMAS[kind][0] + "...", lambda _, k=kind: self.on_create(k)))
        c.addAction(self._action("孔(簡單/沉頭/埋頭,於鎖定平面)...", self.on_hole))
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
        sk.addAction(self._action("草圖放樣(實體/切除)...", self.on_sketch_loft))
        sk.addAction(self._action("加肋(以開放輪廓草圖,於所選實體)...", self.on_rib))
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
        t.addAction(self._action("3D 陣列(線性/圓形)...", self.on_pattern))
        t.addAction(self._action("鏡射實體...", self.on_mirror))
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
        m2.addAction(self._action("抽殼(所選面為開口,未選則封閉空心)...", self.on_shell))
        m2.addAction(self._action("拔模(所選面)...", self.on_draft))

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

        ms = bar.addMenu("量測(&U)")
        for tool, (label, _, _) in MS_TOOLS.items():
            ms.addAction(self._action(label, lambda _, t=tool: self.on_measure(t)))
        ms.addSeparator()
        ms.addAction(self._action("所選實體的屬性(體積/表面積/質心)...", self.on_body_props))
        ms.addAction(self._action("質量屬性(含材料:質量/質心/慣性矩)...", self.on_mass_props))
        ms.addAction(self._action("干涉檢查(所有實體兩兩)...", self.on_interference))
        ms.addAction(self._action("量測小數位數...", self.on_precision))
        um = ms.addMenu("顯示單位")
        ug = QActionGroup(self)
        self.unit_actions = {}
        for u in numfmt.UNITS:
            act = self._action(u, lambda _=False, u=u: self.set_unit(u), checkable=True, checked=(u == numfmt.UNIT))
            ug.addAction(act)
            um.addAction(act)
            self.unit_actions[u] = act
        ms.addAction(self._action("清除畫面上的量測標註", self.on_measure_clear))
        ms.addAction(self._action("結束量測", self.on_measure_exit))

        an = bar.addMenu("標註(&N)")
        for tool, (label, _) in ANN_TOOLS.items():
            an.addAction(self._action(label, lambda _, t=tool: self.on_annotate_tool(t)))
        an.addSeparator()
        an.addAction(self._action("編輯所選標註(半徑/直徑)...", self.on_edit_annotation))
        an.addAction(self._action("刪除所選標註", self.on_delete_annotation))
        an.addAction(self._action("結束標註", self.on_measure_exit))

        v = bar.addMenu("檢視(&V)")
        for name in VIEWS:
            v.addAction(self._action(name, lambda _, n=name: self.scene.set_view(n)))
        v.addSeparator()
        v.addAction(self._action("線框模式", self.on_wireframe, checkable=True))
        v.addAction(self._action("顯示邊線", self.on_edges, checkable=True, checked=True))
        v.addAction(self._action("截面視圖...", self.on_section))
        v.addAction(self._action("關閉截面", self.on_section_off))
        v.addSeparator()
        v.addAction(self._action("全部顯示(取消隱藏)", self.on_show_all))
        qm = v.addMenu("顯示精細度(圓/曲面)")
        qgrp = QActionGroup(self)
        for name, q in QUALITY.items():
            act = self._action(f"{name}(弦高誤差 {q['tol']} mm)", lambda _, n=name: self.on_quality(n),
                               checkable=True, checked=(name == self.scene.quality))
            qgrp.addAction(act)
            qm.addAction(act)
            self.quality_actions[name] = act

    # --- 檔案 ---
    def _confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, APP, "目前專案尚未儲存,確定要放棄變更嗎?")
        return r == QMessageBox.Yes

    def closeEvent(self, ev):
        if self._confirm_discard():
            self.autosave_timer.stop()
            S.clear_backup()
            ev.accept()
        else:
            ev.ignore()

    def on_new(self):
        if self._confirm_discard():
            self.doc.clear()
            S.clear_backup()
            self._update()

    # --- 最近檔案 / 自動儲存 / 單位 ---
    def _fill_recent(self):
        self.recent_menu.clear()
        files = S.recent_files()
        for i, p in enumerate(files):
            self.recent_menu.addAction(self._action(f"&{i + 1} {p}", lambda _=False, p=p: self.open_recent(p)))
        if files:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction(self._action("清除清單", self.clear_recent))
        else:
            empty = self._action("(無)", lambda: None)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)

    def clear_recent(self):
        S.clear_recent()
        self._fill_recent()

    def open_recent(self, path):
        if not os.path.exists(path):
            S.remove_recent(path)
            self._fill_recent()
            QMessageBox.warning(self, APP, f"檔案不存在,已從清單移除:\n{path}")
            return
        if self._confirm_discard():
            self.load(path)

    def autosave_now(self) -> bool:
        """有未儲存的變更時寫入備份檔;回傳是否有寫入。"""
        if not self.doc.dirty or not self.doc.features:
            return False
        try:
            self.doc.write_backup(S.backup_path(), self.doc.path)
        except OSError:
            return False
        return True

    def check_recovery(self) -> bool:
        """啟動時呼叫:若上次異常結束留有備份,詢問是否恢復。"""
        info = S.read_backup_info()
        if info is None:
            return False
        src = info.get("source") or "未命名專案"
        r = QMessageBox.question(self, APP, f"偵測到上次未正常關閉留下的自動備份({src}),要恢復嗎?")
        if r == QMessageBox.Yes:
            return self.recover_backup()
        S.clear_backup()
        return False

    def recover_backup(self) -> bool:
        try:
            info = S.read_backup_info()
            self.doc.load_project(S.backup_path())
            self.doc.path = info.get("source") if info else None
            self.doc.dirty = True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "恢復失敗", str(e))
            return False
        self._report_errors()
        self._update()
        return True

    def set_unit(self, u):
        numfmt.set_unit(u)
        QSettings("3DViewer", "3DViewer").setValue("unit", u)
        if u in getattr(self, "unit_actions", {}):
            self.unit_actions[u].setChecked(True)
        self.statusBar().showMessage(f"量測與屬性顯示單位:{u}(建模輸入仍為 mm)")

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
        S.add_recent(path)
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
        S.add_recent(path)
        S.clear_backup()
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

    def on_drawing(self):
        """工程圖:三視圖 + 等角視、總尺寸與孔徑標註、標題欄;預覽後輸出 PDF/SVG/PNG/DXF。"""
        from PyQt5.QtGui import QPixmap
        from PyQt5.QtWidgets import QDialog, QScrollArea, QLabel as _Label
        from core import drawing as DR
        from ui.drawing_render import export_sheet, render_image
        ap = self.doc.appearance
        shapes = [b.shape for b in self.doc.bodies if ap.get(b.id, {}).get("visible", True)]
        if not shapes:
            QMessageBox.information(self, "工程圖", "目前沒有可繪製的實體")
            return
        name = os.path.splitext(os.path.basename(self.doc.path))[0] if self.doc.path else "未命名"
        v = ask("工程圖設定", [
            ("paper", "紙張(橫式)", "combo", list(DR.PAPERS)),
            ("proj", "投影法", "combo", ["第三角法", "第一角法"]),
            ("scale", "比例", "combo", ["自動", "1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "2:1", "5:1", "10:1"]),
            ("front", "前視圖", "bool", True), ("top", "上視圖", "bool", True), ("right", "右視圖", "bool", True),
            ("iso", "等角視", "bool", True), ("hidden", "顯示隱藏線(虛線)", "bool", True),
            ("dims", "標註總尺寸與孔徑", "bool", True),
            ("hole_pos", "孔位置座標尺寸(自視圖左下角量起)", "bool", True),
            ("radii", "圓角半徑 R 標註", "bool", True), ("chain", "分段(鏈式)尺寸", "bool", False),
            ("section", "剖視圖(與等角視共用右上位置,剖視優先)", "combo", list(DR.SECTION_LABELS)),
            ("sec_off", "剖切位置(相對零件中心,mm)", "num", 0),
            ("title", "圖名", "text", f"{name} 工程圖"), ("part", "零件名稱", "text", name),
            ("author", "設計者", "text", "")], self, initial={"paper": "A3"})
        if not v:
            return
        views = tuple(n for n, k in (("前視", "front"), ("上視", "top"), ("右視", "right"), ("等角視", "iso")) if v[k])
        if not views:
            QMessageBox.information(self, "工程圖", "請至少選一個視圖")
            return
        try:
            axis = DR.SECTION_LABELS[v["section"]]
            sheet = DR.build_sheet(shapes, views, v["paper"], v["proj"] == "第三角法", v["scale"],
                                   v["hidden"], v["dims"], {"title": v["title"], "part": v["part"],
                                                           "author": v["author"], "paper": v["paper"]},
                                   section={"axis": axis, "offset": v["sec_off"]} if axis else None,
                                   hole_pos=v["hole_pos"], radii=v["radii"], chain=v["chain"])
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "工程圖", f"產生失敗:{e}")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"工程圖預覽(比例 {sheet.scale[0]}:{sheet.scale[1]})")
        dlg.resize(1100, 820)
        lay = QVBoxLayout(dlg)
        lab = _Label()
        lab.setPixmap(QPixmap.fromImage(render_image(sheet, 80)))
        sc = QScrollArea()
        sc.setWidget(lab)
        lay.addWidget(sc)
        b_save = QPushButton("儲存為 PDF / SVG / PNG / DXF...")
        lay.addWidget(b_save)

        def save():
            path, flt = QFileDialog.getSaveFileName(
                dlg, "儲存工程圖", f"{name}.pdf", "PDF (*.pdf);;SVG (*.svg);;PNG (*.png);;DXF (*.dxf)")
            if not path:
                return
            if not path.lower().endswith((".pdf", ".svg", ".png", ".dxf")):
                path += "." + flt.split("(*.")[1].split(")")[0].split()[0]
            try:
                export_sheet(sheet, path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(dlg, "儲存失敗", str(e))
                return
            self.statusBar().showMessage(f"已輸出工程圖 {os.path.basename(path)}")

        b_save.clicked.connect(save)
        dlg.exec_()

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
        bad = [f"{f.title}: {f.error}" for f in self.doc.features if f.error]
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

    # --- 特徵:抑制 / 重新命名 / 排序 / 回溯 ---
    def _selected_feature(self):
        k = self.history.currentRow()
        if k < 0 or k >= len(self.doc.features):
            QMessageBox.information(self, "提示", "請先在特徵歷史選取一個特徵")
            return None
        return k

    def _keep_row(self, k):
        self._update(reset_camera=False)
        if 0 <= k < self.history.count():
            self.history.setCurrentRow(k)

    def on_suppress_feature(self):
        k = self._selected_feature()
        if k is not None:
            self.doc.set_suppressed(k, not self.doc.features[k].suppressed)
            self._keep_row(k)

    def on_rename_feature(self):
        k = self._selected_feature()
        if k is None:
            return
        name, ok = QInputDialog.getText(self, "重新命名特徵", "名稱(留空恢復預設):", text=self.doc.features[k].title)
        if ok:
            self.doc.rename_feature(k, name)
            self._keep_row(k)

    def on_move_feature(self, delta):
        k = self._selected_feature()
        if k is not None and self.doc.move_feature(k, delta):
            self._keep_row(k + delta)
            self._report_errors()

    def on_rollback(self):
        k = self._selected_feature()
        if k is not None:
            self.doc.set_rollback(k)
            self._keep_row(k)

    def on_rollback_end(self):
        self.doc.set_rollback(None)
        self._update(reset_camera=False)

    def _history_menu(self, pos):
        if self.history.itemAt(pos) is None:
            return
        self.history.setCurrentRow(self.history.row(self.history.itemAt(pos)))
        f = self.doc.features[self.history.currentRow()]
        m = QMenu(self)
        for text, slot in (("編輯參數...", self.on_edit_feature),
                           ("重新命名...", self.on_rename_feature),
                           ("取消抑制" if f.suppressed else "抑制", self.on_suppress_feature),
                           ("回溯到此特徵之後", self.on_rollback),
                           ("回到最新(解除回溯)", self.on_rollback_end),
                           ("上移", lambda: self.on_move_feature(-1)),
                           ("下移", lambda: self.on_move_feature(1)),
                           ("刪除", self.on_delete_feature)):
            m.addAction(text).triggered.connect(lambda _=False, s=slot: s())
        m.exec_(self.history.mapToGlobal(pos))

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

    # --- 量測 ---
    def _build_measure_dock(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        self.measure_text = QPlainTextEdit()
        self.measure_text.setReadOnly(True)
        lay.addWidget(self.measure_text)
        for text, slot in (("複製全部結果", self.on_measure_copy), ("清除結果與標註", self.on_measure_clear_all)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            lay.addWidget(b)
        self.measure_dock = QDockWidget("量測結果", self)
        self.measure_dock.setWidget(box)
        self.addDockWidget(Qt.RightDockWidgetArea, self.measure_dock)
        self.measure_dock.hide()
        self.scene.measure.on_annotate = self._annotate_pick
        self.scene.measure.on_result = lambda t: self.measure_text.appendPlainText(t + "\n")
        self.scene.measure.status = lambda m: self.statusBar().showMessage(m)

    def on_measure(self, tool):
        if not self.doc.bodies:
            QMessageBox.information(self, "量測", "目前沒有可量測的實體")
            return
        self.scene.set_mode("measure")
        self.scene.measure.set_tool(tool)
        self.measure_dock.show()

    def on_annotate_tool(self, tool):
        if not self.doc.bodies:
            QMessageBox.information(self, "標註", "目前沒有可標註的實體")
            return
        self.scene.set_mode("measure")
        self.scene.measure.set_tool(tool)

    def _annotate_pick(self, pick, mode):
        if pick.kind == "vertex":
            self.statusBar().showMessage("標註:請點選圓/圓弧邊、圓柱面或球面")
            return
        params = {"body": self.doc.bodies[pick.body].id, "kind": pick.kind, "index": pick.index,
                  "mode": mode, "at": [float(c) for c in pick.point]}
        err = self.doc.add_feature("annotation", params)
        if err:
            self.statusBar().showMessage(f"標註失敗:{err}")
            return
        self._update(reset_camera=False)
        self.statusBar().showMessage(f"已建立{mode}標註(存於特徵歷史,可在「標註」清單編輯/刪除)")

    def _selected_annotation(self):
        r = self.ann_list.currentRow()
        if r < 0 or r >= len(self.doc.annotations):
            QMessageBox.information(self, "標註", "請先在「標註」清單選取一個標註")
            return None
        return self.doc.annotations[r][0]

    def on_edit_annotation(self):
        aid = self._selected_annotation()
        if aid is None:
            return
        k = next(i for i, f in enumerate(self.doc.features) if f.kind == "annotation" and aid in f.out_ids)
        title, fields = SCHEMAS["annotation"]
        v = ask("編輯:" + title, fields, self, initial=self.doc.features[k].params)
        if v:
            self._run(lambda: self.doc.edit_feature(k, v))

    def on_delete_annotation(self):
        aid = self._selected_annotation()
        if aid is not None:
            self._run(lambda: self.doc.add_feature("delete", {"body": aid}))

    def on_body_material(self):
        bid = self._current_id()
        if bid is None:
            return
        cur = self.doc.materials.get(bid, {"material": MAT.DEFAULT_MATERIAL, "density": 1.0})
        v = ask("指定材料", [
            ("material", "材料", "combo", list(MAT.MATERIALS) + [MAT.CUSTOM]),
            ("density", "自訂密度 (g/cm³,選「自訂密度」時使用)", "num", cur["density"] if cur["material"] == MAT.CUSTOM else 1.0)],
            self, initial={"material": cur["material"]})
        if v:
            self._run(lambda: self.doc.add_feature("material", {"body": bid, **v}))

    def on_mass_props(self):
        """整體質量屬性:各實體依指定材料(未指定者用選定的預設材料)計算質量、質心與慣性矩。"""
        if not self.doc.bodies:
            QMessageBox.information(self, "質量屬性", "目前沒有實體")
            return
        v = ask("質量屬性", [("default", "未指定材料的實體以此計算", "combo", list(MAT.MATERIALS), ),
                             ("mark", "在畫面標出質心", "bool", True)], self, initial={"default": MAT.DEFAULT_MATERIAL})
        if not v:
            return
        mats = self.doc.materials
        items, notes = [], []
        for b in self.doc.bodies:
            if b.id in mats:
                name, dens = mats[b.id]["material"], mats[b.id]["density"]
            else:
                name, dens = v["default"], MAT.MATERIALS[v["default"]]
                notes.append(b.name)
            items.append((f"{b.name} [{name}]", b.shape, dens))
        r = MAT.assembly_props(items)
        f = fmtn
        I = r["inertia"]
        pm = MAT.principal_moments(I)
        lines = [f"整體質量屬性(共 {len(items)} 個實體)",
                 f"總質量:{f(r['mass'])} g({f(r['mass'] / 1000)} kg)",
                 f"總體積:{fmtv(r['volume'])} {numfmt.UNIT}³({f(r['volume'] / 1000)} cm³)",
                 f"質心:({fmtl(r['com'][0])}, {fmtl(r['com'][1])}, {fmtl(r['com'][2])}) {numfmt.UNIT}",
                 f"慣性矩(對質心,軸向平行座標軸,g·mm²):",
                 f"  Ixx={f(I[0][0])}  Iyy={f(I[1][1])}  Izz={f(I[2][2])}",
                 f"  Ixy={f(I[0][1])}  Ixz={f(I[0][2])}  Iyz={f(I[1][2])}",
                 f"主慣性矩:{f(pm[0])}, {f(pm[1])}, {f(pm[2])}", "", "各實體:"]
        for p in r["parts"]:
            lines.append(f"  {p['name']}:密度 {f(p['density'])} g/cm³,體積 {fmtv(p['volume'])} {numfmt.UNIT}³,質量 {f(p['mass'])} g")
        if notes:
            lines.append(f"\n※ 未指定材料的實體({'、'.join(notes)})以「{v['default']}」計算。")
        text = "\n".join(lines)
        self.measure_text.appendPlainText(text + "\n")
        self.measure_dock.show()
        if v["mark"]:
            self.scene.measure.add_marker(r["com"], "CoM")
        QMessageBox.information(self, "質量屬性", text)

    def on_interference(self):
        if len(self.doc.bodies) < 2:
            QMessageBox.information(self, "干涉檢查", "至少需要兩個實體")
            return
        v = ask("干涉檢查", [("contact", "同時列出僅接觸(貼合)的實體", "bool", True)], self)
        if not v:
            return
        res = IFC.check([(b.id, b.name, b.shape) for b in self.doc.bodies], include_contact=v["contact"])
        ms = self.scene.measure
        ms.items = [it for it in ms.items if it["label"][1] != "INT"]        # 只清掉上一次的干涉標示,保留其他量測
        ms.redraw()
        self.measure_dock.show()
        if not res:
            text = "干涉檢查:沒有發現干涉" + ("或接觸。" if v["contact"] else "。")
        else:
            from viewer.mesh import shape_to_mesh
            n_int = sum(1 for r in res if r["kind"] == "干涉")
            lines = [f"干涉檢查:{n_int} 組干涉" + (f"、{len(res) - n_int} 組接觸" if len(res) > n_int else "")]
            for r in res:
                c = r["center"]
                lines.append(f"  {r['a'][1]} ∩ {r['b'][1]}:{r['kind']}"
                             + (f",重疊體積 {fmtv(r['volume'])} {numfmt.UNIT}³" if r["kind"] == "干涉" else "")
                             + f",位置 ({fmtl(c.x)}, {fmtl(c.y)}, {fmtl(c.z)}) {numfmt.UNIT}")
                if r["shape"] is not None:
                    self.scene.measure.add_marker((c.x, c.y, c.z), "INT", mesh=shape_to_mesh(r["shape"], 0.02, 0.1))
            text = "\n".join(lines)
        self.measure_text.appendPlainText(text + "\n")
        self.statusBar().showMessage(text.splitlines()[0])
        QMessageBox.information(self, "干涉檢查", text)

    def on_precision(self):
        n, ok = QInputDialog.getInt(self, "量測小數位數", "最多顯示的小數位數(預設 3,即 .3f;整數仍顯示為整數):", numfmt.PRECISION, 0, 8)
        if ok:
            numfmt.set_precision(n)
            QSettings("3DViewer", "3DViewer").setValue("precision", n)
            self._update(reset_camera=False)
            self.statusBar().showMessage(f"量測與尺寸顯示改為小數 {n} 位(新的量測才套用)")

    def on_measure_exit(self):
        self.scene.set_mode("off")
        self.scene.measure.cancel()
        self.measure_dock.hide()

    def on_measure_clear(self):
        self.scene.measure.clear()

    def on_measure_clear_all(self):
        self.measure_text.clear()
        self.scene.measure.clear()

    def on_measure_copy(self):
        QApplication.clipboard().setText(self.measure_text.toPlainText())
        self.statusBar().showMessage("已複製量測結果")

    def on_body_props(self):
        bid = self._current_id()
        if bid is None:
            return
        body = next(b for b in self.doc.bodies if b.id == bid)
        p = MS.body_properties(body.shape)
        c = p["center"]
        f = fmtn
        U = numfmt.UNIT
        text = (f"實體:{body.name}\n體積:{fmtv(p['volume'])} {U}³\n表面積:{fmta(p['area'])} {U}²\n"
                f"質心:({fmtl(c.x)}, {fmtl(c.y)}, {fmtl(c.z)})\n"
                f"外型尺寸(X×Y×Z):{fmtl(p['size'][0])} × {fmtl(p['size'][1])} × {fmtl(p['size'][2])} {U}\n"
                f"邊界框:({fmtl(p['min'][0])}, {fmtl(p['min'][1])}, {fmtl(p['min'][2])}) ~ "
                f"({fmtl(p['max'][0])}, {fmtl(p['max'][1])}, {fmtl(p['max'][2])})")
        self.measure_text.appendPlainText(text + "\n")
        self.measure_dock.show()
        QMessageBox.information(self, "實體屬性", text)

    # --- 草圖 ---
    def _build_sketch_bar(self):
        bar = QToolBar("草圖工具", self)
        bar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.sk_bar = bar
        grp = QActionGroup(self)
        self.sk_tool_actions = {}
        for tool in ("select", "line", "rect", "circle", "arc", "ellipse", "spline", "trim", "fillet2d", "chamfer2d",
                     "offset", "delete"):
            act = QAction(SK_TOOLS[tool], self)
            act.setCheckable(True)
            act.triggered.connect(lambda _, t=tool: self._sk and self._sk["ed"].set_tool(t))
            grp.addAction(act)
            bar.addAction(act)
            self.sk_tool_actions[tool] = act
        bar.addSeparator()
        for text, slot, key in (("鏡射...", self.on_sk_mirror, None), ("陣列...", self.on_sk_pattern, None),
                                ("構造線切換", lambda: self._sk["ed"].toggle_construction(), None),
                                ("投影模型邊...", self.on_sk_project, None),
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
        v, ok = QInputDialog.getDouble(self, title, "數值:", current, -1e6, 1e6, 4)
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

    def on_sk_project(self):
        bodies = self.doc.bodies
        if not bodies:
            QMessageBox.information(self, "草圖", "沒有可投影的實體")
            return
        items = [f"{b.id}: {b.name}" for b in bodies]
        v = ask("投影模型邊到草圖平面", [("body", "實體", "combo", items),
                                         ("construction", "當作構造線(參考用,不形成輪廓)", "bool", True)], self)
        if v:
            bid = int(v["body"].split(":")[0])
            self._sk["ed"].project_shape(next(b.shape for b in bodies if b.id == bid), v["construction"])

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

    def on_sketch_loft(self):
        sketches, bodies = self.doc.sketches, self.doc.bodies
        if len(sketches) < 2:
            QMessageBox.information(self, "草圖放樣", "需要至少兩個封閉輪廓草圖(位於不同的平面/位置)")
            return
        items = [f"{i}: {n}" for i, n, _ in sketches]
        title, fields = SCHEMAS["sketch_loft"]
        pf = [(f"p{k}", f"輪廓 {k + 1}" + ("" if k < 2 else "(可不選)"), "combo", items if k < 2 else ["(無)"] + items)
              for k in range(4)]
        fields = pf + list(fields) + [("target", "目標實體(聯集/切除用)", "combo",
                                       [f"{b.id}: {b.name}" for b in bodies] or ["(無)"])]
        v = ask(title + "(依序通過各輪廓)", fields, self, initial={"p0": items[0], "p1": items[1]})
        if not v:
            return
        ids = [int(v[f"p{k}"].split(":")[0]) for k in range(4) if v[f"p{k}"] != "(無)"]
        params = {"profiles": ids, "ruled": v["ruled"], "op": v["op"]}
        if v["op"] != "新實體":
            if not bodies:
                QMessageBox.information(self, "草圖放樣", "沒有可作為目標的實體")
                return
            params["target"] = int(v["target"].split(":")[0])
        self._run(lambda: self.doc.add_feature("sketch_loft", params))

    def on_draft(self):
        s = self.scene
        if s.sel_body is None or not s.sel_faces:
            QMessageBox.information(self, "拔模", "請先用「選取模式:面」選取要拔模的面(可多選)")
            return
        body = self.doc.bodies[s.sel_body]
        title, fields = SCHEMAS["draft"]
        v = ask(title, fields, self, initial={"plane": "鎖定平面" if self.wp else "XY"})
        if not v:
            return
        params = {**v, "body": body.id, "faces": sorted(s.sel_faces)}
        if v["plane"] == "鎖定平面":
            if not self.wp:
                QMessageBox.information(self, "拔模", "請先鎖定平面(F3),或改選 XY/XZ/YZ")
                return
            params = self._with_lock(params)
        self._run(lambda: self.doc.add_feature("draft", params))

    def on_rib(self):
        bid = self._current_id()
        if bid is None:
            return
        sketches = self.doc.sketches
        if not sketches:
            QMessageBox.information(self, "加肋", "請先建立一個開放輪廓的草圖(相連的線/圓弧,畫在肋所在的平面上,輪廓為肋的外緣)")
            return
        items = [f"{i}: {n}" for i, n, _ in sketches]
        title, fields = SCHEMAS["rib"]
        v = ask(title + "(輪廓朝實體方向延伸至碰到實體)", [("sketch", "肋的輪廓草圖", "combo", items)] + list(fields), self,
                initial={"sketch": items[-1]})
        if v:
            params = {k: val for k, val in v.items() if k != "sketch"}
            self._run(lambda: self.doc.add_feature("rib", {**params, "body": bid, "sketch": int(v["sketch"].split(":")[0])}))

    def on_variables(self):
        """編輯變數與公式:每行「名稱 = 數字或算式」,後面的可引用前面的;特徵參數以 =名稱 引用。"""
        from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel
        dlg = QDialog(self)
        dlg.setWindowTitle("變數與公式")
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("每行一個:名稱 = 數字或算式(例如  孔徑 = 板厚 / 2 )。\n"
                             "特徵對話框的數值欄位輸入「=孔徑」即可引用;改這裡的值,相關特徵自動重算。"))
        edit = QPlainTextEdit()
        edit.setPlainText("\n".join(f"{k} = {v if isinstance(v, str) else format(v, '.10g')}"
                                    for k, v in self.doc.variables.items()))
        lay.addWidget(edit)
        preview = QLabel("")
        preview.setWordWrap(True)
        lay.addWidget(preview)

        def parse():
            out = {}
            for n, line in enumerate(edit.toPlainText().splitlines(), 1):
                if not line.strip():
                    continue
                if "=" not in line:
                    raise ValueError(f"第 {n} 行缺少 =")
                name, ex = (t.strip() for t in line.split("=", 1))
                if not name.isidentifier():
                    raise ValueError(f"第 {n} 行的名稱「{name}」無效(可用中英文、數字、底線,不可數字開頭)")
                out[name] = ex if not _is_number(ex) else float(ex)
            from core.expr import evaluate_all
            return out, evaluate_all(out)

        def check():
            try:
                _, vals = parse()
                preview.setText("結果:" + "  ".join(f"{k}={v:.6g}" for k, v in vals.items()))
            except ValueError as e:
                preview.setText(f"⚠ {e}")

        edit.textChanged.connect(check)
        check()
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("套用")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            variables, _ = parse()
        except ValueError as e:
            QMessageBox.warning(self, "變數與公式", str(e))
            return
        if self._run(lambda: self.doc.set_variables(variables)):
            self._report_errors()

    def on_delete_sketch(self):
        r = self.sketch_list.currentRow()
        if r < 0 or r >= len(self.doc.sketches):
            QMessageBox.information(self, "草圖", "請先在「草圖」清單選取一個草圖")
            return
        sid = self.doc.sketches[r][0]
        self._run(lambda: self.doc.add_feature("delete", {"body": sid}))

    # --- 3D 陣列 / 鏡射 / 孔 / 抽殼 ---
    def _with_lock(self, params):
        """若有鎖定平面,把它(與參考面綁定)寫進參數。"""
        if self.wp:
            params["wp"] = self.wp
            if self.wp_id is not None:
                params["plane_id"] = self.wp_id
        return params

    def on_pattern(self):
        bid = self._current_id()
        if bid is None:
            return
        title, fields = SCHEMAS["pattern"]
        v = ask(title, fields, self)
        if not v:
            return
        if v["kind"] == "圓形" and v["axis"].startswith("鎖定") and not self.wp:
            QMessageBox.information(self, "3D 陣列", "旋轉軸選了「鎖定平面法向」,請先鎖定平面(F3)")
            return
        self._run(lambda: self.doc.add_feature("pattern", self._with_lock({**v, "body": bid})))

    def on_mirror(self):
        bid = self._current_id()
        if bid is None:
            return
        title, fields = SCHEMAS["mirror"]
        v = ask(title, fields, self, initial={"plane": "鎖定平面" if self.wp else "YZ"})
        if not v:
            return
        if v["plane"] == "鎖定平面" and not self.wp:
            QMessageBox.information(self, "鏡射實體", "請先鎖定平面(F3),或改選 XY/XZ/YZ")
            return
        self._run(lambda: self.doc.add_feature(
            "mirror", self._with_lock({**v, "body": bid}) if v["plane"] == "鎖定平面" else {**v, "body": bid}))

    def on_hole(self):
        bid = self._current_id()
        if bid is None:
            return
        if not self.wp:
            QMessageBox.information(self, "孔", "請先鎖定平面(選取實體上的面後按 F3):孔從該平面往實體內鑽")
            return
        title, fields = SCHEMAS["hole"]
        v = ask(title, fields, self)
        if v:
            self._run(lambda: self.doc.add_feature("hole", self._with_lock({**v, "body": bid})))

    def on_shell(self):
        s = self.scene
        if s.sel_body is None:
            QMessageBox.information(self, "抽殼", "請先用「選取模式:面」選取要開口的面(不選則做封閉空心)")
            return
        body = self.doc.bodies[s.sel_body]
        title, fields = SCHEMAS["shell"]
        v = ask(title, fields, self)
        if v:
            self._run(lambda: self.doc.add_feature(
                "shell", {**v, "body": body.id, "faces": sorted(s.sel_faces)}))

    # --- 外觀 / 截面 ---
    def _body_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentRow(self.tree.row(item))
        bid = self.doc.bodies[self.tree.currentRow()].id
        hidden = not self.doc.appearance.get(bid, {}).get("visible", True)
        m = QMenu(self)
        for text, slot in (("材料...", self.on_body_material),
                           ("顏色...", self.on_body_color), ("透明度...", self.on_body_opacity),
                           ("顯示" if hidden else "隱藏", self.on_body_toggle),
                           ("重設外觀", self.on_body_reset),
                           ("所選實體的屬性...", self.on_body_props), ("刪除實體", self.on_delete_body)):
            m.addAction(text).triggered.connect(lambda _=False, s=slot: s())
        m.exec_(self.tree.mapToGlobal(pos))

    def _appearance(self, **kw):
        bid = self._current_id()
        if bid is not None:
            self._run(lambda: self.doc.add_feature("appearance", {"body": bid, **kw}))

    def on_body_color(self):
        c = QColorDialog.getColor(QColor("#8fb8de"), self, "選擇實體顏色")
        if c.isValid():
            self._appearance(color=c.name())

    def on_body_opacity(self):
        v, ok = QInputDialog.getInt(self, "透明度", "不透明度(%,5~100):", 100, 5, 100)
        if ok:
            self._appearance(opacity=v / 100.0)

    def on_body_toggle(self):
        bid = self._current_id()
        if bid is not None:
            visible = self.doc.appearance.get(bid, {}).get("visible", True)
            self._appearance(visible=not visible)

    def on_body_reset(self):
        self._appearance(color=None, opacity=1.0, visible=True)

    def on_show_all(self):
        for b in self.doc.bodies:
            if not self.doc.appearance.get(b.id, {}).get("visible", True):
                self.doc.add_feature("appearance", {"body": b.id, "visible": True})
        self._update(reset_camera=False)

    def on_section(self):
        v = ask("截面視圖(切掉平面法向正側)", [
            ("plane", "截面平面", "combo", ["XY", "XZ", "YZ", "鎖定平面"]),
            ("offset", "沿法向的位置(偏移)", "num", 0), ("flip", "反向(保留另一側)", "bool", False)], self,
            initial={"plane": "鎖定平面" if self.wp else "XZ"})
        if not v:
            return
        if v["plane"] == "鎖定平面":
            if not self.wp:
                QMessageBox.information(self, "截面視圖", "請先鎖定平面(F3),或改選 XY/XZ/YZ")
                return
            wp = self.wp
        else:
            wp = F.WORLD_PLANES[v["plane"]]
        n = np.array(wp["normal"], float) * (-1 if v["flip"] else 1)
        self.scene.set_section(np.array(wp["origin"], float) + n * v["offset"], n)
        self.statusBar().showMessage("截面已啟用(「檢視 → 關閉截面」可取消)")

    def on_section_off(self):
        self.scene.set_section(None, None)

    # --- 檢視 ---
    def on_quality(self, name):
        self.scene.set_quality(name)
        QSettings("3DViewer", "3DViewer").setValue("quality", name)
        self.statusBar().showMessage(f"顯示精細度:{name}(只影響畫面,不影響模型與匯出)")

    def on_wireframe(self, on):
        self.scene.wireframe = on
        self.scene.refresh(self.doc, reset_camera=False)

    def on_edges(self, on):
        self.scene.show_edges = on
        self.scene.refresh(self.doc, reset_camera=False)

    def _update(self, reset_camera=True):
        self.scene.measure.clear()                         # 模型改變後舊的量測標註已失效
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
        ap = self.doc.appearance
        mats = self.doc.materials
        self.tree.addItems([f"{b.id}: {b.name}" + (f" [{mats[b.id]['material']}]" if b.id in mats else "")
                            + ("(隱藏)" if not ap.get(b.id, {}).get("visible", True) else "")
                            for b in self.doc.bodies])
        self.ann_list.clear()
        self.ann_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.annotations])
        self.helix_list.clear()
        self.helix_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.helices])
        self.sketch_list.clear()
        self.sketch_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.sketches])
        self.planes_list.clear()
        self.planes_list.addItems([f"{i}: {n}" for i, n, _ in self.doc.planes])
        self.history.clear()
        rb = self.doc.rollback
        for k, f in enumerate(self.doc.features):
            text = f"{k + 1}. {f.title}" + ("  [已抑制]" if f.suppressed else "") \
                + (f"  ⚠ {f.error}" if f.error else "") + ("   ◀ 回溯點" if rb == k else "")
            item = QListWidgetItem(text)
            if f.suppressed or (rb is not None and k > rb):
                item.setForeground(QBrush(QColor("#8a8a8a")))
                font = QFont()
                font.setItalic(True)
                item.setFont(font)
            self.history.addItem(item)
        self.act_undo.setEnabled(self.doc.can_undo())
        self.act_redo.setEnabled(self.doc.can_redo())
        name = os.path.basename(self.doc.path) if self.doc.path else "未命名"
        self.setWindowTitle(f"{APP} - {name}{' *' if self.doc.dirty else ''}")
        self.statusBar().showMessage(f"共 {len(self.doc.bodies)} 個實體、{len(self.doc.features)} 個特徵")


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
