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


def exact_bbox(comp: cq.Shape, name: str):
    """零件在該視圖畫面座標的外框((xmin,ymin),(xmax,ymax)),取自 3D 外框(比取樣折線精確,供尺寸數值使用)。"""
    _, x, y = view_axes(name)
    bb = comp.BoundingBox(tolerance=1e-7)
    corners = np.array([[a, b, c] for a in (bb.xmin, bb.xmax) for b in (bb.ymin, bb.ymax) for c in (bb.zmin, bb.zmax)])
    p = np.column_stack([corners @ x, corners @ y])
    return (tuple(p.min(axis=0)), tuple(p.max(axis=0)))


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


def arcs_in_view(shapes, name: str):
    """視圖中呈現為圓弧的邊(圓角等,軸線平行於視線):[(中心 2D, 半徑, 弧中點方向 2D)](已去重)。"""
    n, x, y = view_axes(name)
    seen, out = set(), []
    for s in shapes:
        for e in s.Edges():
            curve = BRepAdaptor_Curve(e.wrapped)
            if curve.GetType() != GeomAbs_Circle or e.IsClosed():
                continue
            c = curve.Circle()
            ax = _unit((c.Axis().Direction().X(), c.Axis().Direction().Y(), c.Axis().Direction().Z()))
            if abs(float(ax @ n)) < 0.999:
                continue
            loc = np.array([c.Location().X(), c.Location().Y(), c.Location().Z()])
            mid = np.array(e.positionAt(0.5).toTuple()) - loc
            m2 = np.array([mid @ x, mid @ y])
            if np.linalg.norm(m2) < 1e-9:
                continue
            m2 = m2 / np.linalg.norm(m2)
            center = (round(float(loc @ x), 3), round(float(loc @ y), 3))
            key = (center, round(c.Radius(), 3), round(float(m2[0]), 2), round(float(m2[1]), 2))
            if key not in seen:
                seen.add(key)
                out.append((center, c.Radius(), (float(m2[0]), float(m2[1]))))
    return out


# ---------------- 剖視圖 ----------------
# 剖切平面 -> (觀看的視圖, 沿哪個軸(0=X,1=Y,2=Z), 保留側(+1: >=剖切位置, -1: <=), 標示剖切線的視圖, 剖切線方向, 視線箭頭方向)
SECTIONS = {
    "XZ": ("前視", 1, +1, "上視", (1, 0), (0, 1)),
    "YZ": ("右視", 0, -1, "上視", (0, 1), (-1, 0)),
    "XY": ("上視", 2, -1, "前視", (1, 0), (0, -1)),
}
SECTION_LABELS = {"無": None, "前剖(XZ 平面)": "XZ", "側剖(YZ 平面)": "YZ", "上剖(XY 平面)": "XY"}


def hatch_segments(tris, spacing: float):
    """以 45° 斜線填滿三角形群(剖面線)。回傳線段 [array([[x0,y0],[x1,y1]])](同一條線上相接的已合併)。"""
    step = spacing * math.sqrt(2)
    lines: dict = {}
    for t in tris:
        d = t[:, 0] - t[:, 1]
        for k in range(int(math.floor(d.min() / step)), int(math.ceil(d.max() / step)) + 1):
            c = k * step
            pts = []
            for i in range(3):
                a, b = t[i], t[(i + 1) % 3]
                da, db = a[0] - a[1] - c, b[0] - b[1] - c
                if (da <= 0 < db) or (db <= 0 < da):
                    pts.append(a + (b - a) * (da / (da - db)))
            if len(pts) < 2:
                continue
            u = [(p[0] + p[1]) / math.sqrt(2) for p in pts]
            i0, i1 = int(np.argmin(u)), int(np.argmax(u))
            if u[i1] - u[i0] > 1e-9:
                lines.setdefault(k, []).append((u[i0], u[i1], pts[i0], pts[i1]))
    out = []
    for segs in lines.values():
        segs.sort(key=lambda z: z[0])
        cur = list(segs[0])
        for sg in segs[1:]:
            if sg[0] <= cur[1] + 1e-6:
                if sg[1] > cur[1]:
                    cur[1], cur[3] = sg[1], sg[3]
            else:
                out.append(np.array([cur[2], cur[3]]))
                cur = list(sg)
        out.append(np.array([cur[2], cur[3]]))
    return out


