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


def holed():
    return (cq.Workplane().box(60, 40, 30).faces(">Z").workplane().pushPoints([(-15, 0), (15, 8)])
            .cboreHole(8, 14, 5).edges("|Z").edges("<X").fillet(5).val())


def test_section_view_hatch_and_marker():
    sh = D.build_sheet([holed()], section={"axis": "XZ", "offset": 0.0})
    sec = next(v for v in sh.views if v.name == "剖視")
    assert sec.label == "A-A" and sec.hidden == [] and len(sec.hatch) > 20
    assert not any(v.name == "等角視" for v in sh.views)                   # 剖視優先於等角視
    assert any(i["t"] == "text" and i["s"] == "A" for i in sh.markers) and len(sh.markers) >= 9
    # 剖面線都在剖面輪廓內,且為 45°
    (x0, y0), (x1, y1) = sec.bbox
    for seg in sec.hatch:
        assert x0 - 1e-6 <= seg[:, 0].min() and seg[:, 0].max() <= x1 + 1e-6 and y0 - 1e-6 <= seg[:, 1].min() and seg[:, 1].max() <= y1 + 1e-6
        d = seg[1] - seg[0]
        assert abs(abs(d[0]) - abs(d[1])) < 1e-6
    # 孔的位置沒有剖面線:剖切在 y=0,通過左側孔(x=-15,孔徑 8)
    hole_x = (-15 - 4, -15 + 4)
    cx = sec.bbox[0][0]
    for seg in sec.hatch:
        mid_x = (seg[0][0] + seg[1][0]) / 2
        if hole_x[0] + 0.3 < mid_x < hole_x[1] - 0.3 and (seg[0][1] + seg[1][1]) / 2 < 5:      # 孔下半(螺栓孔)區域不應有線
            raise AssertionError("孔內不應有剖面線")
    # 其他剖切方向與位置
    for axis in ("YZ", "XY"):
        s2 = D.build_sheet([holed()], section={"axis": axis, "offset": 0.0})
        assert next(v for v in s2.views if v.name == "剖視").hatch
    with pytest.raises(ValueError):
        D.build_sheet([holed()], section={"axis": "XZ", "offset": 500.0})
    no_iso = D.build_sheet([holed()], views=("前視", "上視", "右視", "等角視"))
    assert any(v.name == "等角視" for v in no_iso.views)


def test_more_dimensions():
    sh = D.build_sheet([holed()], chain=True)
    texts = [i["s"] for i in D.sheet_items(sh) if i["t"] == "text"]
    assert "R5" in texts                                                      # 圓角半徑
    assert "Ø14" in texts and "Ø8" in texts                                   # 沉頭孔兩個直徑
    assert "15" in texts and "45" in texts                                    # 孔中心 X(自左邊量起)
    assert "28" in texts and "20" in texts                                    # 孔中心 Y(自下邊量起)
    assert "5" in texts and "55" in texts                                     # 分段尺寸
    plain = [i["s"] for i in D.sheet_items(D.build_sheet([holed()], hole_pos=False, radii=False))
             if i["t"] == "text"]
    assert "R5" not in plain and "45" not in plain and "55" not in plain
    assert D.hatch_segments([], 1.0) == []
    import numpy as np
    segs = D.hatch_segments([np.array([[0, 0], [10, 0], [0, 10]], float)], 2.0)
    assert segs and all(abs(abs(s_[1][0] - s_[0][0]) - abs(s_[1][1] - s_[0][1])) < 1e-9 for s_ in segs)


def test_export_section_dxf(tmp_path):
    import ezdxf
    sh = D.build_sheet([holed()], section={"axis": "XZ", "offset": 0.0})
    p = str(tmp_path / "s.dxf")
    D.export_dxf(sh, p)
    layers = {e.dxf.layer for e in ezdxf.readfile(p).modelspace()}
    assert "HATCH" in layers and "DIM" in layers
