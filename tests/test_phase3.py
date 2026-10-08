import numpy as np
import pytest
from core import features as F
from viewer.mesh import shape_to_mesh, shape_to_edges
from viewer.picking import EdgeIndex, face_at, nearest_body


def box():
    return F.make_box(10, 10, 10)


def test_fillet_chamfer_volume():
    b = box()
    assert F.fillet(b, set(range(12)), 1).Volume() < 1000
    top = F.face_edge_ids(b, [i for i, f in enumerate(b.Faces()) if f.Center().z > 4])
    assert len(top) == 4
    c = F.chamfer(b, top, 1)
    assert abs(c.Volume() - 990) < 10   # 4 條邊各削去約 0.5*1*1*10
    assert c.Volume() < 1000
    assert F.chamfer(b, {0}, 1, 2).Volume() < 1000


def test_errors():
    with pytest.raises(ValueError):
        F.fillet(box(), set(), 1)
    with pytest.raises(ValueError):
        F.fillet(box(), {0}, 100)


def test_picking():
    b = box()
    idx = EdgeIndex(shape_to_edges(b))
    e = idx.nearest((5, 5, 4.9))          # 靠近頂面的某條邊或面中心,任一邊皆可
    assert e is not None
    # 點在一條邊上:選到的邊其中點必為該位置
    edges = b.Edges()
    mid = edges[3].Center()
    got = idx.nearest((mid.x, mid.y, mid.z))
    assert edges[got].Center().sub(mid).Length < 1e-6
    mesh = shape_to_mesh(b)
    fid = face_at(mesh, (0, 0, 5))
    assert abs(b.Faces()[fid].Center().z - 5) < 1e-6
    assert nearest_body([mesh, shape_to_mesh(F.translate(b, 100, 0, 0))], (99, 0, 0)) == 1


def test_scale_and_constrain():
    from viewer.picking import constrain_delta
    b = F.make_box(2, 2, 2)
    assert abs(F.scale(b, 2, 2, 2).Volume() - 64) < 1e-6
    n = F.scale(b, 1, 2, 3)
    assert abs(n.Volume() - 48) < 1e-6 and abs(n.Center().x) < 1e-9
    t = F.translate(b, 10, 0, 0)
    assert abs(F.scale(t, 2, 2, 2, about_center=True).Center().x - 10) < 1e-6
    assert abs(F.scale(t, 2, 2, 2, about_center=False).Center().x - 20) < 1e-6
    with pytest.raises(ValueError):
        F.scale(b, 0, 1, 1)
    assert list(constrain_delta((1, 2, 3), {"y"})) == [0, 2, 0]
    assert list(constrain_delta((1, 2, 3), set())) == [1, 2, 3]
