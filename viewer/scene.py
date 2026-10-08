"""3D 視窗:封裝 pyvistaqt 的 QtInteractor。"""
from pyvistaqt import QtInteractor

from core.model import Document
from .mesh import shape_to_mesh, shape_to_edges

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

    @property
    def widget(self):
        return self.plotter

    def refresh(self, doc: Document, reset_camera: bool = True) -> None:
        self.plotter.clear()
        self.plotter.add_axes()
        for i, body in enumerate(doc.bodies):
            mesh = shape_to_mesh(body.shape)
            if mesh.n_cells == 0:
                continue
            self.plotter.add_mesh(
                mesh, color=COLORS[i % len(COLORS)], smooth_shading=True,
                style="wireframe" if self.wireframe else "surface",
                name=f"body{i}",
            )
            if self.show_edges and not self.wireframe:
                self.plotter.add_mesh(
                    shape_to_edges(body.shape), color="black",
                    line_width=1.5, name=f"edge{i}",
                )
        if reset_camera:
            self.set_view("等角視")

    def set_view(self, name: str) -> None:
        direction, up = VIEWS[name]
        self.plotter.view_vector(direction, viewup=up)
        self.plotter.reset_camera()
