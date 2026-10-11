import math
import pytest
from core.expr import evaluate, evaluate_all, resolve_params
from core.model import Document


def test_evaluate():
    assert evaluate("1 + 2 * 3") == 7
    assert evaluate("板厚 / 2 + 1", {"板厚": 10}) == 6
    assert abs(evaluate("sqrt(2) * pi") - math.sqrt(2) * math.pi) < 1e-12
    assert evaluate("max(3, 4) - min(1, 2)") == 3
    for bad in ("__import__('os')", "x + 1", "1 / 0", "open('f')", "a.b", "[1]", "1 +"):
        with pytest.raises(ValueError):
            evaluate(bad)


def test_variables_and_resolve():
    vals = evaluate_all({"w": 40, "h": "=w / 2", "r": "h/4"})
    assert vals == {"w": 40.0, "h": 20.0, "r": 5.0}
    out = resolve_params({"x": "=w + 1", "y": 5, "name": "abc", "pts": "0,0"}, vals)
    assert out["x"] == 41.0 and out["y"] == 5 and out["pts"] == "0,0"
    with pytest.raises(ValueError):
        resolve_params({"x": "=zz"}, vals)


def test_document_parametric_variables(tmp_path):
    d = Document()
    assert d.set_variables({"寬": 40, "高": "=寬/2", "孔徑": 8}) is None
    assert d.add_feature("box", {"x": "=寬", "y": "=寬", "z": "=高"}) is None
    assert abs(d.bodies[0].shape.Volume() - 40 * 40 * 20) < 1e-6
    assert d.set_variables({"寬": 30, "高": "=寬/2", "孔徑": 8}) is None          # 改變數 -> 重算
    assert abs(d.bodies[0].shape.Volume() - 30 * 30 * 15) < 1e-6
    assert d.set_variables({"寬": "=未定義"}) is not None and d.variables["寬"] == 30   # 無效 -> 拒絕
    err = d.add_feature("cylinder", {"r": "=不存在", "h": 5})
    assert err and "未定義" in err
    d.undo()                                                 # 復原上一次變數修改:寬回到 40
    assert d.variables["寬"] == 40 and abs(d.bodies[0].shape.Volume() - 40 * 40 * 20) < 1e-6
    d.set_variables({"寬": 25, "高": "=寬/2"})
    p = str(tmp_path / "v.v3d")
    d.save_project(p)
    e = Document()
    e.load_project(p)
    assert e.variables["寬"] == 25 and abs(e.bodies[0].shape.Volume() - 25 * 25 * 12.5) < 1e-6
