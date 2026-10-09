"""草圖幾何拘束求解器(Levenberg-Marquardt,純 numpy)。

拘束 dict: {"id": n, "t": 類型, "refs": [...], "v": 數值, ...}
  refs 元素:點 [圖元id, 部位](部位: p1/p2=線端點, c=圓心, s/e=圓弧起訖點)或整個圖元 [圖元id]。
類型:
  重合 coincident [P,P]        水平 horizontal [L] 或 [P,P]    垂直 vertical [L] 或 [P,P]
  平行 parallel [L,L]          垂直相交 perpendicular [L,L]   相切 tangent [L|C, L|C](+mode)
  等長/等半徑 equal [L,L]|[C,C]   同心 concentric [C,C]        固定 fix [E] 或 [P](+vals)
  中點 midpoint [P,L]          點在物體上 point_on [P,E]
  尺寸:length [L] / distance [P,P] / hdist [P,P] / vdist [P,P](+sign) / radius [C] / diameter [C]
        / angle [L,L](度);皆以 "v" 為驅動值。
"""
import math

import numpy as np

DIMENSIONAL = {"length", "distance", "hdist", "vdist", "radius", "diameter", "angle"}
NAMES = {
    "coincident": "重合", "horizontal": "水平", "vertical": "垂直", "parallel": "平行",
    "perpendicular": "垂直相交", "tangent": "相切", "equal": "等長/等半徑", "concentric": "同心",
    "fix": "固定", "midpoint": "中點", "point_on": "點在物體上",
    "length": "長度", "distance": "距離", "hdist": "水平距離", "vdist": "垂直距離",
    "radius": "半徑", "diameter": "直徑", "angle": "角度",
}
_NV = {"line": 4, "circle": 3, "arc": 5}


# --- 圖元 <-> 變數 ---
def _span(e):
    s = (e["a1"] - e["a0"]) % 360.0
    return s if s > 1e-9 else 360.0


def get_vars(e):
    if e["t"] == "line":
        return [*e["p1"], *e["p2"]]
    if e["t"] == "circle":
        return [*e["c"], e["r"]]
    a0 = math.radians(e["a0"])
    return [*e["c"], e["r"], a0, a0 + math.radians(_span(e))]


def set_vars(e, v):
    e = dict(e)
    if e["t"] == "line":
        e["p1"], e["p2"] = [float(v[0]), float(v[1])], [float(v[2]), float(v[3])]
    elif e["t"] == "circle":
        e["c"], e["r"] = [float(v[0]), float(v[1])], abs(float(v[2]))
    else:
        e["c"], e["r"] = [float(v[0]), float(v[1])], abs(float(v[2]))
        a0, a1 = math.degrees(v[3]), math.degrees(v[4])
        e["a0"], e["a1"] = a0 % 360.0, a1 % 360.0
    return e


class _Ctx:
    def __init__(self, entities):
        self.info, off = {}, 0
        for e in entities:
            self.info[e["id"]] = (e["t"], off)
            off += _NV[e["t"]]
        self.n = off
        self.x0 = np.concatenate([get_vars(e) for e in entities]) if entities else np.zeros(0)

    def P(self, x, ref):
        t, o = self.info[ref[0]]
        part = ref[1]
        if t == "line":
            i = o if part == "p1" else o + 2
            return x[i], x[i + 1]
        if part == "c":
            return x[o], x[o + 1]
        a = x[o + 3] if part == "s" else x[o + 4]
        return x[o] + x[o + 2] * math.cos(a), x[o + 1] + x[o + 2] * math.sin(a)

    def L(self, x, ref):
        o = self.info[ref[0]][1]
        return (x[o], x[o + 1]), (x[o + 2], x[o + 3])

    def C(self, x, ref):
        o = self.info[ref[0]][1]
        return x[o], x[o + 1], x[o + 2]


def _dir(ctx, x, ref):
    (ax, ay), (bx, by) = ctx.L(x, ref)
    return bx - ax, by - ay


