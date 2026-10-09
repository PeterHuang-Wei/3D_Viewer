"""2D 草圖幾何:線、圓、圓弧,以及修整、鏡射、陣列、封閉輪廓與轉成實體。

草圖座標 (u, v) 位於工作平面內;所有圖元皆為可存成 JSON 的 dict:
  line   {"t": "line",   "p1": [u, v], "p2": [u, v]}
  circle {"t": "circle", "c": [u, v], "r": r}
  arc    {"t": "arc",    "c": [u, v], "r": r, "a0": 度, "a1": 度}   由 a0 逆時針到 a1
"""
import copy
import math

import cadquery as cq

TOL = 1e-6


# --- 建立圖元 ---
def line(p1, p2):
    return {"t": "line", "p1": [float(p1[0]), float(p1[1])], "p2": [float(p2[0]), float(p2[1])]}


def circle(c, r):
    return {"t": "circle", "c": [float(c[0]), float(c[1])], "r": float(r)}


def arc(c, r, a0, a1):
    return {"t": "arc", "c": [float(c[0]), float(c[1])], "r": float(r),
            "a0": float(a0) % 360.0, "a1": float(a1) % 360.0}


def assign_ids(entities):
    """替沒有編號的圖元指派唯一編號(拘束以編號參照圖元)。就地修改並回傳。"""
    used = {e["id"] for e in entities if "id" in e}
    nxt = max(used, default=0) + 1
    for e in entities:
        if "id" not in e:
            e["id"] = nxt
            used.add(nxt)
            nxt += 1
    return entities


def rectangle(p1, p2):
    (x1, y1), (x2, y2) = p1, p2
    return [line((x1, y1), (x2, y1)), line((x2, y1), (x2, y2)),
            line((x2, y2), (x1, y2)), line((x1, y2), (x1, y1))]


def arc_from_3pts(p1, p2, p3):
    """起點 p1、經過 p2、終點 p3 的圓弧。"""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        raise ValueError("三點共線,無法建立圓弧")
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    ang = lambda p: math.degrees(math.atan2(p[1] - uy, p[0] - ux))  # noqa: E731
    ccw = (bx - ax) * (cy - by) - (by - ay) * (cx - bx) > 0   # p1->p2->p3 為逆時針
    return arc((ux, uy), r, ang(p1), ang(p3)) if ccw else arc((ux, uy), r, ang(p3), ang(p1))


# --- 基本查詢 ---
def span(e) -> float:
    """圓弧涵蓋的角度(0 度視為整圓)。"""
    s = (e["a1"] - e["a0"]) % 360.0
    return s if s > 1e-9 else 360.0


def _on_arc(e, ang) -> bool:
    if e["t"] == "circle":
        return True
    return (ang - e["a0"]) % 360.0 <= span(e) + 1e-7 or (e["a0"] - ang) % 360.0 < 1e-7


def _pt(e, ang):
    t = math.radians(ang)
    return [e["c"][0] + e["r"] * math.cos(t), e["c"][1] + e["r"] * math.sin(t)]


def endpoints(e):
    if e["t"] == "line":
        return [list(e["p1"]), list(e["p2"])]
    if e["t"] == "arc":
        return [_pt(e, e["a0"]), _pt(e, e["a0"] + span(e))]
    return []


def snap_points(e):
    """可吸附的特徵點:端點、圓心、直線中點、圓的四分點。"""
    pts = endpoints(e)
    if e["t"] == "line":
        pts.append([(e["p1"][0] + e["p2"][0]) / 2, (e["p1"][1] + e["p2"][1]) / 2])
    else:
        pts.append(list(e["c"]))
        if e["t"] == "circle":
            pts += [_pt(e, a) for a in (0, 90, 180, 270)]
    return pts


def is_closed_by_itself(e) -> bool:
    return e["t"] == "circle" or (e["t"] == "arc" and abs(span(e) - 360.0) < 1e-7)


