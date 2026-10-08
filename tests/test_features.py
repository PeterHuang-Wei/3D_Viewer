import pytest
from core import features as f


def vol(s):
    return s.Volume()


def test_primitives():
    assert abs(vol(f.make_box(1, 2, 3)) - 6) < 1e-6
    assert abs(vol(f.make_cylinder(1, 2)) - 2 * 3.14159265) < 1e-3
    assert vol(f.make_sphere(1)) > 4
    assert vol(f.make_cone(2, 1, 3)) > 0
    assert vol(f.make_torus(5, 1)) > 0


def test_sketch():
    s = f.sketch_extrude("XY", 0, "矩形", {"w": 2, "h": 3}, 4)
    assert abs(vol(s) - 24) < 1e-6
    pts = f.parse_points("0,0; 10,0; 0,10")
    t = f.sketch_extrude("XZ", 0, "自訂多邊形", {"pts": pts}, 2)
    assert abs(vol(t) - 100) < 1e-6
    c = f.sketch_revolve("XY", 0, "圓", {"r": 1, "cx": 5})  # 圓繞 Y 軸 -> 環
    assert abs(vol(c) - 2 * 3.14159265 * 5 * 3.14159265) < 1e-3


def test_transform():
    b = f.make_box(2, 2, 2)
    m = f.translate(b, 10, 0, 0)
    assert abs(m.Center().x - 10) < 1e-6
    r = f.rotate(b, 0, 0, 45)
    assert abs(vol(r) - 8) < 1e-6


def test_boolean():
    a = f.make_box(10, 10, 10)
    b = f.translate(f.make_box(10, 10, 10), 5, 0, 0)
    assert abs(vol(f.boolean("聯集", a, b)) - 1500) < 1e-6
    assert abs(vol(f.boolean("差集", a, b)) - 500) < 1e-6
    assert abs(vol(f.boolean("交集", a, b)) - 500) < 1e-6
    far = f.translate(a, 100, 0, 0)
    with pytest.raises(ValueError):
        f.boolean("交集", a, far)
