import math
import cadquery as cq
import pytest
from core import measure as M


def box(x=10, y=10, z=10):
    return cq.Workplane().box(x, y, z).val()


def test_min_distance_and_points():
    a = box()
    b = a.moved(cq.Location(cq.Vector(25, 0, 0)))
    d, p, q = M.min_distance(a, b)
    assert abs(d - 15) < 1e-9 and abs(p.x - 5) < 1e-9 and abs(q.x - 20) < 1e-9
    # 面到面(平行)
    fa = max(a.Faces(), key=lambda f: f.Center().x)
    fb = min(b.Faces(), key=lambda f: f.Center().x)
    assert abs(M.min_distance(fa, fb)[0] - 15) < 1e-9
    # 頂點到邊
    v = cq.Vertex.makeVertex(0, 0, 20)
    assert abs(M.min_distance(v, a)[0] - 15) < 1e-9
    r = M.point_distance(cq.Vector(0, 0, 0), cq.Vector(3, 4, 12))
    assert abs(r["distance"] - 13) < 1e-9 and r["dz"] == 12


def test_edge_and_face_info():
    cyl = cq.Workplane().circle(5).extrude(8).val()
    circles = [e for e in cyl.Edges() if e.geomType() == "CIRCLE"]
    info = M.edge_info(circles[0])
    assert abs(info["radius"] - 5) < 1e-9 and abs(info["diameter"] - 10) < 1e-9
    assert abs(info["length"] - 2 * math.pi * 5) < 1e-6
    line = [e for e in cyl.Edges() if e.geomType() == "LINE"][0]
    assert abs(M.edge_info(line)["length"] - 8) < 1e-9 and "radius" not in M.edge_info(line)
    kinds = {f.geomType(): M.face_info(f) for f in cyl.Faces()}
    assert abs(kinds["PLANE"]["area"] - math.pi * 25) < 1e-6 and abs(kinds["PLANE"]["normal"].z) > 0.99
    assert abs(kinds["CYLINDER"]["radius"] - 5) < 1e-9
    assert abs(kinds["CYLINDER"]["area"] - 2 * math.pi * 5 * 8) < 1e-6


def test_angles():
    b = box()
    top = max(b.Faces(), key=lambda f: f.Center().z)
    right = max(b.Faces(), key=lambda f: f.Center().x)
    assert abs(M.angle_between(top, right)["angle"] - 90) < 1e-9
    # 非 90°:楔形(斜面內夾角 135)
    wedge = cq.Workplane("XZ").polyline([(0, 0), (10, 0), (10, 5), (5, 10), (0, 10)]).close().extrude(3).val()
    slanted = [f for f in wedge.Faces() if f.geomType() == "PLANE" and abs(f.normalAt().x) > 0.1 and abs(f.normalAt().z) > 0.1]
    assert slanted
    assert abs(M.angle_between(slanted[0], max(wedge.Faces(), key=lambda f: f.Center().x))["angle"] - 135) < 1e-6
    e = [e for e in b.Edges() if abs((e.endPoint() - e.startPoint()).x) > 5][0]
    ez = [e for e in b.Edges() if abs((e.endPoint() - e.startPoint()).z) > 5][0]
    assert abs(M.angle_between(e, ez)["angle"] - 90) < 1e-9
    assert abs(M.angle_between(e, top)["angle"]) < 1e-9          # 邊平行於頂面
    assert abs(M.angle_between(ez, top)["angle"] - 90) < 1e-9
    curved = [f for f in cq.Workplane().circle(2).extrude(3).val().Faces() if f.geomType() == "CYLINDER"][0]
    with pytest.raises(ValueError):
        M.angle_between(curved, top)


def test_body_props():
    p = M.body_properties(box(2, 3, 4))
    assert abs(p["volume"] - 24) < 1e-9 and abs(p["area"] - 52) < 1e-9
    assert p["size"] == pytest.approx((2, 3, 4))