def sample(e, n: int = 48):
    """離散成折線點(依圖元自然方向)。"""
    if e["t"] == "line":
        return [list(e["p1"]), list(e["p2"])]
    s = 360.0 if e["t"] == "circle" else span(e)
    a0 = 0.0 if e["t"] == "circle" else e["a0"]
    k = max(8, int(n * s / 360.0))
    return [_pt(e, a0 + s * i / k) for i in range(k + 1)]


def dist_point(e, p) -> float:
    px, py = p
    if e["t"] == "line":
        (x1, y1), (x2, y2) = e["p1"], e["p2"]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
    cx, cy = e["c"]
    d = math.hypot(px - cx, py - cy)
    ang = math.degrees(math.atan2(py - cy, px - cx))
    if _on_arc(e, ang):
        return abs(d - e["r"])
    return min(math.hypot(px - q[0], py - q[1]) for q in endpoints(e))


def nearest_entity(entities, p, tol: float):
    """距離 p 最近且在容許範圍內的圖元索引,沒有則 None。"""
    best, best_d = None, tol
    for i, e in enumerate(entities):
        d = dist_point(e, p)
        if d <= best_d:
            best, best_d = i, d
    return best


# --- 交點與分割 ---
def _line_line(a, b):
    (x1, y1), (x2, y2) = a["p1"], a["p2"]
    (x3, y3), (x4, y4) = b["p1"], b["p2"]
    den = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(den) < 1e-12:
        return []
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / den
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / den
    if -TOL <= t <= 1 + TOL and -TOL <= u <= 1 + TOL:
        return [[x1 + t * (x2 - x1), y1 + t * (y2 - y1)]]
    return []


def _line_circle(ln, c):
    (x1, y1), (x2, y2) = ln["p1"], ln["p2"]
    cx, cy = c["c"]
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - cx, y1 - cy
    A = dx * dx + dy * dy
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - c["r"] ** 2
    disc = B * B - 4 * A * C
    if A < 1e-18 or disc < -1e-12:
        return []
    sq = math.sqrt(max(disc, 0.0))
    ts = {(-B - sq) / (2 * A), (-B + sq) / (2 * A)}
    out = []
    for t in ts:
        if -TOL <= t <= 1 + TOL:
            p = [x1 + t * dx, y1 + t * dy]
            if _on_arc(c, math.degrees(math.atan2(p[1] - cy, p[0] - cx))):
                out.append(p)
    return out


def _circle_circle(a, b):
    (x0, y0), (x1, y1) = a["c"], b["c"]
    d = math.hypot(x1 - x0, y1 - y0)
    r0, r1 = a["r"], b["r"]
    if d < 1e-12 or d > r0 + r1 + 1e-9 or d < abs(r0 - r1) - 1e-9:
        return []
    k = (r0**2 - r1**2 + d**2) / (2 * d)
    h = math.sqrt(max(r0**2 - k**2, 0.0))
    mx, my = x0 + k * (x1 - x0) / d, y0 + k * (y1 - y0) / d
    pts = [[mx + h * (y1 - y0) / d, my - h * (x1 - x0) / d]]
    if h > 1e-9:
        pts.append([mx - h * (y1 - y0) / d, my + h * (x1 - x0) / d])
    ang = lambda e, p: math.degrees(math.atan2(p[1] - e["c"][1], p[0] - e["c"][0]))  # noqa: E731
    return [p for p in pts if _on_arc(a, ang(a, p)) and _on_arc(b, ang(b, p))]


def intersections(a, b):
    if a["t"] == "line" and b["t"] == "line":
        return _line_line(a, b)
    if a["t"] == "line":
        return _line_circle(a, b)
    if b["t"] == "line":
        return _line_circle(b, a)
    return _circle_circle(a, b)


