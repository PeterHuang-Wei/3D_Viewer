"""3D 視窗:封裝 pyvistaqt 的 QtInteractor。"""
import numpy as np
from PyQt5.QtCore import QEvent, QObject, Qt
from pyvistaqt import QtInteractor

from core.model import Document
import vtk

from .mesh import shape_to_mesh, shape_to_edges
from .sketch_editor import lines_poly
from core import sketch2d as SK
from .picking import EdgeIndex, face_at, nearest_body, constrain_delta

COLORS = ["#8fb8de", "#e0a96d", "#9bc59d", "#c9a0dc", "#d9777a"]

# 標準視角: (相機相對於物體的位置方向, 向上方向)
VIEWS = {
    "前視": ((0, -1, 0), (0, 0, 1)),
    "後視": ((0, 1, 0), (0, 0, 1)),
    "右視": ((1, 0, 0), (0, 0, 1)),
    "左視": ((-1, 0, 0), (0, 0, 1)),
    "上視": ((0, 0, 1), (0, 1, 0)),
    "下視": ((0, 0, -1), (0, -1, 0)),
    "等角視": ((1, -1, 1), (0, 0, 1)),
}


class _MouseFilter(QObject):
    """把 3D 視窗的滑鼠/鍵盤事件交給 Scene 處理。"""

    def __init__(self, scene):
        super().__init__()
        self.scene = scene

    def eventFilter(self, obj, ev):
        t = ev.type()
        left = getattr(ev, "button", lambda: None)() == Qt.LeftButton
        if t == QEvent.MouseButtonPress and left:
            return self.scene.qt_press(ev)
        right = getattr(ev, "button", lambda: None)() == Qt.RightButton
        if right and t == QEvent.MouseButtonPress:
            self.scene._rpress = self.scene._disp(ev)
        if right and t == QEvent.MouseButtonRelease:
            self.scene.qt_right_click(ev)
        if t == QEvent.MouseMove:
            return self.scene.qt_move(ev)
        if t == QEvent.MouseButtonRelease and left:
            return self.scene.qt_release(ev)
        if t in (QEvent.KeyPress, QEvent.KeyRelease):
            key = ev.text().lower()
            if key in ("x", "y", "z") and not ev.isAutoRepeat():
                (self.scene._keys.add if t == QEvent.KeyPress else self.scene._keys.discard)(key)
        return False


