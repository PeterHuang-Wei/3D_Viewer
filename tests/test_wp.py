import pytest
from core import features as F
from core.model import Document


def top_face(shape):
    return max(shape.Faces(), key=lambda f: f.Center().z)


def make():
    d = Document()
    d.add_feature("box", {"x": 10, "y": 10, "z": 10})
    return d


def test_plane_from_face():
    b = F.make_box(10, 10, 10)
    wp = F.plane_from_face(top_face(b))
    assert wp["origin"] == [0, 0, 5] and wp["normal"] == [0, 0, 1]
    curved = [f for f in F.make_cylinder(2, 4).Faces() if f.geomType() != "PLANE"][0]
    with pytest.raises(ValueError):
        F.plane_from_face(curved)


def test_cylinder_on_face_and_flip():
    d = make()
    wp = F.plane_from_face(top_face(d.bodies[0].shape))
    assert d.add_feature("cylinder", {"r": 2, "h": 4, "wp": wp}) is None
    bb = d.bodies[1].shape.BoundingBox()
    assert abs(bb.zmin - 5) < 1e-6 and abs(bb.zmax - 9) < 1e-6
    assert d.add_feature("cylinder", {"r": 2, "h": 4, "wp": wp, "flip": True}) is None
    bb = d.bodies[2].shape.BoundingBox()
    assert abs(bb.zmin - 1) < 1e-6 and abs(bb.zmax - 5) < 1e-6


def test_sketch_and_hole_on_side_face():
    d = make()
    side = max(d.bodies[0].shape.Faces(), key=lambda f: f.Center().x)
    wp = F.plane_from_face(side)
    sk = {"kind": "圓", "w": 1, "h": 1, "r": 2, "n": 6, "pts": "", "cx": 0, "cy": 0,
          "depth": 3, "sym": False, "wp": wp}
    assert d.add_feature("extrude", sk) is None
    bb = d.bodies[1].shape.BoundingBox()
    assert abs(bb.xmin - 5) < 1e-6 and abs(bb.xmax - 8) < 1e-6
    th = {"spec": "M3 粗牙 (P0.5)", "d": 3, "p": 0.5, "left": False, "depth": 4, "wp": wp}
    v0 = d.bodies[0].shape.Volume()
    assert d.add_feature("thread_hole", {**th, "body": d.bodies[0].id}) is None
    assert d.bodies[0].shape.Volume() < v0


def test_world_plane_matches_default():
    b = F.to_plane(F.make_box(2, 2, 2), F.WORLD_PLANES["XY"], ground=True)
    assert abs(b.BoundingBox().zmin) < 1e-6
    xz = F.to_plane(F.make_cylinder(1, 2), F.WORLD_PLANES["XZ"], ground=True)
    bb = xz.BoundingBox()
    assert abs(bb.ymin - (-2)) < 1e-6 and abs(bb.ymax) < 1e-6    # XZ 法向為 -Y
