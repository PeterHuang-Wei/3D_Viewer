"""視角方塊(ViewCube):右上角的六面體,點選面/邊/角即可切換視角;另有 HOME 按鈕回到初始視角。"""
import numpy as np
import pyvista as pv
import vtk
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter
from PyQt5.QtWidgets import QPushButton

SIZE = 140          # 方塊區域邊長(像素)
MARGIN = 10
EDGE_ZONE = 0.6     # 面上座標絕對值超過此值視為邊/角

# 面: 名稱 -> (外向法向, 螢幕向上方向)
FACES = {
    "前": ((0, -1, 0), (0, 0, 1)), "後": ((0, 1, 0), (0, 0, 1)),
    "右": ((1, 0, 0), (0, 0, 1)), "左": ((-1, 0, 0), (0, 0, 1)),
    "上": ((0, 0, 1), (0, 1, 0)), "下": ((0, 0, -1), (0, -1, 0)),
}


def view_for_direction(d):
    """相機相對物體的方向 d(各軸 -1/0/1)-> (方向, 向上向量)。純上/下視圖用 Y 當向上。"""
    d = tuple(float(v) for v in d)
    if d[0] == 0 and d[1] == 0:
        return d, (0.0, 1.0, 0.0) if d[2] > 0 else (0.0, -1.0, 0.0)
    return d, (0.0, 0.0, 1.0)


def classify(face_normal, p) -> tuple:
    """點選位置 p(立方體座標,面在 ±1)-> 方向向量:面中央為單軸,靠邊為兩軸(邊),靠角為三軸(角)。"""
    n = np.asarray(face_normal, float)
    d = np.zeros(3)
    for i in range(3):
        if abs(n[i]) > 0.5:
            d[i] = np.sign(n[i])
        elif abs(p[i]) > EDGE_ZONE:
            d[i] = np.sign(p[i])
    return tuple(d)


def _face_texture(text: str) -> pv.Texture:
    img = QImage(128, 128, QImage.Format_RGB888)
    img.fill(QColor("#dfe6ee"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor("#8a97a8"))
    p.drawRect(1, 1, 125, 125)
    font = QFont()
    font.setPixelSize(72)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#2b3a4a"))
    p.drawText(img.rect(), Qt.AlignCenter, text)
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    arr = np.frombuffer(ptr, np.uint8).reshape(128, img.bytesPerLine())[:, :128 * 3].reshape(128, 128, 3)
    return pv.numpy_to_texture(np.ascontiguousarray(arr))


def _face_mesh(normal, up) -> pv.PolyData:
    n, u = np.asarray(normal, float), np.asarray(up, float)
    r = np.cross(-n, u)                                   # 從外側看該面時的「右」
    pts = np.array([n - r - u, n + r - u, n + r + u, n - r + u])
    mesh = pv.PolyData(pts, faces=np.array([4, 0, 1, 2, 3]))
    mesh.active_texture_coordinates = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    return mesh


class ViewCube:
    def __init__(self, scene):
        self.scene = scene
        pl = scene.plotter
        self.ren = vtk.vtkRenderer()
        pl.render_window.SetNumberOfLayers(2)
        self.ren.SetLayer(1)
        self.ren.InteractiveOff()
        pl.render_window.AddRenderer(self.ren)
        self.picker = vtk.vtkCellPicker()
        self.picker.PickFromListOn()
        self.face_of = {}
        for name, (n, u) in FACES.items():
            mesh = _face_mesh(n, u)
            actor = vtk.vtkActor()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(mesh)
            actor.SetMapper(mapper)
            actor.SetTexture(_face_texture(name))
            actor.GetProperty().LightingOff()
            self.ren.AddActor(actor)
            self.picker.AddPickList(actor)
            self.face_of[actor] = n
        outline = pv.Cube(x_length=2, y_length=2, z_length=2).extract_all_edges()
        oa = vtk.vtkActor()
        om = vtk.vtkPolyDataMapper()
        om.SetInputData(outline)
        oa.SetMapper(om)
        oa.GetProperty().SetColor(0.15, 0.2, 0.28)
        oa.GetProperty().SetLineWidth(2)
        oa.GetProperty().LightingOff()
        self.ren.AddActor(oa)
        self.ren.GetActiveCamera().SetViewAngle(30)
        pl.render_window.AddObserver("StartEvent", self._sync_camera)

        self.home = QPushButton("HOME", pl)
        self.home.setCursor(Qt.PointingHandCursor)
        self.home.setToolTip("回到初始視角(等角視、全部顯示)")
        self.home.setStyleSheet(
            "QPushButton{background:rgba(40,50,64,170);color:#e8eef5;border:1px solid #8a97a8;"
            "border-radius:4px;font-weight:bold;padding:2px 6px}"
            "QPushButton:hover{background:rgba(80,100,130,220)}")
        self.home.clicked.connect(lambda: scene.go_home())
        self.layout()

    # --- 版面 ---
    def layout(self):
        pl = self.scene.plotter
        w, h = max(pl.width(), 1), max(pl.height(), 1)
        scale = pl.devicePixelRatioF()
        x0, y0 = (w - SIZE - MARGIN), (h - SIZE - MARGIN)
        self.ren.SetViewport(x0 / w, 1 - (MARGIN + SIZE) / h, (w - MARGIN) / w, 1 - MARGIN / h)
        self.home.setGeometry(w - MARGIN - 62, MARGIN + SIZE + 4, 62, 24)
        self.home.raise_()
        self._rect = (x0, MARGIN, SIZE, SIZE)   # Qt 座標(左上原點): x, y, w, h
        self._scale = scale

    def contains(self, qx, qy) -> bool:
        x, y, w, h = self._rect
        return x <= qx <= x + w and y <= qy <= y + h

    def _sync_camera(self, *_):
        """方塊的相機方向永遠與主相機一致。"""
        cam = self.scene.plotter.renderer.GetActiveCamera()
        pos, foc = np.array(cam.GetPosition()), np.array(cam.GetFocalPoint())
        d = pos - foc
        n = np.linalg.norm(d)
        if n < 1e-12:
            return
        c = self.ren.GetActiveCamera()
        c.SetFocalPoint(0, 0, 0)
        c.SetPosition(*(d / n * 7.5))
        c.SetViewUp(*cam.GetViewUp())
        self.ren.ResetCameraClippingRange()

    # --- 點選 ---
    def click(self, qx, qy) -> bool:
        """點選方塊:切換視角並回傳 True;沒點到方塊則回傳 False。"""
        pl = self.scene.plotter
        x = round(qx * self._scale)
        y = round((pl.height() - qy - 1) * self._scale)
        if not self.picker.Pick(x, y, 0, self.ren):
            return False
        actor = self.picker.GetActor()
        p = np.array(self.picker.GetPickPosition())
        self.scene.set_view_dir(*view_for_direction(classify(self.face_of[actor], p)))
        return True