def make_section(comp: cq.Shape, axis: str, offset: float = 0.0, spacing: float = 1.5) -> dict:
    """全剖視:剖切位置 = 零件中心 + offset。回傳 {"view","coord","proj","hatch","marker_view","marker_dir","arrow"}。"""
    view, idx, keep, mview, mdir, arrow = SECTIONS[axis]
    bb = comp.BoundingBox()
    lo = np.array([bb.xmin, bb.ymin, bb.zmin])
    hi = np.array([bb.xmax, bb.ymax, bb.zmax])
    coord = float((lo[idx] + hi[idx]) / 2 + offset)
    if not lo[idx] + 1e-6 < coord < hi[idx] - 1e-6:
        raise ValueError("剖切位置在零件之外")
    pad = float(np.linalg.norm(hi - lo)) + 10
    bmin, bmax = lo - pad, hi + pad
    if keep > 0:
        bmin[idx] = coord
    else:
        bmax[idx] = coord
    box = cq.Solid.makeBox(*(bmax - bmin), pnt=cq.Vector(*bmin))
    rem = comp.intersect(box)
    if not rem.Solids() or rem.Volume() < 1e-9:
        raise ValueError("剖切位置在零件之外")
    proj = project(rem, view)
    _, vx, vy = view_axes(view)
    n = np.zeros(3)
    n[idx] = 1.0
    tris = []
    for f in rem.Faces():
        c = f.Center()
        if f.geomType() != "PLANE" or abs(abs(float(np.array(f.normalAt().toTuple()) @ n)) - 1) > 1e-6 \
                or abs(np.array(c.toTuple())[idx] - coord) > 1e-4:
            continue
        verts, tri = f.tessellate(0.02, 0.1)
        pts = np.array([[v.x, v.y, v.z] for v in verts])
        p2 = np.column_stack([pts @ vx, pts @ vy])
        tris += [p2[list(t)] for t in tri]
    return {"view": view, "coord": coord, "proj": proj, "tris": tris, "marker_view": mview,
            "marker_dir": mdir, "arrow": arrow, "idx": idx, "spacing": spacing}


@dataclass
class DrawnView:
    name: str
    origin: tuple          # 模型座標 (0,0) 在圖紙上的位置 (mm,圖紙座標,y 向上)
    scale: float
    visible: list
    hidden: list
    circles: list
    bbox: tuple            # ((xmin,ymin),(xmax,ymax)) 模型座標
    arcs: list = field(default_factory=list)       # 圓角等圓弧 (中心, 半徑, 弧中點方向)
    hatch: list = field(default_factory=list)      # 剖面線線段 (模型座標)
    label: str = ""        # 視圖名稱的顯示文字(預設為 name)
    exact: tuple | None = None                     # 精確外框(尺寸數值用)


@dataclass
class Sheet:
    paper: tuple
    scale: tuple           # (分子, 分母)
    views: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    dims: bool = True
    hidden: bool = True
    options: dict = field(default_factory=dict)    # hole_pos / radii / chain
    markers: list = field(default_factory=list)    # 剖切線標示(圖紙座標圖元)


def choose_scale(w_avail, h_avail, model_w, model_h):
    """選用不超過版面的最大標準比例。"""
    for num, den in reversed(STD_SCALES):
        s = num / den
        if model_w * s <= w_avail and model_h * s <= h_avail:
            return num, den
    return STD_SCALES[0]