def _res(c, x, ctx):
    t, r = c["t"], c["refs"]
    if t == "coincident":
        a, b = ctx.P(x, r[0]), ctx.P(x, r[1])
        return [a[0] - b[0], a[1] - b[1]]
    if t in ("horizontal", "vertical"):
        if len(r) == 1:
            (ax, ay), (bx, by) = ctx.L(x, r[0])
        else:
            (ax, ay), (bx, by) = ctx.P(x, r[0]), ctx.P(x, r[1])
        return [by - ay] if t == "horizontal" else [bx - ax]
    if t in ("parallel", "perpendicular"):
        d1, d2 = _dir(ctx, x, r[0]), _dir(ctx, x, r[1])
        n = math.hypot(*d1) * math.hypot(*d2) + 1e-12
        cross, dot = d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]
        return [(cross if t == "parallel" else dot) / n]
    if t == "equal":
        if ctx.info[r[0][0]][0] == "line":
            return [math.hypot(*_dir(ctx, x, r[0])) - math.hypot(*_dir(ctx, x, r[1]))]
        return [ctx.C(x, r[0])[2] - ctx.C(x, r[1])[2]]
    if t == "concentric":
        a, b = ctx.C(x, r[0]), ctx.C(x, r[1])
        return [a[0] - b[0], a[1] - b[1]]
    if t == "tangent":
        k = [ctx.info[q[0]][0] for q in r]
        if "line" in k:
            li, ci = (0, 1) if k[0] == "line" else (1, 0)
            (ax, ay), (bx, by) = ctx.L(x, r[li])
            cx, cy, rad = ctx.C(x, r[ci])
            dx, dy = bx - ax, by - ay
            dist = (dx * (cy - ay) - dy * (cx - ax)) / (math.hypot(dx, dy) + 1e-12)
            return [abs(dist) - rad]
        (x1, y1, r1), (x2, y2, r2) = ctx.C(x, r[0]), ctx.C(x, r[1])
        d = math.hypot(x1 - x2, y1 - y2)
        return [d - (r1 + r2) if c.get("mode", "ext") == "ext" else d - abs(r1 - r2)]
    if t == "fix":
        vals = c["vals"]
        if len(r[0]) == 2:
            p = ctx.P(x, r[0])
            return [p[0] - vals[0], p[1] - vals[1]]
        o = ctx.info[r[0][0]][1]
        return [x[o + i] - v for i, v in enumerate(vals)]
    if t == "midpoint":
        p = ctx.P(x, r[0])
        (ax, ay), (bx, by) = ctx.L(x, r[1])
        return [p[0] - (ax + bx) / 2, p[1] - (ay + by) / 2]
    if t == "point_on":
        px, py = ctx.P(x, r[0])
        if ctx.info[r[1][0]][0] == "line":
            (ax, ay), (bx, by) = ctx.L(x, r[1])
            dx, dy = bx - ax, by - ay
            return [(dx * (py - ay) - dy * (px - ax)) / (math.hypot(dx, dy) + 1e-12)]
        cx, cy, rad = ctx.C(x, r[1])
        return [math.hypot(px - cx, py - cy) - rad]
    # --- 尺寸 ---
    v = c["v"]
    if t == "length":
        return [math.hypot(*_dir(ctx, x, r[0])) - v]
    if t in ("distance", "hdist", "vdist"):
        a, b = ctx.P(x, r[0]), ctx.P(x, r[1])
        if t == "distance":
            return [math.hypot(a[0] - b[0], a[1] - b[1]) - v]
        i = 0 if t == "hdist" else 1
        return [c.get("sign", 1) * (b[i] - a[i]) - v]
    if t == "radius":
        return [ctx.C(x, r[0])[2] - v]
    if t == "diameter":
        return [2 * ctx.C(x, r[0])[2] - v]
    if t == "angle":
        d1, d2 = _dir(ctx, x, r[0]), _dir(ctx, x, r[1])
        th = math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
        diff = th - math.radians(v)
        return [math.atan2(math.sin(diff), math.cos(diff))]
    raise ValueError(f"未知拘束: {t}")


