"""工程圖:三視圖(含隱藏線)、總尺寸與孔徑標註、圖框與標題欄;輸出 PDF / SVG / PNG / DXF。

build_sheet() 只做幾何與版面(純計算,可測試);draw_sheet() 用 Qt 畫在任何 QPainter 上。
"""
import math
from dataclasses import dataclass, field
from datetime import date

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepLib import BRepLib
from OCP.GeomAbs import GeomAbs_Circle
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

PAPERS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0)}      # 橫式 mm
STD_SCALES = [(1, 100), (1, 50), (1, 20), (1, 10), (1, 5), (1, 2), (1, 1), (2, 1), (5, 1), (10, 1), (20, 1)]
MARGIN, TITLE_H, GAP = 10.0, 42.0, 34.0

# 視圖: 名稱 -> (朝向觀看者的法向 N, 畫面向右的方向 X);畫面向上 = N × X
VIEW_DEFS = {
    "前視": ((0, -1, 0), (1, 0, 0)), "上視": ((0, 0, 1), (1, 0, 0)), "右視": ((1, 0, 0), (0, 1, 0)),
    "左視": ((-1, 0, 0), (0, -1, 0)), "後視": ((0, 1, 0), (-1, 0, 0)), "下視": ((0, 0, -1), (1, 0, 0)),
}


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def view_axes(name: str):
    """回傳 (N, X, Y):法向、畫面向右、畫面向上(皆為單位向量)。等角視 = 從 (1,-1,1) 方向看。"""
    if name == "等角視":
        n = _unit((1, -1, 1))
        x = _unit(np.cross((0, 0, 1), n))
    else:
        n, x = (_unit(v) for v in VIEW_DEFS[name])
    return n, x, np.cross(n, x)


def _polyline(edge: cq.Edge) -> np.ndarray:
    m = 2 if edge.geomType() == "LINE" else 72
    return np.array([[v.x, v.y] for v in edge.positions(np.linspace(0, 1, m))])


def project(shape: cq.Shape, name: str) -> dict:
    """隱藏線消除投影。回傳 {"visible": [Nx2], "hidden": [Nx2]}(單位 mm,以該視圖座標)。"""
    n, x, _ = view_axes(name)
    hlr = HLRBRep_Algo()
    hlr.Add(shape.wrapped)
    hlr.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*n), gp_Dir(*x))))
    hlr.Update()
    hlr.Hide()
    res = HLRBRep_HLRToShape(hlr)
    vis = [c for c in (res.VCompound(), res.Rg1LineVCompound(), res.OutLineVCompound()) if not c.IsNull()]
    hid = [c for c in (res.HCompound(), res.OutLineHCompound()) if not c.IsNull()]
    for c in vis + hid:
        BRepLib.BuildCurves3d_s(c, 1e-6)
    out = {"visible": [], "hidden": []}
    for key, comps in (("visible", vis), ("hidden", hid)):
        for c in comps:
            for e in cq.Shape(c).Edges():
                try:
                    out[key].append(_polyline(e))
                except Exception:  # noqa: BLE001  個別壞邊略過
                    continue
    return out


def _bbox(polys):
    pts = np.vstack(polys) if polys else np.zeros((1, 2))
    return pts.min(axis=0), pts.max(axis=0)


def circles_in_view(shapes, name: str):
    """視圖中呈現為圓的完整圓邊(軸線平行於視線):[(中心 2D, 半徑)](已去重)。"""
    n, x, y = view_axes(name)
    seen, out = set(), []
    for s in shapes:
        for e in s.Edges():
            curve = BRepAdaptor_Curve(e.wrapped)
            if curve.GetType() != GeomAbs_Circle or not e.IsClosed():
                continue
            c = curve.Circle()
            ax = _unit((c.Axis().Direction().X(), c.Axis().Direction().Y(), c.Axis().Direction().Z()))
            if abs(float(ax @ n)) < 0.999:
                continue
            loc = np.array([c.Location().X(), c.Location().Y(), c.Location().Z()])
            center = (round(float(loc @ x), 3), round(float(loc @ y), 3))
            key = (center, round(c.Radius(), 3))
            if key not in seen:
                seen.add(key)
                out.append((center, c.Radius()))
    return out