def build_sheet(shapes, views=("前視", "上視", "右視"), paper="A3", third_angle=True, scale="自動",
                hidden=True, dims=True, info=None, iso=True, section=None, hole_pos=True, radii=True,
                chain=False) -> Sheet:
    """產生圖紙:各視圖投影與擺放位置。scale 為 '自動' 或 '1:2'、'2:1' 之類。
    section: None 或 {"axis": "XZ"|"YZ"|"XY", "offset": 相對零件中心的位置};剖視圖放在右上(與等角視共用,剖視優先)。
    hole_pos: 圓孔位置(座標尺寸);radii: 圓角半徑 R;chain: 分段(鏈式)尺寸。"""
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
    if scale == "自動":
        num, den = choose_scale(avail_w - GAP, avail_h - GAP, total_w, total_h)
    else:
        num, den = (int(t) for t in scale.split(":"))
    s = num / den
    sheet = Sheet((pw, ph), (num, den), info=dict(info or {}), dims=dims, hidden=hidden,
                  options={"hole_pos": hole_pos, "radii": radii, "chain": chain})
    block_w, block_h = W * s + GAP + D * s, H * s + GAP + D * s
    ox = MARGIN + (avail_w - block_w) / 2
    oy = MARGIN + TITLE_H + (avail_h - block_h) / 2          # 圖紙座標 y 向上,標題欄在下方
    top_edge, right_edge = ph - MARGIN, pw - MARGIN
    if third_angle:
        front_x0, front_y0 = ox, oy                           # 前視格左下角
        right_x0, right_y0 = ox + W * s + GAP, oy
        top_x0, top_y0 = ox, oy + H * s + GAP
        free = (right_x0, top_y0, right_edge - right_x0, top_edge - top_y0 - 14)         # 右上空位(上方留視圖名稱)
    else:
        front_x0, front_y0 = ox + D * s + GAP, oy + D * s + GAP
        right_x0, right_y0 = ox, front_y0
        top_x0, top_y0 = front_x0, oy
        free = (MARGIN, MARGIN + TITLE_H, front_x0 - MARGIN - GAP * 0.5, front_y0 - MARGIN - TITLE_H - GAP * 0.5 - 14)
    cells = {"前視": (front_x0, front_y0, W * s, H * s), "上視": (top_x0, top_y0, W * s, D * s),
             "右視": (right_x0, right_y0, D * s, H * s)}

    def place(v, cell, sc_max):
        (bx0, by0), (bx1, by1) = box[v]
        cx, cy, cw, ch = cell
        sc = min(sc_max, cw * 0.9 / max(bx1 - bx0, 1e-9), ch * 0.9 / max(by1 - by0, 1e-9))
        return (cx + cw / 2 - (bx0 + bx1) / 2 * sc, cy + ch / 2 - (by0 + by1) / 2 * sc), sc

    for v in views:
        if v == "等角視":
            continue
        (bx0, by0), (bx1, by1) = box[v]
        x0, y0, cw, ch = cells[v]
        org = (x0 + cw / 2 - (bx0 + bx1) / 2 * s, y0 + ch / 2 - (by0 + by1) / 2 * s)
        sheet.views.append(DrawnView(v, org, s, proj[v]["visible"], proj[v]["hidden"] if hidden else [],
                                     circles_in_view(shapes, v), box[v], arcs_in_view(shapes, v) if radii else [],
                                     exact=exact_bbox(comp, v)))
    if section:
        sec = make_section(comp, section["axis"], section.get("offset", 0.0))
        v = "剖視"
        box[v] = _bbox(sec["proj"]["visible"])
        org, sc = place(v, free, s)
        segs = hatch_segments(sec["tris"], 2.5 / max(sc, 1e-9)) if sec["tris"] else []      # 剖面線間距約 2.5 mm
        sheet.views.append(DrawnView(v, org, sc, sec["proj"]["visible"], [], [], box[v], [], segs, "A-A"))
        _add_section_marker(sheet, sec, "A")
    elif "等角視" in views and iso:
        proj["等角視"] = project(comp, "等角視")
        box["等角視"] = _bbox(proj["等角視"]["visible"] + proj["等角視"]["hidden"])
        org, sc = place("等角視", free, s)
        sheet.views.append(DrawnView("等角視", org, sc, proj["等角視"]["visible"],
                                     proj["等角視"]["hidden"] if hidden else [], [], box["等角視"]))
    sheet.info.setdefault("date", date.today().isoformat())
    sheet.info["projection"] = "第三角法" if third_angle else "第一角法"
    return sheet


def _add_section_marker(sheet: Sheet, sec: dict, letter: str) -> None:
    """在剖切線所在的視圖畫出剖切線(兩端粗線 + 視線方向箭頭 + 代號)。"""
    tv = next((v for v in sheet.views if v.name == sec["marker_view"]), None)
    if tv is None:
        return
    (bx0, by0), (bx1, by1) = tv.bbox
    ox, oy = tv.origin
    s = tv.scale
    d = np.array(sec["marker_dir"], float)                        # 剖切線方向
    a = np.array(sec["arrow"], float)                             # 視線(箭頭)方向
    c = sec["coord"]
    if d[0] == 1:                                                  # 水平線:y = c(視圖座標)
        p0, p1 = np.array([bx0 * s + ox, c * s + oy]), np.array([bx1 * s + ox, c * s + oy])
    else:                                                          # 垂直線:x = c
        p0, p1 = np.array([c * s + ox, by0 * s + oy]), np.array([c * s + ox, by1 * s + oy])
    p0, p1 = p0 - d * 8, p1 + d * 8
    it = sheet.markers
    it.append({"t": "poly", "pts": [tuple(p0), tuple(p1)], "style": "center"})
    for end, sign in ((p0, +1), (p1, -1)):
        tick_end = end + d * 5 * sign
        it.append({"t": "poly", "pts": [tuple(end), tuple(tick_end)], "style": "frame"})
        tip = end + a * 9
        it.append({"t": "poly", "pts": [tuple(end), tuple(tip)], "style": "frame"})
        it.append({"t": "arrow", "tip": tuple(tip), "dir": tuple(-a)})
        it.append({"t": "text", "pos": tuple(tip + a * 4), "s": letter, "h": 5.0, "rot": 0, "anchor": "c"})


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