def _residual(constraints, x, ctx):
    out = []
    for c in constraints:
        out.extend(_res(c, x, ctx))
    return np.asarray(out, dtype=float)


def _jac(f, x, r0, central=False):
    n, m = len(x), len(r0)
    J = np.zeros((m, n))
    for i in range(n):
        h = 1e-7 * (1.0 + abs(x[i]))
        xp = x.copy()
        xp[i] += h
        if central:
            xm = x.copy()
            xm[i] -= h
            J[:, i] = (f(xp) - f(xm)) / (2 * h)
        else:
            J[:, i] = (f(xp) - r0) / h
    return J


def _lm(f, x0, max_iter=200):
    x, r, lam = x0.copy(), f(x0), 1e-3
    for _ in range(max_iter):
        if len(r) == 0 or np.max(np.abs(r)) < 1e-11:
            break
        J = _jac(f, x, r)
        A, g = J.T @ J, J.T @ r
        improved = False
        while lam < 1e12:
            try:
                dx = -np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            r2 = f(x + dx)
            if r2 @ r2 < r @ r:
                x, r, lam, improved = x + dx, r2, max(lam / 3, 1e-12), True
                break
            lam *= 4
        if not improved:
            break
    return x, r


# --- 對外 API ---
def solve(entities, constraints):
    """求解拘束。回傳 (成功?, 新圖元清單, 自由度, 最大殘差)。失敗時圖元維持原樣。"""
    if not entities:
        return True, entities, 0, 0.0
    ctx = _Ctx(entities)
    cons = [c for c in constraints if all(q[0] in ctx.info for q in c["refs"])]
    f = lambda x: _residual(cons, x, ctx)  # noqa: E731
    x, r = _lm(f, ctx.x0)
    err = float(np.max(np.abs(r))) if len(r) else 0.0
    ok = err < 1e-6
    out = entities
    if ok:
        out, off = [], 0
        for e in entities:
            n = _NV[e["t"]]
            out.append(set_vars(e, x[off:off + n]))
            off += n
    return ok, out, _dof(f, x, ctx.n), err


def _dof(f, x, n):
    r = f(x)
    if len(r) == 0:
        return n
    s = np.linalg.svd(_jac(f, x, r, central=True), compute_uv=False)
    rank = int(np.sum(s > 1e-6 * max(1.0, s.max() if len(s) else 1.0)))
    return n - rank


def dof(entities, constraints):
    if not entities:
        return 0
    ctx = _Ctx(entities)
    cons = [c for c in constraints if all(q[0] in ctx.info for q in c["refs"])]
    return _dof(lambda x: _residual(cons, x, ctx), ctx.x0, ctx.n)


def prune(entities, constraints):
    """移除參照到已不存在圖元的拘束。"""
    ids = {e["id"] for e in entities}
    return [c for c in constraints if all(q[0] in ids for q in c["refs"])]


def measure(entities, c):
    """目前幾何下,尺寸拘束的實際量測值(供建立尺寸時預設)。"""
    ctx = _Ctx(entities)
    x = ctx.x0
    r = c["refs"]
    t = c["t"]
    if t == "length":
        return math.hypot(*_dir(ctx, x, r[0]))
    if t in ("distance", "hdist", "vdist"):
        a, b = ctx.P(x, r[0]), ctx.P(x, r[1])
        if t == "distance":
            return math.hypot(a[0] - b[0], a[1] - b[1])
        i = 0 if t == "hdist" else 1
        return abs(b[i] - a[i])
    if t == "radius":
        return ctx.C(x, r[0])[2]
    if t == "diameter":
        return 2 * ctx.C(x, r[0])[2]
    if t == "angle":
        d1, d2 = _dir(ctx, x, r[0]), _dir(ctx, x, r[1])
        return math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
    raise ValueError("非尺寸拘束")


def point_coords(entities, ref):
    ctx = _Ctx(entities)
    return ctx.P(ctx.x0, ref)
