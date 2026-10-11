from core.model import Document


def test_appearance_accumulates_and_validates():
    d = Document()
    d.add_feature("box", {"x": 1, "y": 1, "z": 1})
    b = d.bodies[0].id
    assert d.add_feature("appearance", {"body": b, "color": "#ff0000", "opacity": 0.5, "visible": True}) is None
    assert d.appearance[b] == {"color": "#ff0000", "opacity": 0.5, "visible": True}
    assert d.add_feature("appearance", {"body": b, "visible": False}) is None
    assert d.appearance[b] == {"color": "#ff0000", "opacity": 0.5, "visible": False}
    assert d.add_feature("appearance", {"body": b, "opacity": 0.0}) is not None       # 透明度無效 -> 拒絕
    assert d.add_feature("appearance", {"body": 99, "color": "#00ff00"}) is not None  # 實體不存在
    assert len(d.bodies) == 1                                # 外觀不改變幾何
    d.set_suppressed(1, True)
    assert d.appearance[b] == {"color": None, "opacity": 1.0, "visible": False}   # 第一個外觀被抑制
    d.set_rollback(0)
    assert b not in d.appearance
