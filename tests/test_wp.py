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


def test_offset_plane():
    wp = F.offset_plane(F.WORLD_PLANES["XY"], 5)
    assert wp["origin"] == [0, 0, 5] and wp["normal"] == [0, 0, 1]
    t = F.offset_plane(F.WORLD_PLANES["XY"], 0, rx=90)
    assert t["normal"] == [0, -1, 0]


def test_refplane_feature_follows_edit():
    d = make()
    assert d.add_feature("refplane", {"wp": F.WORLD_PLANES["XY"], "offset": 10, "rx": 0, "ry": 0}) is None
    assert len(d.planes) == 1 and len(d.bodies) == 1
    pid = d.planes[0][0]
    assert d.add_feature("cylinder", {"r": 1, "h": 2, "wp": d.planes[0][2],
                                      "plane_id": pid}) is None
    assert abs(d.bodies[1].shape.BoundingBox().zmin - 10) < 1e-6
    assert d.edit_feature(1, {"offset": 20}) is None             # 移動參考面 -> 圓柱跟著動
    assert abs(d.bodies[1].shape.BoundingBox().zmin - 20) < 1e-6
    # 以參考面為基準再建平行面(串接)
    assert d.add_feature("refplane", {"wp": d.planes[0][2], "plane_id": pid, "offset": 5}) is None
    assert d.planes[1][2]["origin"] == [0, 0, 25]
    assert d.edit_feature(3, {"offset": 0}) is None
    assert d.planes[1][2]["origin"] == [0, 0, 20]
    d.add_feature("delete", {"body": pid})                        # 刪除第一個參考面
    assert len(d.planes) == 1
    # 刪除參考面後再用它建立的特徵會改用快照平面(不會失敗)
    assert d.add_feature("cylinder", {"r": 1, "h": 2, "wp": F.WORLD_PLANES["XY"],
                                      "plane_id": pid}) is None
    assert abs(d.bodies[-1].shape.BoundingBox().zmin) < 1e-6
