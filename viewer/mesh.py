"""CadQuery 形狀 -> PyVista 網格(保留每個面/邊的編號,供日後選取)。"""
import numpy as np
import pyvista as pv
import cadquery as cq
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_Orientation
from OCP.TopLoc import TopLoc_Location


def _tessellate(face: cq.Face, tol: float, ang: float):
    """以絕對誤差(mm)重新細分一個面。先清除舊網格,否則較粗的設定會沿用先前較細的結果。"""
    BRepTools.Clean_s(face.wrapped)
    BRepMesh_IncrementalMesh(face.wrapped, tol, False, ang, True)
    loc = TopLoc_Location()
    poly = BRep_Tool.Triangulation_s(face.wrapped, loc)
    if poly is None:
        return [], []
    trsf = loc.Transformation()
    reverse = face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
    verts = [cq.Vector(*(lambda p: (p.X(), p.Y(), p.Z()))(poly.Node(i).Transformed(trsf)))
             for i in range(1, poly.NbNodes() + 1)]
    tris = [((t.Value(1) - 1, t.Value(3) - 1, t.Value(2) - 1) if reverse
             else (t.Value(1) - 1, t.Value(2) - 1, t.Value(3) - 1)) for t in poly.Triangles()]
    return verts, tris


def shape_to_mesh(shape: cq.Shape, tol: float = 0.05, ang: float = 0.2) -> pv.PolyData:
    """逐面細分,cell_data['face_id'] 記錄三角形所屬的面編號。tol 為弦高誤差(mm),ang 為角度誤差(rad)。"""
    verts, tris, ids, offset = [], [], [], 0
    for i, face in enumerate(shape.Faces()):
        v, t = _tessellate(face, tol, ang)
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
        m = 2 if edge.geomType() == "LINE" else n          # 直線只需兩個端點
        p = [(v.x, v.y, v.z) for v in edge.positions(np.linspace(0, 1, m))]
        pts.extend(p)
        lines.extend([m, *range(offset, offset + m)])
        ids.append(i)
        offset += m
    if not pts:
        return pv.PolyData()
    poly = pv.PolyData(np.asarray(pts, dtype=float), lines=np.asarray(lines))
    poly.cell_data["edge_id"] = np.asarray(ids)
    return poly
