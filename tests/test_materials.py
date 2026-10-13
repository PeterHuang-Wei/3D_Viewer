import math
import numpy as np
import cadquery as cq
import pytest
from core import materials as MT
from core import interference as IF
from core.model import Document


def box(x, y, z, at=(0, 0, 0)):
    return cq.Workplane().box(x, y, z).val().moved(cq.Location(cq.Vector(*at)))


def test_mass_props_box():
    p = MT.mass_props(box(10, 20, 30, (100, 0, 0)), 7.85)
    assert abs(p["volume"] - 6000) < 1e-6 and abs(p["mass"] - 47.1) < 1e-9          # 6 cm³ × 7.85 g/cm³
    assert np.allclose(p["com"], (100, 0, 0), atol=1e-6)
    m = p["mass"]
    assert np.allclose(np.diag(p["inertia"]), [m * (20**2 + 30**2) / 12, m * (10**2 + 30**2) / 12, m * (10**2 + 20**2) / 12])
    assert np.allclose(sorted(MT.principal_moments(p["inertia"])), sorted(np.diag(p["inertia"])))
    sphere = MT.mass_props(cq.Workplane().sphere(10).val(), 1.0)
    assert abs(sphere["mass"] - 4 / 3 * math.pi * 1000 / 1000) < 1e-2
    assert abs(sphere["inertia"][0][0] - 2 / 5 * sphere["mass"] * 100) < 1


def test_assembly_parallel_axis():
    a, b = box(10, 10, 10, (-20, 0, 0)), box(10, 10, 10, (20, 0, 0))
    r = MT.assembly_props([("a", a, 1.0), ("b", b, 3.0)])
    assert abs(r["mass"] - 4.0) < 1e-9 and np.allclose(r["com"], (10, 0, 0), atol=1e-6)    # 重的一側在右,質心偏右
    ma, mb = 1.0, 3.0
    Iyy_self = (ma + mb) * (100 + 100) / 12
    d2 = ma * 30**2 + mb * 10**2
    assert abs(r["inertia"][1][1] - (Iyy_self + d2)) < 1e-6
    with pytest.raises(ValueError):
        MT.assembly_props([])


def test_density_lookup():
    assert MT.density_of("鋁 6061") == 2.70 and MT.density_of(MT.CUSTOM, 3.3) == 3.3
    for bad in (("不存在", 1), (MT.CUSTOM, 0)):
        with pytest.raises(ValueError):
            MT.density_of(*bad)


def test_material_feature_in_document(tmp_path):
    d = Document()
    d.add_feature("box", {"x": 10, "y": 10, "z": 10})
    b = d.bodies[0].id
    assert d.add_feature("material", {"body": b, "material": "鋁 6061", "density": 2.7}) is None
    assert d.materials[b] == {"material": "鋁 6061", "density": 2.7}
    assert d.add_feature("material", {"body": b, "material": "自訂密度", "density": 0}) is not None    # 無效密度 -> 拒絕
    assert d.add_feature("material", {"body": 99, "material": "碳鋼", "density": 7.85}) is not None
    p = str(tmp_path / "m.v3d")
    d.save_project(p)
    e = Document()
    e.load_project(p)
    assert e.materials[b]["material"] == "鋁 6061"


def test_interference():
    a, b = box(10, 10, 10), box(10, 10, 10, (5, 0, 0))
    r = IF.check([(1, "A", a), (2, "B", b)])
    assert len(r) == 1 and r[0]["kind"] == "干涉" and abs(r[0]["volume"] - 500) < 1e-6
    assert abs(r[0]["center"].x - 2.5) < 1e-6
    inner = box(2, 2, 2)
    assert abs(IF.check([(1, "A", a), (3, "In", inner)])[0]["volume"] - 8) < 1e-6      # 完全包含
    touch = box(10, 10, 10, (10, 0, 0))
    t = IF.check([(1, "A", a), (4, "T", touch)])
    assert len(t) == 1 and t[0]["kind"] == "接觸" and t[0]["volume"] == 0
    assert IF.check([(1, "A", a), (4, "T", touch)], include_contact=False) == []
    far = box(10, 10, 10, (100, 0, 0))
    assert IF.check([(1, "A", a), (5, "Far", far)]) == []
    assert len(IF.check([(1, "A", a), (2, "B", b), (5, "F", far)])) == 1