@dataclass
class DrawnView:
    name: str
    origin: tuple          # 模型座標 (0,0) 在圖紙上的位置 (mm,圖紙座標,y 向上)
    scale: float
    visible: list
    hidden: list
    circles: list
    bbox: tuple            # ((xmin,ymin),(xmax,ymax)) 模型座標


@dataclass
class Sheet:
    paper: tuple
    scale: tuple           # (分子, 分母)
    views: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    dims: bool = True
    hidden: bool = True


def choose_scale(w_avail, h_avail, model_w, model_h):
    """選用不超過版面的最大標準比例。"""
    for num, den in reversed(STD_SCALES):
        s = num / den
        if model_w * s <= w_avail and model_h * s <= h_avail:
            return num, den
    return STD_SCALES[0]


def build_sheet(shapes, views=("前視", "上視", "右視"), paper="A3", third_angle=True, scale="自動",
                hidden=True, dims=True, info=None, iso=True) -> Sheet:
    """產生圖紙:各視圖投影與擺放位置。scale 為 '自動' 或 '1:2'、'2:1' 之類。"""
    if not shapes:
        raise ValueError("沒有可繪製的實體")
    comp = cq.Compound.makeCompound(list(shapes))
    pw, ph = PAPERS[paper]
    avail_w, avail_h = pw - 2 * MARGIN, ph - 2 * MARGIN - TITLE_H
    proj = {v: project(comp, v) for v in set(views) | {"前視", "上視", "右視"}}
    box = {v: _bbox(p["visible"] + p["hidden"]) for v, p in proj.items()}
    size = {v: (b[1][0] - b[0][0], b[1][1] - b[0][1]) for v, b in box.items()}
    W, H = size["前視"]
    D = size["右視"][0]
    total_w, total_h = W + D, H + D
    use_top, use_right = "上視" in views, "右視" in views
    if scale == "自動":
        num, den = choose_scale(avail_w - GAP, avail_h - GAP, total_w, total_h)
    else:
        num, den = (int(t) for t in scale.split(":"))
    s = num / den
    sheet = Sheet((pw, ph), (num, den), info=dict(info or {}), dims=dims, hidden=hidden)
    # 版面:以「前視」為基準;第三角投影 上視在前視上方、右視在前視右方;第一角則相反
    block_w, block_h = W * s + GAP + D * s, H * s + GAP + D * s
    ox = MARGIN + (avail_w - block_w) / 2
    oy = MARGIN + TITLE_H + (avail_h - block_h) / 2          # 圖紙座標 y 向上,標題欄在下方
    if third_angle:
        front_x0, front_y0 = ox, oy                           # 前視格左下角
        right_x0, right_y0 = ox + W * s + GAP, oy
        top_x0, top_y0 = ox, oy + H * s + GAP
        iso_cell = (ox + W * s + GAP, oy + H * s + GAP, avail_w + MARGIN - (ox + W * s + GAP), D * s)
    else:
        front_x0, front_y0 = ox + D * s + GAP, oy + D * s + GAP
        right_x0, right_y0 = ox, front_y0
        top_x0, top_y0 = front_x0, oy
        iso_cell = (ox, oy, D * s, D * s)
    cells = {"前視": (front_x0, front_y0, W * s, H * s), "上視": (top_x0, top_y0, W * s, D * s),
             "右視": (right_x0, right_y0, D * s, H * s)}
    for v in views:
        if v in cells:
            x0, y0, cw, ch = cells[v]
            (bx0, by0), (bx1, by1) = box[v]
            org = (x0 + cw / 2 - (bx0 + bx1) / 2 * s, y0 + ch / 2 - (by0 + by1) / 2 * s)
            sc = s
        elif v == "等角視" or v not in cells:
            if v not in proj:
                proj[v] = project(comp, v)
                box[v] = _bbox(proj[v]["visible"] + proj[v]["hidden"])
            (bx0, by0), (bx1, by1) = box[v]
            cx, cy, cw, ch = iso_cell
            sc = min(s, cw * 0.9 / max(bx1 - bx0, 1e-9), ch * 0.9 / max(by1 - by0, 1e-9))
            org = (cx + cw / 2 - (bx0 + bx1) / 2 * sc, cy + ch / 2 - (by0 + by1) / 2 * sc)
        if v == "等角視" and not iso:
            continue
        sheet.views.append(DrawnView(v, org, sc, proj[v]["visible"], proj[v]["hidden"] if hidden else [],
                                     circles_in_view(shapes, v) if v != "等角視" else [], box[v]))
    sheet.info.setdefault("date", date.today().isoformat())
    sheet.info["projection"] = "第三角法" if third_angle else "第一角法"
    return sheet


def fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


# ---------------- 圖元(與輸出格式無關) ----------------
# {"t": "poly", "pts": [(x,y)...], "style": visible|hidden|dim|center|frame|thin}
# {"t": "arrow", "tip": (x,y), "dir": (dx,dy)}   {"t": "text", "pos": (x,y), "s": str, "h": mm, "rot": 度, "anchor": c|l|r}
# 座標皆為圖紙座標 (mm,原點在左下,y 向上)


def _dimension(items, p0, p1, offset_dir, off, text, ext=2.0, text_h=3.5):
    """p0、p1 為被標註的兩點;尺寸線沿 offset_dir 方向偏移 off mm。"""
    d = np.asarray(offset_dir, float)
    a, b = np.asarray(p0, float) + d * off, np.asarray(p1, float) + d * off
    for q, qa in ((p0, a), (p1, b)):
        items.append({"t": "poly", "pts": [tuple(np.asarray(q) + d * 1.5), tuple(qa + d * ext)], "style": "dim"})
    items.append({"t": "poly", "pts": [tuple(a), tuple(b)], "style": "dim"})
    u = b - a
    L = np.linalg.norm(u)
    if L > 1e-6:
        u = u / L
        items.append({"t": "arrow", "tip": tuple(a), "dir": tuple(u)})
        items.append({"t": "arrow", "tip": tuple(b), "dir": tuple(-u)})
    mid = (a + b) / 2 + d * 1.2
    rot = math.degrees(math.atan2(u[1], u[0])) if L > 1e-6 else 0
    if rot > 90 or rot <= -90:
        rot += 180
    items.append({"t": "text", "pos": tuple(mid), "s": text, "h": text_h, "rot": rot, "anchor": "c"})