def split_entity(e, pts):
    """在交點 pts 處把圖元切成多段(端點上的點會被忽略)。"""
    if e["t"] == "line":
        (x1, y1), (x2, y2) = e["p1"], e["p2"]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        ts = sorted({round(((p[0] - x1) * dx + (p[1] - y1) * dy) / L2, 9) for p in pts})
        ts = [t for t in ts if TOL < t < 1 - TOL]
        cuts = [0.0] + ts + [1.0]
        return [line((x1 + a * dx, y1 + a * dy), (x1 + b * dx, y1 + b * dy))
                for a, b in zip(cuts, cuts[1:])]
    cx, cy = e["c"]
    angs = sorted({round(math.degrees(math.atan2(p[1] - cy, p[0] - cx)) % 360.0, 7) for p in pts})
    if e["t"] == "circle":
        if not angs:
            return [e]
        angs.append(angs[0] + 360.0)
        return [arc(e["c"], e["r"], a, b) for a, b in zip(angs, angs[1:])]
    a0, s = e["a0"], span(e)
    rel = sorted({round((a - a0) % 360.0, 7) for a in angs})
    rel = [r for r in rel if 1e-7 < r < s - 1e-7]
    cuts = [0.0] + rel + [s]
    return [arc(e["c"], e["r"], a0 + a, a0 + b) for a, b in zip(cuts, cuts[1:])]


def trim(entities, idx, click):
    """修整:在與其他圖元的交點處切開,刪除點擊位置所在的那一段。"""
    e = entities[idx]
    pts = [p for j, o in enumerate(entities) if j != idx for p in intersections(e, o)]
    rest = entities[:idx] + entities[idx + 1:]
    pieces = split_entity(e, pts) if pts else []
    if len(pieces) <= 1:
        return rest                       # 沒有交點(或整條都是同一段):整個刪除
    drop = min(range(len(pieces)), key=lambda i: dist_point(pieces[i], click))
    return rest + [p for i, p in enumerate(pieces) if i != drop]


# --- 變換 ---
def _map(e, fp, fa=None, flip=False):
    """對圖元套用點變換 fp;圓弧另用 fa 轉角度,flip=True 表示變換反轉方向(鏡射)。"""
    e = copy.deepcopy(e)
    e.pop("id", None)                       # 複製出來的圖元是新圖元
    if e["t"] == "line":
        e["p1"], e["p2"] = fp(e["p1"]), fp(e["p2"])
    else:
        e["c"] = fp(e["c"])
        if e["t"] == "arc" and fa:
            a0, a1 = fa(e["a0"]), fa(e["a1"])
            e["a0"], e["a1"] = ((a1, a0) if flip else (a0, a1))
            e["a0"] %= 360.0
            e["a1"] %= 360.0
    return e


def translate_entity(e, dx, dy):
    return _map(e, lambda p: [p[0] + dx, p[1] + dy], lambda a: a)


def rotate_entity(e, center, deg):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    cx, cy = center
    return _map(e, lambda p: [cx + (p[0] - cx) * c - (p[1] - cy) * s,
                              cy + (p[0] - cx) * s + (p[1] - cy) * c], lambda a: a + deg)


