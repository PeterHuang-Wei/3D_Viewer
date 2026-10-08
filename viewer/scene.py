"""3D 視窗:封裝 pyvistaqt 的 QtInteractor。"""
from pyvistaqt import QtInteractor

from core.model import Document
import vtk

from .mesh import shape_to_mesh, shape_to_edges
from .picking import EdgeIndex, face_at, nearest_body

COLORS = ["#8fb8de", "#e0a96d", "#9bc59d", "#c9a0dc", "#d9777a"]

# 標準視角: (視線方向, 向上方向)
VIEWS = {
    "前視": ((0, -1, 0), (0, 0, 1)),
    "後視": ((0, 1, 0), (0, 0, 1)),
    "右視": ((1, 0, 0), (0, 0, 1)),
    "左視": ((-1, 0, 0), (0, 0, 1)),
    "上視": ((0, 0, -1), (0, 1, 0)),
    "下視": ((0, 0, 1), (0, -1, 0)),
    "等角視": ((-1, -1, -1), (0, 0, 1)),
}


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
        it = self.plotter.iren.interactor
        it.AddObserver("LeftButtonPressEvent", self._on_press, 10.0)
        it.AddObserver("LeftButtonReleaseEvent", self._on_release, 10.0)

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

    def _on_press(self, obj, _evt):
        self._press = obj.GetEventPosition()

    def _on_release(self, obj, _evt):
        if self.mode == "off" or self._press is None:
            return
        x, y = obj.GetEventPosition()
        px, py = self._press
        self._press = None
        if abs(x - px) > 3 or abs(y - py) > 3:  # 拖曳(旋轉視角)不算點選
            return
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        if not picker.Pick(x, y, 0, self.plotter.renderer):
            return
        self.pick_point(picker.GetPickPosition())

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