class Scene:
    def __init__(self, parent=None):
        self.plotter = QtInteractor(parent)
        self.plotter.set_background("#2b2f36", top="#4a5160")
        self.plotter.add_axes()
        self.wireframe = False
        self.show_edges = True
        # 選取狀態:模式 off/edge/face;只允許選同一個實體內的邊或面
        self.mode = "off"
        self.sel_body = None
        self.sel_edges: set[int] = set()
        self.sel_faces: set[int] = set()
        self.on_selection = None  # 選取改變時的回呼
        self._doc = None
        self._meshes, self._edge_idx, self._edge_polys = [], [], []
        self._press = None
        self.locked = None  # 鎖定的工作平面 dict(origin/xdir/normal)
        self.lock_id = None  # 若鎖定的是參考面,其編號
        self.sketch = None  # 進行中的 SketchEditor
        self.hide_sketch = None  # 編輯中而暫時隱藏的草圖編號
        self._rpress = None
        # 滑鼠/鍵盤改由 Qt 事件過濾器處理(VTK 的放開事件在部分版本不會送到觀察者)
        self._filter = _MouseFilter(self)
        self.plotter.installEventFilter(self._filter)
        # 移動模式:on_move(body_index, (dx, dy, dz)) 於放開滑鼠時回呼
        self.on_move = None
        self._keys: set[str] = set()
        self._drag = None  # (body, 起點世界座標, 起點深度, 目前位移)

    @property
    def widget(self):
        return self.plotter

    def refresh(self, doc: Document, reset_camera: bool = True) -> None:
        self._doc = doc
        self.clear_selection(notify=False)
        self.plotter.clear()
        self.plotter.add_axes()
        self._meshes, self._edge_idx, self._edge_polys = [], [], []
        for i, body in enumerate(doc.bodies):
            mesh = shape_to_mesh(body.shape)
            edges = shape_to_edges(body.shape)
            self._meshes.append(mesh)
            self._edge_polys.append(edges)
            self._edge_idx.append(EdgeIndex(edges))
            if mesh.n_cells == 0:
                continue
            self.plotter.add_mesh(
                mesh, color=COLORS[i % len(COLORS)], smooth_shading=True,
                style="wireframe" if self.wireframe else "surface",
                name=f"body{i}",
            )
            if self.show_edges and not self.wireframe:
                self.plotter.add_mesh(
                    edges, color="black",
                    line_width=1.5, name=f"edge{i}",
                )
        self._draw_planes()
        self._draw_sketches()
        self._draw_lock(render=False)
        if reset_camera:
            self.set_view("等角視")

    def set_view(self, name: str) -> None:
        direction, up = VIEWS[name]
        self.plotter.view_vector(direction, viewup=up)
        self.plotter.reset_camera()

    # --- 選取 ---
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.clear_selection()

    def clear_selection(self, notify: bool = True) -> None:
        self.sel_body, self.sel_edges, self.sel_faces = None, set(), set()
        self._draw_selection()
        if notify and self.on_selection:
            self.on_selection()

    def _world_at(self, x, y, depth):
        r = self.plotter.renderer
        r.SetDisplayPoint(x, y, depth)
        r.DisplayToWorld()
        w = r.GetWorldPoint()
        return np.array(w[:3]) / w[3]

    def _disp(self, ev):
        """Qt 事件座標 -> VTK 顯示座標(裝置像素,原點在左下)。"""
        w = self.plotter
        scale = w.devicePixelRatioF()
        return round(ev.x() * scale), round((w.height() - ev.y() - 1) * scale)

    def _pick_at(self, x, y):
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        if not picker.Pick(x, y, 0, self.plotter.renderer):
            return None
        return np.array(picker.GetPickPosition())

    def qt_right_click(self, ev):
        """草圖模式下,右鍵點一下(未拖曳)結束目前的連續操作。"""
        if self.mode == "sketch" and self.sketch and self._rpress is not None:
            x, y = self._disp(ev)
            if abs(x - self._rpress[0]) <= 3 and abs(y - self._rpress[1]) <= 3:
                self.sketch.cancel_op()
        self._rpress = None

    def qt_press(self, ev) -> bool:
        """回傳 True 表示事件已處理(不再交給 VTK 旋轉視角)。"""
        self._press = self._disp(ev)
        if self.mode != "move":
            return False
        p = self._pick_at(*self._press)
        body = None if p is None else nearest_body(self._meshes, p)
        if body is None:
            return False
        r = self.plotter.renderer
        r.SetWorldPoint(*p, 1.0)
        r.WorldToDisplay()
        self._drag = (body, p, r.GetDisplayPoint()[2], np.zeros(3))
        return True

    def qt_move(self, ev) -> bool:
        if self.mode == "sketch" and self.sketch:
            self.sketch.hover(*self._disp(ev))
            return False
        if self._drag is None:
            return False
        body, p0, depth, _ = self._drag
        x, y = self._disp(ev)
        delta = constrain_delta(self._world_at(x, y, depth) - p0, self._keys)
        self._drag = (body, p0, depth, delta)
        for name in (f"body{body}", f"edge{body}"):
            actor = self.plotter.renderer.actors.get(name)
            if actor is not None:
                actor.SetPosition(*delta)
        self.plotter.render()
        return True

    def _finish_drag(self):
        body, _, _, delta = self._drag
        self._drag = None
        if np.linalg.norm(delta) > 1e-6:
            if self.on_move:
                self.on_move(body, tuple(round(float(v), 4) for v in delta))
        else:
            self.plotter.render()

    def qt_release(self, ev) -> bool:
        if self._drag is not None:
            self._press = None
            self._finish_drag()
            return True
        if self.mode == "sketch" and self.sketch and self._press is not None:
            x, y = self._disp(ev)
            if abs(x - self._press[0]) <= 3 and abs(y - self._press[1]) <= 3:
                self.sketch.click(x, y)
            self._press = None
            return False
        if self.mode not in ("edge", "face") or self._press is None:
            return False
        x, y = self._disp(ev)
        px, py = self._press
        self._press = None
        if abs(x - px) > 3 or abs(y - py) > 3:  # 拖曳(旋轉視角)不算點選
            return False
        p = self._pick_at(x, y)
        if p is not None:
            self.pick_point(p)
        return False

    def pick_point(self, p) -> None:
        """在 3D 位置 p 選取(依目前模式選最近的邊或面,再次點擊同一個則取消)。"""
        body = nearest_body(self._meshes, p)
        if body is None or self.mode == "off":
            return
        if body != self.sel_body:
            self.sel_edges, self.sel_faces, self.sel_body = set(), set(), body
        if self.mode == "edge":
            eid = self._edge_idx[body].nearest(p)
            if eid is not None:
                self.sel_edges ^= {eid}
        else:
            fid = face_at(self._meshes[body], p)
            if fid is not None:
                self.sel_faces ^= {fid}
        self._draw_selection()
        if self.on_selection:
            self.on_selection()

    def _draw_selection(self) -> None:
        for name in ("sel_edges", "sel_faces"):
            self.plotter.remove_actor(name, render=False)
        b = self.sel_body
        if b is not None and self._doc is not None and b < len(self._meshes):
            if self.sel_edges:
                poly = self._edge_polys[b]
                ids = poly.cell_data["edge_id"]
                sub = poly.extract_cells([i for i, e in enumerate(ids) if e in self.sel_edges])
                self.plotter.add_mesh(sub, color="red", line_width=5, name="sel_edges",
                                      render_lines_as_tubes=True, pickable=False)
            if self.sel_faces:
                m = self._meshes[b]
                ids = m.cell_data["face_id"]
                sub = m.extract_cells([i for i, f in enumerate(ids) if f in self.sel_faces])
                self.plotter.add_mesh(sub, color="orange", name="sel_faces", pickable=False)
        self.plotter.render()

    # --- 鎖定平面 ---
    def set_lock(self, wp, plane_id=None) -> None:
        self.locked, self.lock_id = wp, plane_id
        self._draw_planes()
        self._draw_lock()

    def _plane_size(self) -> float:
        sizes = [np.linalg.norm(np.array(m.bounds[1::2]) - np.array(m.bounds[0::2]))
                 for m in self._meshes if m.n_cells]
        return max(sizes, default=40.0) * 0.6

    def _draw_sketches(self) -> None:
        """畫出文件中所有草圖(橘色線)。"""
        for name in [n for n in self.plotter.renderer.actors if str(n).startswith("sketchobj")]:
            self.plotter.remove_actor(name, render=False)
        if self._doc is None:
            return
        for sid, _, sk in self._doc.sketches:
            if sid != self.hide_sketch and sk["entities"]:
                self.plotter.add_mesh(lines_poly(SK.polylines_global(sk["entities"], sk["wp"])),
                                      color="#ff8c00", line_width=2.5, name=f"sketchobj{sid}",
                                      pickable=False)

    def _draw_planes(self) -> None:
        """畫出所有參考面(被鎖定的那個由 _draw_lock 以青色畫)。"""
        import pyvista as pv
        for name in [n for n in self.plotter.renderer.actors if str(n).startswith("refplane")]:
            self.plotter.remove_actor(name, render=False)
        if self._doc is None:
            return
        size = self._plane_size()
        for pid, pname, wp in self._doc.planes:
            if pid == self.lock_id:
                continue
            o, n = np.array(wp["origin"]), np.array(wp["normal"])
            self.plotter.add_mesh(pv.Plane(center=o, direction=n, i_size=size, j_size=size),
                                  color="#7aa2ff", opacity=0.18, name=f"refplane{pid}", pickable=False)
            self.plotter.add_point_labels([o], [pname], name=f"refplane_label{pid}",
                                          font_size=12, shape=None, show_points=False,
                                          always_visible=True, pickable=False)

    def _draw_lock(self, render: bool = True) -> None:
        self.plotter.remove_actor("lock_plane", render=False)
        self.plotter.remove_actor("lock_normal", render=False)
        if self.locked:
            import pyvista as pv
            origin, normal = np.array(self.locked["origin"]), np.array(self.locked["normal"])
            size = self._plane_size()
            self.plotter.add_mesh(pv.Plane(center=origin, direction=normal, i_size=size, j_size=size),
                                  color="cyan", opacity=0.1 if self.mode == "sketch" else 0.25,
                                  name="lock_plane", pickable=False)
            if self.mode != "sketch":
                self.plotter.add_mesh(pv.Arrow(start=origin, direction=normal, scale=size * 0.25),
                                      color="cyan", name="lock_normal", pickable=False)
        if render:
            self.plotter.render()
