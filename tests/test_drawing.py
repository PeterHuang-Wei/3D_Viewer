import math
import os
import cadquery as cq
import pytest
from core import drawing as D


def part():
    return cq.Workplane().box(60, 40, 30).faces(">Z").workplane().hole(10).val()


def test_views_projection_and_layout():
    sh = D.build_sheet([part()], views=("前視", "上視", "右視", "等角視"), paper="A3")
    names = [v.name for v in sh.views]
    assert names == ["前視", "上視", "右視", "等角視"]
    sizes = {v.name: tuple(round(b, 3) for b in (v.bbox[1][0] - v.bbox[0][0], v.bbox[1][1] - v.bbox[0][1])) for v in sh.views}
    assert sizes["前視"] == (60, 30) and sizes["上視"] == (60, 40) and sizes["右視"] == (40, 30)
    front, top, right = (next(v for v in sh.views if v.name == n) for n in ("前視", "上視", "右視"))
    assert top.origin[1] > front.origin[1] and right.origin[0] > front.origin[0]      # 第三角
    assert any(abs(r - 5) < 1e-6 for (_, r) in top.circles)                          # 俯視可見孔
    assert not front.circles and front.hidden                                          # 前視沒有圓,但孔的隱藏線存在
    sh2 = D.build_sheet([part()], third_angle=False)
    f2, t2, r2 = (next(v for v in sh2.views if v.name == n) for n in ("前視", "上視", "右視"))
    assert t2.origin[1] < f2.origin[1] and r2.origin[0] < f2.origin[0]                # 第一角相反
    assert D.build_sheet([part()], hidden=False).views[0].hidden == []
    with pytest.raises(ValueError):
        D.build_sheet([])


def test_scale_choice_and_fit():
    assert D.choose_scale(300, 200, 60, 40) in ((2, 1), (5, 1))
    big = cq.Workplane().box(2000, 1000, 500).val()
    num, den = D.build_sheet([big], paper="A3").scale
    assert num == 1 and den >= 5
    assert D.build_sheet([part()], scale="1:2").scale == (1, 2)
    for v in D.build_sheet([big]).views:                    # 所有視圖都在圖框內
        ox, oy = v.origin
        pts = [(ox + p[0] * v.scale, oy + p[1] * v.scale) for pl in v.visible for p in pl]
        assert all(D.MARGIN - 1e-6 <= x <= 420 - D.MARGIN + 1e-6 and D.MARGIN - 1e-6 <= y <= 297 - D.MARGIN + 1e-6 for x, y in pts)


def test_items_and_dimensions():
    sh = D.build_sheet([part()], views=("前視", "上視", "右視"), info={"title": "測試", "part": "底座"})
    items = D.sheet_items(sh)
    texts = [i["s"] for i in items if i["t"] == "text"]
    assert "60" in texts and "30" in texts and "40" in texts and "Ø10" in texts      # 總尺寸與孔徑
    assert "測試" in texts and "底座" in texts and f"{sh.scale[0]}:{sh.scale[1]}" in texts
    assert sum(1 for i in items if i["t"] == "arrow") == 7        # 前視 2 組、上視 1 組總尺寸 + 1 個孔徑
    assert not any(i["t"] == "text" and i["s"].startswith("Ø") for i in D.sheet_items(D.build_sheet([part()], dims=False)))


def test_export_all_formats(tmp_path):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.drawing_render import export_sheet, render_image
    sh = D.build_sheet([part()], views=("前視", "上視", "右視", "等角視"), info={"title": "測試圖", "author": "me"})
    for ext in ("pdf", "svg", "png", "dxf"):
        p = str(tmp_path / f"d.{ext}")
        export_sheet(sh, p)
        assert os.path.getsize(p) > 1000
    assert open(tmp_path / "d.pdf", "rb").read(5) == b"%PDF-"
    import ezdxf
    dxf = ezdxf.readfile(str(tmp_path / "d.dxf"))
    layers = {e.dxf.layer for e in dxf.modelspace()}
    assert {"OUTLINE", "HIDDEN", "DIM", "TEXT", "FRAME"} <= layers
    img = render_image(sh, 60)
    assert img.width() == int(420 * 60 / 25.4)
    with pytest.raises(ValueError):
        export_sheet(sh, str(tmp_path / "d.xyz"))
