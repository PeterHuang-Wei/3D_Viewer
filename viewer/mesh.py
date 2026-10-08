"""CadQuery 形狀 -> PyVista 網格(保留每個面/邊的編號,供日後選取)。"""
import numpy as np
import pyvista as pv
import cadquery as cq


def shape_to_mesh(shape: cq.Shape, tol: float = 0.05, ang: float = 0.2) -> pv.PolyData:
    """逐面細分,cell_data['face_id'] 記錄三角形所屬的面編號。"""
    verts, tris, ids, offset = [], [], [], 0
    for i, face in enumerate(shape.Faces()):
        v, t = face.tessellate(tol, ang)
        if not t:
            continue
        verts.extend((p.x, p.y, p.z) for p in v)
        tris.extend((a + offset, b + offset, c + offset) for a, b, c in t)
        ids.extend([i] * len(t))
        offset += len(v)
    if not tris:
        return pv.PolyData()
    tri = np.asarray(tris)
    faces = np.hstack([np.full((len(tri), 1), 3), tri]).ravel()
    mesh = pv.PolyData(np.asarray(verts, dtype=float), faces)
    mesh.cell_data["face_id"] = np.asarray(ids)
    return mesh


def shape_to_edges(shape: cq.Shape, n: int = 24) -> pv.PolyData:
    """所有邊離散成折線,cell_data['edge_id'] 記錄邊編號。"""
    pts, lines, ids, offset = [], [], [], 0
    for i, edge in enumerate(shape.Edges()):
        p = [(v.x, v.y, v.z) for v in edge.positions(np.linspace(0, 1, n))]
        pts.extend(p)
        lines.extend([n, *range(offset, offset + n)])
        ids.append(i)
        offset += n
    if not pts:
        return pv.PolyData()
    poly = pv.PolyData(np.asarray(pts, dtype=float), lines=np.asarray(lines))
    poly.cell_data["edge_id"] = np.asarray(ids)
    return poly