def _chain_values(polys, axis: int, lo: float, hi: float):
    """直線邊(垂直於 axis 方向者)所在的座標值,含兩端,已排序去重:供分段尺寸使用。"""
    vals = {round(lo, 3), round(hi, 3)}
    for pl in polys:
        if len(pl) == 2 and abs(pl[0][axis] - pl[1][axis]) < 1e-6 and np.linalg.norm(pl[1] - pl[0]) > 1e-6:
            vals.add(round(float(pl[0][axis]), 3))
    out = sorted(vals)
    merged = [out[0]]
    for v in out[1:]:                                   # 間距太小(< 0.5)的視為同一條
        if v - merged[-1] >= 0.5:
            merged.append(v)
    return merged if len(merged) > 2 else []


def _ordinates(items, v, P, bx0, by0, bx1, by1, ex0, ey0):
    """孔中心的座標尺寸:X 值標在視圖上方、Y 值標在視圖左方(皆為相對視圖左下角的距離)。"""
    xs = sorted({round(c[0] - ex0, 2) for c, _ in v.circles if c[0] - ex0 > 0.05})
    ys = sorted({round(c[1] - ey0, 2) for c, _ in v.circles if c[1] - ey0 > 0.05})
    if not v.circles or not (xs or ys):
        return
    top = P(bx0, by1)[1] + 7
    left = P(bx0, by0)[0] - 13
    for c, r in v.circles:
        px, py = P(*c)
        cx_val, cy_val = round(c[0] - ex0, 2), round(c[1] - ey0, 2)
        if cx_val > 0.05:
            items.append({"t": "poly", "pts": [(px, py + r * v.scale * 1.25 + 1), (px, top)], "style": "thin"})
            items.append({"t": "text", "pos": (px, top + 2.2), "s": fmt(cx_val), "h": 3.0, "rot": 0, "anchor": "c"})
        if cy_val > 0.05:
            items.append({"t": "poly", "pts": [(px - r * v.scale * 1.25 - 1, py), (left, py)], "style": "thin"})
            items.append({"t": "text", "pos": (left - 1.5, py), "s": fmt(cy_val), "h": 3.0, "rot": 90, "anchor": "c"})


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
    opt = sheet.options
    for v in sheet.views:
        ox, oy = v.origin
        tr = lambda pl: [(ox + p[0] * v.scale, oy + p[1] * v.scale) for p in pl]  # noqa: E731
        for pl in v.visible:
            items.append({"t": "poly", "pts": tr(pl), "style": "visible"})
        for pl in v.hidden:
            items.append({"t": "poly", "pts": tr(pl), "style": "hidden"})
        for sg in v.hatch:
            items.append({"t": "poly", "pts": tr(sg), "style": "hatch"})
        (bx0, by0), (bx1, by1) = v.bbox
        (ex0, ey0), (ex1, ey1) = v.exact if v.exact else v.bbox
        P = lambda x, y: (ox + x * v.scale, oy + y * v.scale)  # noqa: E731
        std = v.name in ("前視", "上視", "右視")
        if sheet.dims and std:
            chain_x = _chain_values(v.visible, 0, bx0, bx1) if opt.get("chain") else []
            chain_y = _chain_values(v.visible, 1, by0, by1) if opt.get("chain") else []
            off_all = 9 + (9 if len(chain_x) > 2 else 0)
            offy_all = 9 + (9 if len(chain_y) > 2 else 0)
            if v.name == "前視":
                _dimension(items, P(bx0, by0), P(bx1, by0), (0, -1), off_all, fmt(ex1 - ex0))
                _dimension(items, P(bx0, by0), P(bx0, by1), (-1, 0), offy_all, fmt(ey1 - ey0))
            elif v.name == "上視":
                _dimension(items, P(bx1, by0), P(bx1, by1), (1, 0), offy_all, fmt(ey1 - ey0))
            elif v.name == "右視" and "前視" not in {w.name for w in sheet.views}:
                _dimension(items, P(bx0, by0), P(bx1, by0), (0, -1), off_all, fmt(ex1 - ex0))
            if len(chain_x) > 2 and v.name in ("前視", "上視", "右視"):         # 分段尺寸(水平方向,在下方)
                for xa, xb in zip(chain_x, chain_x[1:]):
                    _dimension(items, P(xa, by0), P(xb, by0), (0, -1), 9, fmt(xb - xa))
            if len(chain_y) > 2 and v.name in ("前視", "右視"):                  # 分段尺寸(垂直方向,在左方)
                for ya, yb in zip(chain_y, chain_y[1:]):
                    _dimension(items, P(bx0, ya), P(bx0, yb), (-1, 0), 9, fmt(yb - ya))
        # 圓孔:中心線、Ø 直徑(同心圓的引線錯開角度)
        seen_centers: dict = {}
        for (cx, cy), r in sorted(v.circles, key=lambda t: -t[1]):
            rs = r * v.scale
            if rs < 1.2:
                continue
            c = P(cx, cy)
            for a_, b_ in (((c[0] - rs * 1.25, c[1]), (c[0] + rs * 1.25, c[1])),
                           ((c[0], c[1] - rs * 1.25), (c[0], c[1] + rs * 1.25))):
                items.append({"t": "poly", "pts": [a_, b_], "style": "center"})
            if sheet.dims and std and (round(cx, 2), round(cy, 2), round(r, 2), v.name) not in done:
                done.add((round(cx, 2), round(cy, 2), round(r, 2), v.name))
                k = seen_centers.get((cx, cy), 0)
                seen_centers[(cx, cy)] = k + 1
                ang = math.radians(45 + 28 * k)
                u = np.array([math.cos(ang), math.sin(ang)])
                tip = np.array(c) + u * rs
                far = tip + u * 9
                side = 1 if u[0] >= -1e-9 else -1
                items.append({"t": "poly", "pts": [tuple(tip), tuple(far), (far[0] + 5 * side, far[1])], "style": "dim"})
                items.append({"t": "arrow", "tip": tuple(tip), "dir": tuple(-u)})
                items.append({"t": "text", "pos": (far[0] + 6 * side, far[1] - 1.2), "s": f"Ø{fmt(2 * r)}", "h": 3.5,
                              "rot": 0, "anchor": "l" if side > 0 else "r"})
        # 圓孔位置:座標(縱標)尺寸,從視圖左下角量起
        if sheet.dims and std and opt.get("hole_pos"):
            _ordinates(items, v, P, bx0, by0, bx1, by1, ex0, ey0)
        # 圓角半徑 R
        if sheet.dims and std and opt.get("radii"):
            for (cx, cy), r, (mx, my) in v.arcs:
                rs = r * v.scale
                if rs < 1.0 or (round(cx, 2), round(cy, 2), round(r, 2), "R", v.name) in done:
                    continue
                done.add((round(cx, 2), round(cy, 2), round(r, 2), "R", v.name))
                u = np.array([mx, my])
                tip = np.array(P(cx, cy)) + u * rs
                far = tip + u * 8
                side = 1 if far[0] >= tip[0] else -1
                items.append({"t": "poly", "pts": [tuple(tip), tuple(far), (far[0] + 4 * side, far[1])], "style": "dim"})
                items.append({"t": "arrow", "tip": tuple(tip), "dir": tuple(-u)})
                items.append({"t": "text", "pos": (far[0] + 5 * side, far[1] - 1.2), "s": f"R{fmt(r)}", "h": 3.2,
                              "rot": 0, "anchor": "l" if side > 0 else "r"})
    # 視圖名稱
    for v in sheet.views:
        (bx0, by0), (bx1, by1) = v.bbox
        lift = 8 if (sheet.dims and opt.get("hole_pos") and v.circles) else 0      # 有座標尺寸時,名稱上移避開
        items.append({"t": "text", "pos": (v.origin[0] + (bx0 + bx1) / 2 * v.scale,
                                           v.origin[1] + by1 * v.scale + 4 + lift), "s": v.label or v.name, "h": 4.5 if v.label else 3.2,
                      "rot": 0, "anchor": "c"})
    items.extend(sheet.markers)
    return items


def export_dxf(sheet: Sheet, path: str) -> None:
    """輸出 DXF(各線型分圖層;箭頭以填滿的小三角形 SOLID 表示)。"""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    layers = {"visible": ("OUTLINE", 7, "CONTINUOUS"), "hidden": ("HIDDEN", 8, "DASHED"),
              "dim": ("DIM", 3, "CONTINUOUS"), "center": ("CENTER", 1, "CENTER"),
              "frame": ("FRAME", 7, "CONTINUOUS"), "thin": ("FRAME_THIN", 7, "CONTINUOUS"), "text": ("TEXT", 2, "CONTINUOUS"),
              "hatch": ("HATCH", 8, "CONTINUOUS")}
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