def sheet_items(sheet: Sheet) -> list:
    pw, ph = sheet.paper
    items = []
    # 圖框
    items.append({"t": "poly", "pts": [(MARGIN, MARGIN), (pw - MARGIN, MARGIN), (pw - MARGIN, ph - MARGIN),
                                       (MARGIN, ph - MARGIN), (MARGIN, MARGIN)], "style": "frame"})
    # 標題欄(右下角)
    tw, th = 150.0, 36.0
    x0, y0 = pw - MARGIN - tw, MARGIN
    cols = [x0, x0 + 60, x0 + 105, x0 + tw]
    rows = [y0, y0 + 12, y0 + 24, y0 + th]
    items.append({"t": "poly", "pts": [(x0, y0), (x0 + tw, y0), (x0 + tw, y0 + th), (x0, y0 + th), (x0, y0)],
                  "style": "frame"})
    for y in rows[1:3]:
        items.append({"t": "poly", "pts": [(x0, y), (x0 + tw, y)], "style": "thin"})
    for x in cols[1:3]:
        items.append({"t": "poly", "pts": [(x, y0), (x, rows[2])], "style": "thin"})
    num, den = sheet.scale
    info = sheet.info
    cells = [
        (cols[0], rows[2], cols[3], rows[3], "圖名", info.get("title", "")),
        (cols[0], rows[1], cols[1], rows[2], "零件名稱", info.get("part", "")),
        (cols[1], rows[1], cols[2], rows[2], "比例", f"{num}:{den}"),
        (cols[2], rows[1], cols[3], rows[2], "單位", "mm"),
        (cols[0], rows[0], cols[1], rows[1], "設計者", info.get("author", "")),
        (cols[1], rows[0], cols[2], rows[1], "日期", info.get("date", "")),
        (cols[2], rows[0], cols[3], rows[1], "投影法 / 紙張", f"{info.get('projection', '')} {info.get('paper', '')}"),
    ]
    for xa, ya, xb, yb, label, val in cells:
        items.append({"t": "text", "pos": (xa + 1.5, yb - 3.2), "s": label, "h": 2.2, "rot": 0, "anchor": "l"})
        items.append({"t": "text", "pos": (xa + 1.5, ya + 4.6), "s": val, "h": 4.0 if label != "圖名" else 5.0,
                      "rot": 0, "anchor": "l"})
    # 視圖
    done = set()
    for v in sheet.views:
        ox, oy = v.origin
        tr = lambda pl: [(ox + p[0] * v.scale, oy + p[1] * v.scale) for p in pl]  # noqa: E731
        for pl in v.visible:
            items.append({"t": "poly", "pts": tr(pl), "style": "visible"})
        for pl in v.hidden:
            items.append({"t": "poly", "pts": tr(pl), "style": "hidden"})
        (bx0, by0), (bx1, by1) = v.bbox
        P = lambda x, y: (ox + x * v.scale, oy + y * v.scale)  # noqa: E731
        if sheet.dims:
            if v.name == "前視":
                _dimension(items, P(bx0, by0), P(bx1, by0), (0, -1), 9, fmt(bx1 - bx0))
                _dimension(items, P(bx0, by0), P(bx0, by1), (-1, 0), 9, fmt(by1 - by0))
            elif v.name == "上視":
                _dimension(items, P(bx1, by0), P(bx1, by1), (1, 0), 9, fmt(by1 - by0))
            elif v.name == "右視" and "前視" not in {w.name for w in sheet.views}:
                _dimension(items, P(bx0, by0), P(bx1, by0), (0, -1), 9, fmt(bx1 - bx0))
        for (cx, cy), r in v.circles:
            rs = r * v.scale
            if rs < 1.2:
                continue
            c = P(cx, cy)
            for a, b in (((c[0] - rs * 1.25, c[1]), (c[0] + rs * 1.25, c[1])),
                         ((c[0], c[1] - rs * 1.25), (c[0], c[1] + rs * 1.25))):
                items.append({"t": "poly", "pts": [a, b], "style": "center"})
            if sheet.dims and (round(cx, 2), round(cy, 2), round(r, 2), v.name) not in done:
                done.add((round(cx, 2), round(cy, 2), round(r, 2), v.name))
                u = np.array([math.cos(math.radians(45)), math.sin(math.radians(45))])
                tip = np.array(c) + u * rs
                far = tip + u * 9
                items.append({"t": "poly", "pts": [tuple(tip), tuple(far), (far[0] + 5, far[1])], "style": "dim"})
                items.append({"t": "arrow", "tip": tuple(tip), "dir": tuple(-u)})
                items.append({"t": "text", "pos": (far[0] + 6, far[1] - 1.2), "s": f"Ø{fmt(2 * r)}", "h": 3.5,
                              "rot": 0, "anchor": "l"})
    # 視圖名稱
    for v in sheet.views:
        (bx0, by0), (bx1, by1) = v.bbox
        items.append({"t": "text", "pos": (v.origin[0] + (bx0 + bx1) / 2 * v.scale,
                                           v.origin[1] + by1 * v.scale + 4), "s": v.name, "h": 3.2,
                      "rot": 0, "anchor": "c"})
    return items


def export_dxf(sheet: Sheet, path: str) -> None:
    """輸出 DXF(各線型分圖層;箭頭以填滿的小三角形 SOLID 表示)。"""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    layers = {"visible": ("OUTLINE", 7, "CONTINUOUS"), "hidden": ("HIDDEN", 8, "DASHED"),
              "dim": ("DIM", 3, "CONTINUOUS"), "center": ("CENTER", 1, "CENTER"),
              "frame": ("FRAME", 7, "CONTINUOUS"), "thin": ("FRAME_THIN", 7, "CONTINUOUS"), "text": ("TEXT", 2, "CONTINUOUS")}
    for name, color, lt in layers.values():
        doc.layers.add(name, color=color, linetype=lt)
    for it in sheet_items(sheet):
        if it["t"] == "poly":
            msp.add_lwpolyline(it["pts"], dxfattribs={"layer": layers[it["style"]][0]})
        elif it["t"] == "arrow":
            tip, d = np.array(it["tip"]), np.array(it["dir"])
            n = np.array([-d[1], d[0]])
            a, b = tip + d * 3 + n * 0.9, tip + d * 3 - n * 0.9
            msp.add_solid([tuple(tip), tuple(a), tuple(b)], dxfattribs={"layer": "DIM"})
        else:
            t = msp.add_text(it["s"], dxfattribs={"layer": "TEXT", "height": it["h"], "rotation": it["rot"]})
            t.set_placement(it["pos"], align={"c": ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
                                              "l": ezdxf.enums.TextEntityAlignment.LEFT,
                                              "r": ezdxf.enums.TextEntityAlignment.RIGHT}[it["anchor"]])
    doc.saveas(path)
