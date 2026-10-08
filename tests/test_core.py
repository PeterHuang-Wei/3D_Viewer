import cadquery as cq

from core.model import Document
from viewer.mesh import shape_to_mesh, shape_to_edges


def test_step_roundtrip(tmp_path):
    box = cq.Workplane().box(10, 20, 30).val()
    doc = Document()
    doc.add(box)
    p = str(tmp_path / "a.step")
    doc.save_step(p)

    doc2 = Document()
    doc2.open_step(p)
    assert len(doc2.bodies) == 1
    assert abs(doc2.bodies[0].shape.Volume() - 6000) < 1e-6


def test_mesh():
    box = cq.Workplane().box(10, 10, 10).val()
    mesh = shape_to_mesh(box)
    assert mesh.n_cells == 12
    assert set(mesh.cell_data["face_id"]) == set(range(6))
    assert shape_to_edges(box).n_cells == 12