def mirror_entity(e, p, q):
    """對通過 p、q 的直線鏡射。"""
    dx, dy = q[0] - p[0], q[1] - p[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        raise ValueError("鏡射線兩點不可重合")
    theta = math.degrees(math.atan2(dy, dx))

    def fp(pt):
        t = ((pt[0] - p[0]) * dx + (pt[1] - p[1]) * dy) / L2
        fx, fy = p[0] + t * dx, p[1] + t * dy
        return [2 * fx - pt[0], 2 * fy - pt[1]]

    return _map(e, fp, lambda a: 2 * theta - a, flip=True)


def mirror(entities, idxs, p, q, keep_original=True):
    new = [mirror_entity(entities[i], p, q) for i in idxs]
    base = entities if keep_original else [e for i, e in enumerate(entities) if i not in set(idxs)]
    return base + new


def linear_pattern(entities, idxs, n, dx, dy):
    """n 為總數量(含原件)。"""
    return entities + [translate_entity(entities[i], k * dx, k * dy)
                       for k in range(1, int(n)) for i in idxs]


def circular_pattern(entities, idxs, n, total_angle, center):
    n = int(n)
    step = total_angle / n if abs(total_angle - 360.0) < 1e-9 else total_angle / max(n - 1, 1)
    return entities + [rotate_entity(entities[i], center, k * step)
                       for k in range(1, n) for i in idxs]


# --- 輸入解析 ---
def parse_input(text: str, last=None, direction=None):
    """解析數值輸入:'x,y' 絕對座標、'@dx,dy' 相對、'@長度<角度' 極座標、單一數字。
    回傳 ("point", (u, v)) 或 ("number", 值)。direction 為單一數字時沿用的單位方向。"""
    s = text.strip().replace(" ", "")
    if not s:
        raise ValueError("輸入是空的")
    rel = s.startswith("@")
    s = s.lstrip("@")
    base = last if (rel and last is not None) else (0.0, 0.0)
    if "<" in s:
        r, a = (float(v) for v in s.split("<"))
        return "point", (base[0] + r * math.cos(math.radians(a)), base[1] + r * math.sin(math.radians(a)))
    if "," in s:
        x, y = (float(v) for v in s.split(","))
        return "point", (base[0] + x, base[1] + y)
    val = float(s)
    if direction is not None and last is not None:
        return "point", (last[0] + val * direction[0], last[1] + val * direction[1])
    return "number", val


# --- 封閉輪廓 ---
def _close(a, b, tol=1e-5):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def closed_loops(entities):
    """找出封閉輪廓。回傳 [[(圖元, 是否反向), ...], ...];只支援單純封閉鏈(每個接點恰連兩段)。"""
    loops = [[(e, False)] for e in entities if is_closed_by_itself(e)]
    segs = [e for e in entities if not is_closed_by_itself(e)]
    used = [False] * len(segs)
    ends = [endpoints(e) for e in segs]
    for i in range(len(segs)):
        if used[i]:
            continue
        chain, cur = [(segs[i], False)], ends[i][1]
        start = ends[i][0]
        used[i] = True
        ok = True
        while not _close(cur, start):
            cand = [(j, k) for j in range(len(segs)) if not used[j] for k in (0, 1)
                    if _close(ends[j][k], cur)]
            if len(cand) != 1:               # 斷開或分岔:不是單純封閉鏈
                ok = False
                break
            j, k = cand[0]
            used[j] = True
            chain.append((segs[j], k == 1))
            cur = ends[j][1 - k]
        if ok and len(chain) >= 1 and (len(chain) > 1 or _close(ends[i][0], ends[i][1])):
            loops.append(chain)
    return loops


def _loop_polygon(loop):
    pts = []
    for e, rev in loop:
        s = sample(e)
        pts += (s[::-1] if rev else s)[:-1]
    return pts


def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def _inside(poly, p):
    x, y, c = p[0], p[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def profiles(entities):
    """[(外輪廓 loop, [孔洞 loop, ...]), ...];孔洞以巢狀奇偶判斷。"""
    loops = closed_loops(entities)
    polys = [_loop_polygon(lp) for lp in loops]
    areas = [abs(_area(p)) for p in polys]
    parents = []
    for i, pi in enumerate(polys):
        cont = [j for j, pj in enumerate(polys) if j != i and areas[j] > areas[i] + 1e-9
                and _inside(pj, pi[0])]
        parents.append(cont)
    out = {}
    for i in range(len(loops)):
        if len(parents[i]) % 2 == 0:
            out[i] = []
    for i in range(len(loops)):
        if len(parents[i]) % 2 == 1:
            par = min(parents[i], key=lambda j: areas[j])
            out[par].append(loops[i])
    return [(loops[i], holes) for i, holes in out.items()]


# --- 轉成 CadQuery(局部座標,平面在 z=0) ---
def _edge(e, rev=False):
    V = lambda p: cq.Vector(p[0], p[1], 0)  # noqa: E731
    if is_closed_by_itself(e):
        return cq.Edge.makeCircle(e["r"], V(e["c"]), cq.Vector(0, 0, 1))
    if e["t"] == "line":
        a, b = (e["p2"], e["p1"]) if rev else (e["p1"], e["p2"])
        return cq.Edge.makeLine(V(a), V(b))
    s, m, t = _pt(e, e["a0"]), _pt(e, e["a0"] + span(e) / 2), _pt(e, e["a0"] + span(e))
    return cq.Edge.makeThreePointArc(V(t if rev else s), V(m), V(s if rev else t))


def _wire(loop):
    return cq.Wire.assembleEdges([_edge(e, r) for e, r in loop])


def local_faces(entities):
    """草圖封閉輪廓 -> 局部座標的面清單(含孔洞)。沒有封閉輪廓時丟出錯誤。"""
    profs = profiles(entities)
    if not profs:
        raise ValueError("草圖中沒有封閉輪廓(線段需首尾相接,或使用圓)")
    return [cq.Face.makeFromWires(_wire(o), [_wire(h) for h in holes]) for o, holes in profs]


def to_global(shape, wp):
    from .features import plane_from_dict
    return shape.transformShape(plane_from_dict(wp).rG)


def extrude_solid(entities, wp, depth, symmetric=False) -> cq.Shape:
    solids = []
    for f in local_faces(entities):
        if symmetric:
            f = f.moved(cq.Location(cq.Vector(0, 0, -depth / 2)))
            depth_eff = depth
        else:
            depth_eff = depth
        solids.append(cq.Solid.extrudeLinear(f, cq.Vector(0, 0, depth_eff)))
    return to_global(_fuse(solids), wp)


def revolve_solid(entities, wp, angle=360.0, axis="Y") -> cq.Shape:
    end = cq.Vector(1, 0, 0) if axis == "X" else cq.Vector(0, 1, 0)
    solids = [cq.Solid.revolve(f, angle, cq.Vector(0, 0, 0), end) for f in local_faces(entities)]
    return to_global(_fuse(solids), wp)


def _fuse(solids):
    res = solids[0]
    for s in solids[1:]:
        res = res.fuse(s)
    return res.clean() if len(solids) > 1 else res


def polylines_global(entities, wp):
    """供顯示用:每個圖元離散成 3D 折線點(numpy 陣列)。"""
    import numpy as np
    from .features import plane_from_dict
    pl = plane_from_dict(wp)
    o, x, y = (np.array(v.toTuple()) for v in (pl.origin, pl.xDir, pl.yDir))
    return [np.array([o + u * x + v * y for u, v in sample(e)]) for e in entities]


# --- 掃掠 ---
def ordered_chain(entities):
    """把草圖圖元排成單一連續路徑 [(圖元, 是否反向), ...](可為封閉)。不是單一連續線時丟出錯誤。"""
    segs = [e for e in entities if not is_closed_by_itself(e)]
    if not segs or len(segs) != len(entities):
        raise ValueError("路徑草圖只能包含相連的線與圓弧(不可有整圓)")
    ends = [endpoints(e) for e in segs]
    # 端點 -> 連到它的 (線段, 端) 清單
    def at(pt, skip):
        return [(j, k) for j in range(len(segs)) if j != skip for k in (0, 1) if _close(ends[j][k], pt)]
    degree = lambda i, k: len(at(ends[i][k], i))  # noqa: E731
    if any(degree(i, k) > 1 for i in range(len(segs)) for k in (0, 1)):
        raise ValueError("路徑不可分岔")
    starts = [i for i in range(len(segs)) if degree(i, 0) == 0 or degree(i, 1) == 0]
    first = starts[0] if starts else 0
    rev = degree(first, 0) != 0 if starts else False        # 讓起點落在沒有鄰居的那端
    chain, used, cur = [(segs[first], rev)], {first}, ends[first][0 if rev else 1]
    while True:
        nxt = [(j, k) for j, k in at(cur, -1) if j not in used]
        if not nxt:
            break
        j, k = nxt[0]
        used.add(j)
        chain.append((segs[j], k == 1))
        cur = ends[j][1 - k]
    if len(used) != len(segs):
        raise ValueError("路徑草圖必須是單一連續的線/圓弧(目前有分離的線段)")
    return chain


def path_wire(entities, wp):
    """路徑草圖 -> 全域座標的 Wire。"""
    return to_global(_wire(ordered_chain(entities)), wp)
