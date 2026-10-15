"""3D 列印準備:網格檢查(封閉性/法向/退化)、擺放方向分析、支撐預估與支撐實體產生。
單位 mm;建構方向為 +Z,列印平台為 Z = 最低點(落地後為 0)。支撐預估為幾何近似,非切片器級結果。"""
import math
import os
import struct

import cadquery as cq
import numpy as np

SUPPORT_TYPES = {"格狀": 1.0, "線狀": 0.8, "樹狀": 0.5}          # 體積估算係數
FILAMENT_DENSITY = 1.24                                         # g/cm³ (PLA)


# ---------- 取得三角網 ----------
def shape_mesh(shape: cq.Shape, tol: float = 0.05, ang: float = 0.2):
    """回傳 (V, T):頂點 (n,3) 與三角形索引 (m,3)(逐面細分,面與面之間的頂點未合併)。"""
    verts, tris = shape.tessellate(tol, ang)
    if not tris:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    V = np.array([[v.x, v.y, v.z] for v in verts], float)
    return V, np.array(tris, int)


def read_stl(path: str):
    """讀二進位或 ASCII STL,回傳 (V, T)(未合併頂點)。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(84)
        n = int.from_bytes(head[80:84], "little") if len(head) == 84 else -1
        if len(head) == 84 and 84 + 50 * n == size:
            data = np.frombuffer(f.read(50 * n), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
            V = data["v"].reshape(-1, 3).astype(float)
            return V, np.arange(len(V)).reshape(-1, 3)
    pts = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            t = line.split()
            if t[:1] == ["vertex"]:
                pts.append([float(x) for x in t[1:4]])
    if not pts or len(pts) % 3:
        raise ValueError("無法解析 STL 檔案")
    V = np.array(pts)
    return V, np.arange(len(V)).reshape(-1, 3)


def weld(V, T, tol: float = 1e-5):
    """依座標合併重複頂點,回傳 (V2, T2)。"""
    if len(V) == 0:
        return V, T
    scale = max(float(np.ptp(V, axis=0).max()), 1.0)
    key = np.round(V / (tol * scale)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return V[first], inv.reshape(-1)[T]


def _tri_normals_areas(V, T):
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    cr = np.cross(b - a, c - a)
    ar = np.linalg.norm(cr, axis=1) / 2
    n = cr / np.maximum(2 * ar, 1e-300)[:, None]
    return n, ar


# ---------- 檢查 ----------
def check_mesh(V, T) -> dict:
    """網格健檢。watertight = 無邊界邊且無非流形邊;inverted = 有向體積為負(法向朝內)。"""
    V, T = weld(V, T)
    if len(T) == 0:
        raise ValueError("沒有三角形可檢查")
    _, ar = _tri_normals_areas(V, T)
    degenerate = int(np.sum(ar < 1e-10))
    T = T[(T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])]
    de = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])             # 有向邊
    und = np.sort(de, axis=1)
    keys, inv, cnt = np.unique(und, axis=0, return_inverse=True, return_counts=True)
    boundary = int(np.sum(cnt == 1))
    nonmanifold = int(np.sum(cnt > 2))
    # 同向使用兩次的邊 = 相鄰三角形法向不一致
    dkey = de[:, 0].astype(np.int64) * len(V) + de[:, 1]
    _, dcnt = np.unique(dkey, return_counts=True)
    inconsistent = int(np.sum(dcnt > 1))
    vol = float(np.sum(np.einsum("ij,ij->i", V[T[:, 0]], np.cross(V[T[:, 1]], V[T[:, 2]]))) / 6)
    # 連通殼數
    parent = np.arange(len(V))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, c in T:
        for u, v in ((a, b), (b, c)):
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[ru] = rv
    used = np.unique(T)
    shells = len({find(i) for i in used})
    issues = []
    if boundary:
        issues.append(f"有 {boundary} 條開放邊(不封閉,切片器可能無法判斷內外)")
    if nonmanifold:
        issues.append(f"有 {nonmanifold} 條非流形邊(三個以上的面共用一條邊)")
    if inconsistent and not boundary:
        issues.append(f"有 {inconsistent} 條邊的相鄰面法向不一致")
    if vol < 0 and not boundary:
        issues.append("整體法向朝內(有向體積為負),需要翻轉")
    if degenerate:
        issues.append(f"有 {degenerate} 個退化三角形(面積幾乎為 0)")
    watertight = boundary == 0 and nonmanifold == 0
    return {"triangles": int(len(T)), "vertices": int(len(V)), "boundary_edges": boundary,
            "nonmanifold_edges": nonmanifold, "inconsistent_edges": inconsistent, "degenerate": degenerate,
            "shells": int(shells), "volume": abs(vol) if watertight else vol, "watertight": watertight,
            "inverted": bool(vol < 0 and watertight), "issues": issues, "ok": not issues}


def check_shape(shape: cq.Shape, bed=(220.0, 220.0, 250.0)) -> dict:
    """實體健檢:網格 + 幾何有效性 + 是否超出列印平台。"""
    V, T = shape_mesh(shape)
    if not shape.Solids():
        raise ValueError("曲面體不能列印:請先縫合成實體或加厚")
    r = check_mesh(V, T)
    if not shape.isValid():
        r["issues"].append("OCC 幾何驗證未通過(形狀可能有自交或破面)")
    bb = shape.BoundingBox()
    size = (bb.xlen, bb.ylen, bb.zlen)
    r["size"] = [round(s, 3) for s in size]
    fits = any(all(s <= b + 1e-6 for s, b in zip(sorted(size), sorted(bed))) for _ in (0,))
    r["fits_bed"] = bool(fits)
    if not fits:
        r["issues"].append(f"尺寸 {size[0]:.1f}×{size[1]:.1f}×{size[2]:.1f} 超出列印平台 {bed[0]:g}×{bed[1]:g}×{bed[2]:g}(任意擺放也放不下)")
    r["ok"] = not r["issues"]
    return r


# ---------- 方向與支撐 ----------
def rotation_to_down(n):
    """旋轉 (軸, 角度°),使方向 n 轉成 -Z。"""
    n = np.asarray(n, float) / np.linalg.norm(n)
    down = np.array([0.0, 0.0, -1.0])
    axis = np.cross(n, down)
    s = np.linalg.norm(axis)
    if s < 1e-9:
        return (np.array([1.0, 0, 0]), 0.0 if n[2] < 0 else 180.0)
    return axis / s, math.degrees(math.atan2(s, float(np.dot(n, down))))


def _rot_matrix(axis, deg):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)


def _grounded(V, R=None):
    W = V @ R.T if R is not None else V.copy()
    W[:, 2] -= W[:, 2].min()
    return W


def vertical_hits(W, T, xy, chunk: int = 200):
    """沿 Z 方向的射線與網格的所有交點:對每個 (x,y) 回傳 [(z, 三角形索引), ...](依 z 由小到大,已去除邊上的重複)。"""
    a, b, c = W[T[:, 0]], W[T[:, 1]], W[T[:, 2]]
    cr = np.cross(b - a, c - a)
    ok = np.abs(cr[:, 2]) > 1e-12                                # 垂直面投影面積為 0,略過
    idx = np.flatnonzero(ok)
    a, b, c, cr = a[idx], b[idx], c[idx], cr[idx]
    mn = np.minimum(np.minimum(a[:, :2], b[:, :2]), c[:, :2]) - 1e-9
    mx = np.maximum(np.maximum(a[:, :2], b[:, :2]), c[:, :2]) + 1e-9
    xy = np.asarray(xy, float)
    out = []
    for s0 in range(0, len(xy), chunk):
        P = xy[s0:s0 + chunk]
        cand = ((P[:, None, 0] >= mn[None, :, 0]) & (P[:, None, 0] <= mx[None, :, 0])
                & (P[:, None, 1] >= mn[None, :, 1]) & (P[:, None, 1] <= mx[None, :, 1]))
        for k in range(len(P)):
            ti = np.flatnonzero(cand[k])
            if len(ti) == 0:
                out.append([])
                continue
            x, y = P[k]
            A, B, C = a[ti], b[ti], c[ti]
            d = cr[ti, 2]
            w0 = ((B[:, 0] - x) * (C[:, 1] - y) - (C[:, 0] - x) * (B[:, 1] - y)) / d
            w1 = ((C[:, 0] - x) * (A[:, 1] - y) - (A[:, 0] - x) * (C[:, 1] - y)) / d
            w2 = 1.0 - w0 - w1
            eps = -1e-9
            inside = (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
            ti2 = ti[inside]
            z = (w0 * A[:, 2] + w1 * B[:, 2] + w2 * C[:, 2])[inside]
            hits = sorted(zip(z.tolist(), idx[ti2].tolist()))
            dedup = []
            for zz, t in hits:
                if dedup and abs(zz - dedup[-1][0]) < 1e-6:
                    continue
                dedup.append((zz, t))
            out.append(dedup)
    return out


def support_estimate(V, T, threshold: float = 45.0, density_pct: float = 15.0, support_type: str = "格狀",
                     scope: str = "全部", gap: float = 0.2, filament_density: float = FILAMENT_DENSITY,
                     flow: float = 10.0, max_samples: int = 800, grounded: bool = False) -> dict:
    """估算懸伸面積與支撐用量。V,T 為已落地(Z 最低 = 0)的網格,否則自動落地(grounded=False)。
    scope: 全部(模型上也可長支撐)/ 僅平台(只允許從列印平台長出,落在模型上的懸伸區視為無法支撐)。"""
    if support_type not in SUPPORT_TYPES:
        raise ValueError(f"支撐類型需為 {list(SUPPORT_TYPES)}")
    V, T = weld(V, T)
    W = V if grounded else _grounded(V)
    n, ar = _tri_normals_areas(W, T)
    cen = W[T].mean(axis=1)
    sin_t = math.sin(math.radians(threshold))
    on_bed = cen[:, 2] < 1e-6 + 1e-3
    over = (-n[:, 2] > sin_t) & ~on_bed
    over_area = float(ar[over].sum())
    height = float(W[:, 2].max())
    base = float(ar[on_bed & (-n[:, 2] > 0.99)].sum())
    res = {"mesh_vertices": V, "mesh_tris": T, "overhang_area": over_area, "overhang_triangles": int(over.sum()), "height": height, "base_area": base,
           "support_volume": 0.0, "unsupportable_area": 0.0, "overhang_mask": over}
    if over.any():
        idx = np.flatnonzero(over)
        if len(idx) > max_samples:                      # 依面積加權抽樣
            w = ar[idx] / ar[idx].sum()
            pick = np.random.default_rng(0).choice(len(idx), max_samples, replace=False, p=w)
            idx_s = idx[pick]
            scale = ar[idx].sum() / ar[idx_s].sum()
        else:
            idx_s, scale = idx, 1.0
        hits = vertical_hits(W, T, cen[idx_s, :2])
        floor = np.full(len(idx_s), -np.inf)
        for k, hs in enumerate(hits):
            below = [z for z, t in hs if z < cen[idx_s[k], 2] - 1e-4]
            if below:
                floor[k] = max(below)
        lands = np.isfinite(floor)
        bottom = np.where(lands, floor, 0.0)
        h = np.maximum(cen[idx_s, 2] - bottom - gap, 0.0)
        proj = ar[idx_s] * np.abs(n[idx_s, 2]) * scale
        if scope == "僅平台":
            res["unsupportable_area"] = float((ar[idx_s] * scale)[lands].sum())
            h = np.where(lands, 0.0, h)
        res["support_volume"] = float((proj * h).sum() * density_pct / 100.0 * SUPPORT_TYPES[support_type])
    mass = res["support_volume"] / 1000.0 * filament_density
    res["support_mass_g"] = mass
    res["extra_time_min"] = res["support_volume"] / max(flow, 1e-9) / 60.0
    return res


def orientation_candidates(V, T, min_area_frac: float = 0.03, max_faces: int = 8):
    """候選擺放:6 個軸向 + 最大的幾個平面朝下。回傳 [(名稱, 3×3 旋轉矩陣)]。"""
    cands = [("原方向", np.eye(3))]
    for name, n in (("底面 -Z(原)", None), ("+Z 朝下", (0, 0, 1)), ("+X 朝下", (1, 0, 0)), ("-X 朝下", (-1, 0, 0)),
                    ("+Y 朝下", (0, 1, 0)), ("-Y 朝下", (0, -1, 0))):
        if n is not None:
            ax, ang = rotation_to_down(n)
            cands.append((name, _rot_matrix(ax, ang)))
    W, Tw = weld(V, T)
    nn, ar = _tri_normals_areas(W, Tw)
    total = ar.sum()
    keyed = {}
    for ni, a in zip(np.round(nn, 3), ar):
        keyed[tuple(ni)] = keyed.get(tuple(ni), 0.0) + a
    big = sorted(keyed.items(), key=lambda kv: -kv[1])
    known = [np.array(n) for n in ((0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))]
    for nrm, a in big[:max_faces * 3]:
        if a < min_area_frac * total or len(cands) >= 7 + max_faces:
            break
        nv = np.array(nrm)
        if any(np.allclose(nv, k, atol=1e-2) for k in known):
            continue
        ax, ang = rotation_to_down(nv)
        cands.append((f"平面朝下 ({nv[0]:.2f},{nv[1]:.2f},{nv[2]:.2f})", _rot_matrix(ax, ang)))
        known.append(nv)
    return cands


def analyze_orientations(V, T, top: int = 5, w_height: float = 0.3, w_base: float = 0.2, **support_kw) -> list:
    """逐一評估候選擺放,回傳依成本由低到高的前 top 名:
    cost = 支撐體積/模型體積 + w_height×(高度/最大邊長) − w_base×(底面接觸面積/總表面積)。"""
    V, T = weld(V, T)
    n0, a0 = _tri_normals_areas(V, T)
    total_area = float(a0.sum())
    chk = check_mesh(V, T)
    vol = abs(chk["volume"]) or 1.0
    diag = float(np.ptp(V, axis=0).max())
    rows = []
    for name, R in orientation_candidates(V, T):
        W = _grounded(V, R)
        est = support_estimate(W, T, grounded=True, **support_kw)
        cost = est["support_volume"] / vol + w_height * est["height"] / max(diag, 1e-9) \
            - w_base * est["base_area"] / max(total_area, 1e-9)
        rows.append({"name": name, "rotation": R, "cost": float(cost), **{k: v for k, v in est.items() if k != "overhang_mask"}})
    rows.sort(key=lambda r: r["cost"])
    return rows[:top]


def axis_angle_from_matrix(R):
    """旋轉矩陣 -> (單位軸, 角度°)。"""
    ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
    if ang < 1e-9:
        return np.array([0.0, 0.0, 1.0]), 0.0
    if abs(ang - 180) < 1e-6:
        w, v = np.linalg.eigh((R + np.eye(3)) / 2)
        return v[:, -1] / np.linalg.norm(v[:, -1]), 180.0
    ax = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return ax / np.linalg.norm(ax), ang


def orient_shape(shape: cq.Shape, axis, angle: float, ground: bool = True) -> cq.Shape:
    c = shape.Center()
    out = shape
    if abs(angle) > 1e-9:
        out = shape.rotate(c, c + cq.Vector(*[float(x) for x in axis]), angle)
    if ground:
        out = out.moved(cq.Location(cq.Vector(0, 0, -out.BoundingBox().zmin)))
    return out


# ---------- 支撐實體 ----------
def build_supports(shape: cq.Shape, threshold: float = 45.0, support_type: str = "格狀", spacing: float = 4.0,
                   thickness: float = 0.8, gap: float = 0.2, scope: str = "全部", max_parts: int = 4000) -> cq.Shape:
    """在懸伸面下方產生支撐實體(柱 + 牆)。shape 應已落地(Z 最低 = 0)。
    格狀:支撐柱 + X/Y 方向連接牆;線狀:只有 X 方向牆;樹狀:以兩倍間距的稀疏柱近似。"""
    if support_type not in SUPPORT_TYPES:
        raise ValueError(f"支撐類型需為 {list(SUPPORT_TYPES)}")
    if spacing <= thickness:
        raise ValueError("間距必須大於支撐厚度")
    V, T = shape_mesh(shape)
    V, T = weld(V, T)
    n, ar = _tri_normals_areas(V, T)
    sp = spacing * (2 if support_type == "樹狀" else 1)
    lo, hi = V.min(axis=0), V.max(axis=0)
    xs, ys = np.arange(lo[0] + sp / 2, hi[0], sp), np.arange(lo[1] + sp / 2, hi[1], sp)
    if len(xs) * len(ys) > 40000:
        raise ValueError("支撐格點太多,請加大間距")
    sin_t = math.sin(math.radians(threshold))
    cols = {}                                           # 格點編號 -> [(z_bottom, z_top)]
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    allhits = vertical_hits(V, T, np.column_stack([gx.ravel(), gy.ravel()]))
    for r, hs in enumerate(allhits):
        below = lo[2]
        for z, c in hs:                                 # 由下往上依序遇到的表面
            if -n[c, 2] > sin_t:                        # 朝下的面:進入模型,其下方需要支撐
                top = z - gap
                if top - below > 0.3 and (scope == "全部" or below <= lo[2] + 1e-6):
                    cols.setdefault(r, []).append((below, top))
            elif n[c, 2] > 1e-6:                        # 朝上的面:支撐可以落在這裡
                below = z + gap if scope == "全部" else below
    # 四個角落都要落在模型外且柱身範圍內沒有其他表面,避免支撐柱穿進模型
    h2 = thickness / 2
    keys = [(r, k) for r, spans in cols.items() for k in range(len(spans))]
    corner_pts = []
    for r, _ in keys:
        i, j = divmod(r, len(ys))
        corner_pts += [(xs[i] + dx * h2, ys[j] + dy * h2) for dx in (-1, 1) for dy in (-1, 1)]
    chits = vertical_hits(V, T, np.array(corner_pts)) if corner_pts else []
    clean = {}
    for q, (r, k) in enumerate(keys):
        zb, zt = cols[r][k]
        good = True
        for hs in chits[4 * q:4 * q + 4]:
            if any(zb + 1e-6 < z < zt for z, _ in hs) or sum(1 for z, _ in hs if z < zb + 1e-6) % 2:
                good = False
                break
        if good:
            clean.setdefault(r, []).append((zb, zt))
    cols = clean
    boxes, hmap = [], {}
    for r, spans in cols.items():
        i, j = divmod(r, len(ys))
        for (zb, zt) in spans:
            hmap[(i, j)] = (zb, zt)
            boxes.append(cq.Solid.makeBox(thickness, thickness, zt - zb,
                                          cq.Vector(xs[i] - thickness / 2, ys[j] - thickness / 2, zb)))
    if support_type in ("格狀", "線狀"):
        for (i, j), (zb, zt) in list(hmap.items()):
            for di, dj in ((1, 0), (0, 1)) if support_type == "格狀" else ((1, 0),):
                nb = hmap.get((i + di, j + dj))
                if nb is None:
                    continue
                z0, z1 = max(zb, nb[0]), min(zt, nb[1])
                if z1 - z0 < 0.3:
                    continue
                x0, y0 = xs[i] - thickness / 2, ys[j] - thickness / 2
                if di:
                    boxes.append(cq.Solid.makeBox(sp, thickness, z1 - z0, cq.Vector(x0, y0, z0)))
                else:
                    boxes.append(cq.Solid.makeBox(thickness, sp, z1 - z0, cq.Vector(x0, y0, z0)))
    if not boxes:
        raise ValueError("沒有需要支撐的懸伸區(或間距過大/範圍限制為僅平台)")
    if len(boxes) > max_parts:
        raise ValueError(f"支撐零件太多({len(boxes)} 個),請加大間距")
    return cq.Compound.makeCompound(boxes)
