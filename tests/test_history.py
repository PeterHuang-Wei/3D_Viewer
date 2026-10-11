from core.model import Document


def make():
    d = Document()
    d.add_feature("box", {"x": 10, "y": 10, "z": 10})
    d.add_feature("cylinder", {"r": 2, "h": 30})
    a, b = [x.id for x in d.bodies]
    return d, a, b


def vol(d, i=0):
    return d.bodies[i].shape.Volume()


def test_boolean_edit_recompute():
    d, a, b = make()
    assert d.add_feature("boolean", {"op": "差集", "target": a, "tool": b}) is None
    assert len(d.bodies) == 1
    v1 = vol(d)
    assert d.edit_feature(1, {"r": 3}) is None        # 改圓柱半徑 -> 重算
    assert vol(d) < v1


def test_undo_redo():
    d, a, b = make()
    d.add_feature("boolean", {"op": "聯集", "target": a, "tool": b})
    d.undo()
    assert len(d.bodies) == 2
    d.redo()
    assert len(d.bodies) == 1
    d.undo(); d.undo(); d.undo()
    assert d.bodies == [] and not d.can_undo()


def test_failed_add_rolls_back():
    d, a, b = make()
    err = d.add_feature("fillet", {"body": a, "edges": [0], "r": 100})
    assert err and len(d.features) == 2


def test_delete_feature_marks_dependents():
    d, a, b = make()
    d.add_feature("translate", {"body": a, "x": 5, "y": 0, "z": 0})
    d.delete_feature(0)                                # 刪除方塊 -> 平移失敗但不崩潰
    assert d.features[-1].error and len(d.bodies) == 1


def test_project_roundtrip(tmp_path):
    d, a, b = make()
    d.add_feature("fillet", {"body": a, "edges": [0, 1], "r": 1})
    p = str(tmp_path / "x.v3d")
    d.save_project(p)
    e = Document()
    e.load_project(p)
    assert len(e.bodies) == 2 and abs(vol(e) - vol(d)) < 1e-6 and not e.dirty
    e.add_feature("box", {"x": 1, "y": 1, "z": 1})
    assert e.bodies[-1].id not in (a, b)               # 編號不重複


def test_thread_and_sketch_features():
    d = Document()
    sk = {"plane": "XY 平面", "offset": 0, "kind": "矩形", "w": 4, "h": 5, "r": 1, "n": 6,
          "pts": "", "cx": 0, "cy": 0, "depth": 3, "sym": False}
    assert d.add_feature("extrude", sk) is None
    assert abs(vol(d) - 60) < 1e-6
    th = {"spec": "M6 粗牙 (P1.0)", "d": 6, "p": 1, "left": False, "len": 8}
    assert d.add_feature("rod", th) is None


def test_scale_feature():
    d, a, b = make()
    p = {"uniform": True, "sx": 2, "sy": 1, "sz": 1, "c": True, "body": a}
    assert d.add_feature("scale", p) is None
    assert abs(vol(d) - 8000) < 1e-6
    assert d.edit_feature(2, {"uniform": False, "sy": 3}) is None
    assert abs(vol(d) - 10 * 10 * 10 * 2 * 3 * 1) < 1e-3


def test_suppress_rename_move_rollback():
    d, a, b = make()
    d.add_feature("boolean", {"op": "差集", "target": a, "tool": b})
    assert len(d.bodies) == 1
    d.set_suppressed(2, True)                              # 抑制布林 -> 兩個實體回來
    assert len(d.bodies) == 2 and d.features[2].suppressed and d.features[2].error is None
    d.set_suppressed(2, False)
    assert len(d.bodies) == 1
    d.set_suppressed(1, True)                              # 抑制被引用的圓柱 -> 布林失敗但不崩潰
    assert d.features[2].error and len(d.bodies) == 1
    d.set_suppressed(1, False)
    d.rename_feature(0, "底板")
    assert d.features[0].title == "底板" and d.features[1].title == "圓柱"
    # 回溯到第 2 個特徵之後
    d.set_rollback(1)
    assert len(d.bodies) == 2 and d.rollback == 1
    d.add_feature("box", {"x": 1, "y": 1, "z": 1})         # 回溯中新增 -> 插在回溯點之後
    assert d.features[2].kind == "box" and d.features[3].kind == "boolean" and d.rollback == 2
    d.set_rollback(None)
    assert d.rollback is None and len(d.bodies) == 2       # 方塊 + 差集結果
    # 上移/下移
    assert d.move_feature(0, 1) and d.features[1].title == "底板"
    assert not d.move_feature(0, -1)
    d.undo()
    assert d.features[0].title == "底板"


def test_project_keeps_suppress_name_rollback(tmp_path):
    d, a, b = make()
    d.add_feature("translate", {"body": a, "x": 5, "y": 0, "z": 0})
    d.rename_feature(2, "右移")
    d.set_suppressed(1, True)
    d.set_rollback(2)
    p = str(tmp_path / "r.v3d")
    d.save_project(p)
    e = Document()
    e.load_project(p)
    assert e.features[1].suppressed and e.features[2].name == "右移" and e.rollback is None
    assert [f.suppressed for f in e.features] == [False, True, False]
