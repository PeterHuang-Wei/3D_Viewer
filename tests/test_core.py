import cadquery as cq

from core.model import Document
from viewer.mesh import shape_to_mesh, shape_to_edges


def box(doc, x=10, y=10, z=10):
    assert doc.add_feature("box", {"x": x, "y": y, "z": z}) is None
    return doc.bodies[-1].id


def test_step_roundtrip(tmp_path):
    doc = Document()
    box(doc, 10, 20, 30)
    p = str(tmp_path / "a.step")
    doc.export_step(p)
    doc2 = Document()
    assert doc2.import_step(p) is None
    assert len(doc2.bodies) == 1
    assert abs(doc2.bodies[0].shape.Volume() - 6000) < 1e-6


def test_mesh():
    b = cq.Workplane().box(10, 10, 10).val()
    mesh = shape_to_mesh(b)
    assert mesh.n_cells == 12
    assert set(mesh.cell_data["face_id"]) == set(range(6))
    assert shape_to_edges(b).n_cells == 12
