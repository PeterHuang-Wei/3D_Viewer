"""選取邏輯(與 GUI 無關,可單獨測試)。"""
import numpy as np
import pyvista as pv


class EdgeIndex:
    """把邊折線拆成線段,供「點到最近邊」查詢。"""

    def __init__(self, edges: pv.PolyData):
        a, b, ids = [], [], []
        if edges.n_cells:
            lines = edges.lines
            pts = edges.points
            i = 0
            eid = edges.cell_data["edge_id"]
            for c in range(edges.n_cells):
                n = lines[i]
                idx = lines[i + 1:i + 1 + n]
                a.append(pts[idx[:-1]])
                b.append(pts[idx[1:]])
                ids.extend([eid[c]] * (n - 1))
                i += n + 1
        self.a = np.vstack(a) if a else np.zeros((0, 3))
        self.b = np.vstack(b) if b else np.zeros((0, 3))
        self.ids = np.asarray(ids, dtype=int)

    def nearest(self, p) -> int | None:
        if not len(self.ids):
            return None
        ab = self.b - self.a
        t = np.einsum("ij,ij->i", np.asarray(p) - self.a, ab) / np.maximum(
            np.einsum("ij,ij->i", ab, ab), 1e-12)
        proj = self.a + np.clip(t, 0, 1)[:, None] * ab
        d = np.linalg.norm(proj - p, axis=1)
        return int(self.ids[np.argmin(d)])


def face_at(mesh: pv.PolyData, p) -> int | None:
    if mesh.n_cells == 0:
        return None
    return int(mesh.cell_data["face_id"][mesh.find_closest_cell(p)])


def nearest_body(meshes, p) -> int | None:
    """點 p 距離哪個網格最近。"""
    best, best_d = None, 1e300
    for i, m in enumerate(meshes):
        if m.n_cells == 0:
            continue
        d = np.linalg.norm(m.points[m.find_closest_point(p)] - p)
        if d < best_d:
            best, best_d = i, d
    return best


def constrain_delta(delta, keys) -> np.ndarray:
    """依按住的 x/y/z 鍵把位移限制在軸向上;沒有按鍵則不限制。"""
    d = np.asarray(delta, dtype=float)
    axes = [i for i, k in enumerate("xyz") if k in keys]
    if not axes:
        return d
    out = np.zeros(3)
    out[axes] = d[axes]
    return out
