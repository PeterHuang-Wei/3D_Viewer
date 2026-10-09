"""互動式草圖編輯器:在鎖定平面上以滑鼠(或數值輸入)畫線、矩形、圓、圓弧,並可修整、鏡射、陣列。"""
import copy
import math

import numpy as np
import pyvista as pv

from core import features as F
from core import sketch2d as S
from core import sketch_solver as K

TOOLS = {
    "select": "選取", "line": "線", "rect": "矩形", "circle": "圓", "arc": "圓弧(三點)",
    "trim": "修整", "delete": "刪除", "mirror2": "鏡射(兩點定軸)",
}
# 拘束/標註工具: 工具 -> (標籤, 拘束類型, 可接受的選取序列) ;P=點 L=直線 C=圓/圓弧 E=任一圖元
CONSTRAINT_TOOLS = {
    "c_coincident": ("重合", "coincident", [("P", "P")]),
    "c_horizontal": ("水平", "horizontal", [("L",), ("P", "P")]),
    "c_vertical": ("垂直", "vertical", [("L",), ("P", "P")]),
    "c_parallel": ("平行", "parallel", [("L", "L")]),
    "c_perpendicular": ("垂直相交", "perpendicular", [("L", "L")]),
    "c_tangent": ("相切", "tangent", [("L", "C"), ("C", "L"), ("C", "C")]),
    "c_equal": ("等長/等半徑", "equal", [("L", "L"), ("C", "C")]),
    "c_concentric": ("同心", "concentric", [("C", "C")]),
    "c_fix": ("固定", "fix", [("L",), ("C",), ("P",)]),
    "c_midpoint": ("中點", "midpoint", [("P", "L")]),
    "c_point_on": ("點在物體上", "point_on", [("P", "E")]),
    "d_size": ("尺寸:長度/直徑/半徑", "size", [("L",), ("C",)]),
    "d_distance": ("尺寸:兩點距離", "distance", [("P", "P")]),
    "d_hdist": ("尺寸:水平距離", "hdist", [("P", "P")]),
    "d_vdist": ("尺寸:垂直距離", "vdist", [("P", "P")]),
    "d_angle": ("尺寸:角度", "angle", [("L", "L")]),
}
CONS_HINT = "依序點選要拘束的{}(點選端點/圓心為「點」,點選線身為「線」)"
SYMBOLS = {"horizontal": "H", "vertical": "V", "parallel": "//", "perpendicular": "|_", "tangent": "T",
           "equal": "=", "concentric": "O", "fix": "F", "midpoint": "M", "point_on": "o"}
HINTS = {
    "select": "點選圖元可選取/取消選取(供鏡射、陣列、刪除使用)",
    "line": "點選起點,再點選下一點;右鍵或 Esc 結束連續線",
    "rect": "點選第一個角點,再點選對角點",
    "circle": "點選圓心,再點選圓上一點(或輸入半徑數值)",
    "arc": "依序點選:起點、弧上一點、終點",
    "trim": "點選要修整掉的線段(到相鄰交點為止)",
    "delete": "點選要刪除的圖元",
    "mirror2": "點選鏡射線的兩個點",
}
ACTORS = ("sk_ent", "sk_sel", "sk_prev", "sk_snap", "sk_axes", "sk_dims", "sk_dimlbl", "sk_cons", "sk_hi", "sk_coin")


def lines_poly(polys) -> pv.PolyData:
    pts, cells, off = [], [], 0
    for p in polys:
        pts.append(p)
        cells.extend([len(p), *range(off, off + len(p))])
        off += len(p)
    if not pts:
        return pv.PolyData()
    return pv.PolyData(np.vstack(pts), lines=np.asarray(cells))


class SketchEditor:
    def __init__(self, scene, wp, entities=None, status=None, constraints=None):
        self.scene = scene
        self.wp = wp
        self.plane = F.plane_from_dict(wp)
        self.entities = S.assign_ids(copy.deepcopy(entities or []))
        self.constraints = copy.deepcopy(constraints or [])
        self.highlight = []                       # 要強調的圖元編號(選取拘束時)
        self.pick_buf: list = []                  # 拘束工具已選取的參照
        self.ask_value = lambda title, current: None   # 由主視窗提供數值輸入對話框
        self.sel: set[int] = set()
        self.tool = "line"
        self.pts: list[list[float]] = []
        self.hover_uv = None
        self.snap_kind = None
        self.grid = True
        self.grid_step = 1.0
        self._undo, self._redo = [], []
        self.status = status or (lambda m: None)
        self.on_change = None

    # --- 座標轉換 ---
    def _vec(self, v):
        return np.array(v.toTuple())

    def to3d(self, uv):
        o, x, y = self._vec(self.plane.origin), self._vec(self.plane.xDir), self._vec(self.plane.yDir)
        return o + uv[0] * x + uv[1] * y

    def uv_from_display(self, x, y):
        """螢幕座標 -> 草圖座標 (u, v) 與 3D 點;視線與平面平行時回傳 None。"""
        a = self.scene._world_at(x, y, 0.0)
        b = self.scene._world_at(x, y, 1.0)
        d = b - a
        n, o = self._vec(self.plane.zDir), self._vec(self.plane.origin)
        den = float(n @ d)
        if abs(den) < 1e-12:
            return None
        P = a + float(n @ (o - a)) / den * d
        rel = P - o
        return (float(rel @ self._vec(self.plane.xDir)), float(rel @ self._vec(self.plane.yDir))), P

    def _tol(self, P, pixels=10):
        r = self.scene.plotter.renderer
        r.SetWorldPoint(*P, 1.0)
        r.WorldToDisplay()
        x, y, z = r.GetDisplayPoint()
        w = np.linalg.norm(self.scene._world_at(x + pixels, y, z) - self.scene._world_at(x, y, z))
        return float(w)

    # --- 吸附 ---
    def snap(self, uv, tol):
        best, best_d, kind = None, tol, None
        for q in [[0.0, 0.0]] + [p for e in self.entities for p in S.snap_points(e)]:
            d = math.hypot(q[0] - uv[0], q[1] - uv[1])
            if d <= best_d:
                best, best_d, kind = q, d, "特徵點"
        if best is not None:
            return list(best), kind
        if self.grid and self.grid_step > 0:
            g = self.grid_step
            return [round(uv[0] / g) * g, round(uv[1] / g) * g], "格點"
        return list(uv), None

    # --- 滑鼠 ---
    def hover(self, x, y):
        hit = self.uv_from_display(x, y)
        if hit is None:
            return
        uv, P = hit
        self.hover_uv, self.snap_kind = self.snap(uv, self._tol(P))
        self._redraw()

    def click(self, x, y):
        hit = self.uv_from_display(x, y)
        if hit is None:
            return
        uv, P = hit
        tol = self._tol(P)
        pt, _ = self.snap(uv, tol)
        self._point(pt, uv, tol)

    def _snap_state(self):
        return copy.deepcopy((self.entities, self.constraints))

    def _restore(self, state):
        self.entities, self.constraints = state

    def _mutate(self):
        self._undo.append(self._snap_state())
        self._redo.clear()

    def _point(self, pt, raw, tol):
        t, ents = self.tool, self.entities
        if t in CONSTRAINT_TOOLS:
            self._constraint_pick(raw, tol)
            return
        n0 = len(ents)
        if t in ("select", "delete", "trim"):
            i = S.nearest_entity(ents, raw, tol)
            if i is None:
                if t == "select":
                    self.sel.clear()
            elif t == "select":
                self.sel ^= {i}
            elif t == "delete":
                self._mutate()
                del ents[i]
                self.sel.clear()
            else:
                self._mutate()
                self.entities = S.trim(ents, i, raw)
                self.sel.clear()
        elif t == "line":
            if self.pts and S_dist(self.pts[-1], pt) > 1e-9:
                self._mutate()
                ents.append(S.line(self.pts[-1], pt))
            self.pts = [pt]
        elif t == "rect":
            if not self.pts:
                self.pts = [pt]
            elif abs(pt[0] - self.pts[0][0]) > 1e-9 and abs(pt[1] - self.pts[0][1]) > 1e-9:
                self._mutate()
                ents.extend(S.rectangle(self.pts[0], pt))
                self.pts = []
        elif t == "circle":
            if not self.pts:
                self.pts = [pt]
            elif S_dist(self.pts[0], pt) > 1e-9:
                self._mutate()
                ents.append(S.circle(self.pts[0], S_dist(self.pts[0], pt)))
                self.pts = []
        elif t == "arc":
            self.pts.append(pt)
            if len(self.pts) == 3:
                try:
                    a = S.arc_from_3pts(*self.pts)
                except ValueError as e:
                    self.status(str(e))
                else:
                    self._mutate()
                    ents.append(a)
                self.pts = []
        elif t == "mirror2":
            self.pts.append(pt)
            if len(self.pts) == 2:
                self._mirror(self.pts[0], self.pts[1])
                self.pts = []
                self.tool = "select"
        self._after_edit(n0, rect=(t == "rect"))
        self._changed()

    def _after_edit(self, n_before, rect=False):
        """編輯後:替新圖元編號、移除失效拘束,並對新畫的圖元自動加上重合(矩形另加水平/垂直)拘束。"""
        S.assign_ids(self.entities)
        self.constraints = K.prune(self.entities, self.constraints)
        if self.tool in ("line", "rect", "circle", "arc") and len(self.entities) > n_before:
            new = self.entities[n_before:]
            self._auto_coincident(new)
            if rect and len(new) == 4:
                a, b, c, d = (e["id"] for e in new)
                for t, ref in (("horizontal", a), ("horizontal", c), ("vertical", b), ("vertical", d)):
                    self._add_raw({"t": t, "refs": [[ref]]})

    @staticmethod
    def _parts(e):
        return ["p1", "p2"] if e["t"] == "line" else (["c"] if e["t"] == "circle" else ["c", "s", "e"])

    @staticmethod
    def _xy(e, part):
        if e["t"] == "line":
            return e["p1"] if part == "p1" else e["p2"]
        if part == "c":
            return e["c"]
        return S.endpoints(e)[0 if part == "s" else 1]

    def _add_raw(self, c):
        c["id"] = max((k["id"] for k in self.constraints), default=0) + 1
        self.constraints.append(c)

    def _has_coincident(self, ra, rb):
        return any(c["t"] == "coincident" and {tuple(q) for q in c["refs"]} == {tuple(ra), tuple(rb)}
                   for c in self.constraints)

    def _auto_coincident(self, new):
        ids = {e["id"] for e in new}
        for e in new:
            for part in self._parts(e):
                a = self._xy(e, part)
                for o in self.entities:
                    if o["id"] == e["id"] or (o["id"] in ids and o["id"] < e["id"]):
                        continue
                    for op in self._parts(o):
                        b = self._xy(o, op)
                        if math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-7 and \
                                not self._has_coincident([e["id"], part], [o["id"], op]):
                            self._add_raw({"t": "coincident", "refs": [[e["id"], part], [o["id"], op]]})

    # --- 工具 / 編輯 ---
    def set_tool(self, tool):
        self.tool, self.pts, self.pick_buf = tool, [], []
        if tool in CONSTRAINT_TOOLS:
            label, _, seqs = CONSTRAINT_TOOLS[tool]
            what = "、".join({"P": "點", "L": "線", "C": "圓/弧", "E": "圖元"}[k] for k in seqs[0])
            self.status(f"{label}:" + CONS_HINT.format(what))
        else:
            self.status(f"{TOOLS.get(tool, tool)}:{HINTS.get(tool, '')}")
        self._redraw()

    def cancel_op(self):
        self.pts, self.pick_buf = [], []
        self._redraw()

    def typed(self, text):
        """數值輸入:x,y / @dx,dy / @長度<角度 / 單一數字(圓:半徑;線:沿游標方向的長度)。"""
        last = self.pts[-1] if self.pts else None
        direction = None
        if last is not None and self.hover_uv is not None:
            dx, dy = self.hover_uv[0] - last[0], self.hover_uv[1] - last[1]
            L = math.hypot(dx, dy)
            direction = (dx / L, dy / L) if L > 1e-12 else (1.0, 0.0)
        kind, val = S.parse_input(text, last, direction if self.tool != "circle" else None)
        if kind == "number":
            if self.tool == "circle" and self.pts and val > 0:
                self._mutate()
                n0 = len(self.entities)
                self.entities.append(S.circle(self.pts[0], val))
                self.pts = []
                self._after_edit(n0)
                self._changed()
                return
            raise ValueError("目前工具不接受單一數字,請輸入 x,y 或 @dx,dy")
        self._point(list(val), list(val), 0.0)

    def undo(self):
        if self._undo:
            self._redo.append(self._snap_state())
            self._restore(self._undo.pop())
            self.sel.clear()
            self.pts = []
            self._changed()

    def redo(self):
        if self._redo:
            self._undo.append(self._snap_state())
            self._restore(self._redo.pop())
            self.sel.clear()
            self._changed()

    def delete_selected(self):
        if self.sel:
            self._mutate()
            self.entities = [e for i, e in enumerate(self.entities) if i not in self.sel]
            self.sel.clear()
            self._after_edit(len(self.entities))
            self._changed()

    def _targets(self):
        return sorted(self.sel) if self.sel else list(range(len(self.entities)))

    def _mirror(self, p, q):
        idxs = self._targets()
        if not idxs:
            return
        try:
            new = S.mirror(self.entities, idxs, p, q)
        except ValueError as e:
            self.status(str(e))
            return
        self._mutate()
        self.entities = new
        self.sel.clear()

    def mirror_axis(self, axis):
        """axis: 'X' / 'Y' 為草圖座標軸;None 則進入兩點定軸模式。"""
        if axis is None:
            self.set_tool("mirror2")
            return
        self._mirror((0, 0), (1, 0) if axis == "X" else (0, 1))
        self._after_edit(len(self.entities))
        self._changed()

    def pattern(self, kind, n, dx=0.0, dy=0.0, angle=360.0, center=(0.0, 0.0)):
        idxs = self._targets()
        if not idxs or n < 2:
            return
        self._mutate()
        if kind == "linear":
            self.entities = S.linear_pattern(self.entities, idxs, n, dx, dy)
        else:
            self.entities = S.circular_pattern(self.entities, idxs, n, angle, center)
        self.sel.clear()
        self._after_edit(len(self.entities))
        self._changed()

    # --- 拘束 / 尺寸 ---
    def _ent(self, eid):
        return next(e for e in self.entities if e["id"] == eid)

    def _kind(self, ref):
        if len(ref) == 2:
            return "P"
        return "L" if self._ent(ref[0])["t"] == "line" else "C"

    @staticmethod
    def _fits(spec, kind):
        return spec == kind or spec == "E" and kind in ("L", "C")

    def _wanted(self, seqs):
        got = [self._kind(r) for r in self.pick_buf]
        return {sq[len(got)] for sq in seqs if len(sq) > len(got)
                and all(self._fits(a, b) for a, b in zip(sq, got))}

    def _pick_ref(self, raw, tol, kinds):
        if "P" in kinds:
            best, bd = None, tol
            for e in self.entities:
                for part in self._parts(e):
                    q = self._xy(e, part)
                    d = math.hypot(q[0] - raw[0], q[1] - raw[1])
                    if d <= bd:
                        best, bd = [e["id"], part], d
            if best:
                return best
        want = kinds - {"P"}
        if want:
            cands = [(i, e) for i, e in enumerate(self.entities) if any(
                self._fits(k, "L" if e["t"] == "line" else "C") for k in want)]
            idx = S.nearest_entity([e for _, e in cands], raw, tol)
            if idx is not None:
                return [cands[idx][1]["id"]]
        return None

    def _constraint_pick(self, raw, tol):
        label, ctype, seqs = CONSTRAINT_TOOLS[self.tool]
        ref = self._pick_ref(raw, tol, self._wanted(seqs))
        if ref is None:
            self.status(f"{label}:沒有點到可用的圖元(需要:" + "/".join(sorted(self._wanted(seqs))) + ")")
            return
        self.pick_buf.append(ref)
        kinds = tuple(self._kind(r) for r in self.pick_buf)
        if kinds in seqs:
            buf, self.pick_buf = self.pick_buf, []
            self._complete(ctype, buf)
        else:
            self.status(f"{label}:已選 {len(self.pick_buf)} 項,請繼續選取")
        self._redraw()

    def _complete(self, ctype, refs):
        c = {"t": ctype, "refs": refs}
        ents = self.entities
        if ctype == "size":
            e = self._ent(refs[0][0])
            c["t"] = "length" if e["t"] == "line" else ("diameter" if e["t"] == "circle" else "radius")
        if ctype == "tangent" and all(self._kind(r) == "C" for r in refs):
            a, b = self._ent(refs[0][0]), self._ent(refs[1][0])
            d = math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1])
            c["mode"] = "ext" if abs(d - (a["r"] + b["r"])) <= abs(d - abs(a["r"] - b["r"])) else "int"
        if ctype == "fix":
            if len(refs[0]) == 2:
                c["vals"] = list(self._xy(self._ent(refs[0][0]), refs[0][1]))
            else:
                c["vals"] = K.get_vars(self._ent(refs[0][0]))
        if ctype in ("horizontal", "vertical") and len(refs) == 2 and refs[0] == refs[1]:
            self.status("兩次選到同一個點")
            return
        if c["t"] in K.DIMENSIONAL:
            if ctype in ("distance", "hdist", "vdist") and refs[0] == refs[1]:
                self.status("兩次選到同一個點")
                return
            cur = K.measure(ents, c)
            title = K.NAMES[c["t"]]
            val = self.ask_value(title, round(cur, 6))
            if val is None:
                self.status("已取消標註")
                return
            if c["t"] in ("hdist", "vdist"):
                a, b = (K.point_coords(ents, r) for r in refs)
                i = 0 if c["t"] == "hdist" else 1
                c["sign"] = -1 if b[i] - a[i] < 0 else 1
            if c["t"] != "angle" and val <= 0:
                self.status("尺寸必須大於 0")
                return
            c["v"] = float(val)
        self.add_constraint(c)

    def add_constraint(self, c) -> bool:
        """加入拘束並求解;失敗(衝突/無解)則復原並回傳 False。"""
        d0 = K.dof(self.entities, self.constraints)
        self._mutate()
        self._add_raw(c)
        ok, out, dof, err = K.solve(self.entities, self.constraints)
        if not ok:
            self._restore(self._undo.pop())
            self.status(f"無法加入「{K.NAMES[c['t']]}」:與現有拘束衝突或無法求解")
            self._changed()
            return False
        self.entities = out
        note = "(多餘拘束:已可由其他拘束推得)" if dof == d0 and c["t"] not in K.DIMENSIONAL else ""
        self.status(f"已加入「{K.NAMES[c['t']]}」,自由度 {dof}" + note)
        self._changed()
        return True

    def edit_value(self, cid, value) -> bool:
        c = next(k for k in self.constraints if k["id"] == cid)
        old = c["v"]
        self._mutate()
        c["v"] = float(value)
        ok, out, dof, _ = K.solve(self.entities, self.constraints)
        if not ok:
            self._restore(self._undo.pop())
            self.status("新數值與其他拘束衝突,已還原")
            self._changed()
            return False
        self.entities = out
        self.status(f"尺寸已改為 {value:g}(原 {old:g}),自由度 {dof}")
        self._changed()
        return True

    def delete_constraint(self, cid):
        self._mutate()
        self.constraints = [k for k in self.constraints if k["id"] != cid]
        self._changed()

    def dof(self) -> int:
        return K.dof(self.entities, self.constraints)

    def describe(self, c) -> str:
        names = []
        for r in c["refs"]:
            e = self._ent(r[0])
            tag = {"line": "線", "circle": "圓", "arc": "弧"}[e["t"]] + str(e["id"])
            names.append(tag + (f".{r[1]}" if len(r) == 2 else ""))
        text = f"{K.NAMES[c['t']]} [{', '.join(names)}]"
        if c["t"] in K.DIMENSIONAL:
            text += f" = {c['v']:.4g}" + ("°" if c["t"] == "angle" else "")
        return text

    def _extent(self) -> float:
        pts = [p for e in self.entities for p in S.sample(e, 24)]
        if not pts:
            return 10.0
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 10.0)

    def _dim_shapes(self, c):
        """尺寸標註的圖形: (折線清單[uv], 文字, 文字位置 uv)。"""
        ents, off = self.entities, 0.07 * self._extent()
        t, r, v = c["t"], c["refs"], c["v"]
        P = lambda ref: K.point_coords(ents, ref)  # noqa: E731
        if t in ("length", "distance"):
            if t == "length":
                a, b = P([r[0][0], "p1"]), P([r[0][0], "p2"])
            else:
                a, b = P(r[0]), P(r[1])
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            n = (-(b[1] - a[1]) / L * off, (b[0] - a[0]) / L * off)
            a2, b2 = (a[0] + n[0], a[1] + n[1]), (b[0] + n[0], b[1] + n[1])
            return ([[a, (a2[0] + n[0] * .2, a2[1] + n[1] * .2)], [b, (b2[0] + n[0] * .2, b2[1] + n[1] * .2)], [a2, b2]],
                    f"{v:.4g}", ((a2[0] + b2[0]) / 2 + n[0] * .3, (a2[1] + b2[1]) / 2 + n[1] * .3))
        if t in ("hdist", "vdist"):
            a, b = P(r[0]), P(r[1])
            if t == "hdist":
                y = max(a[1], b[1]) + off
                return ([[a, (a[0], y + off * .2)], [b, (b[0], y + off * .2)], [(a[0], y), (b[0], y)]],
                        f"{v:.4g}", ((a[0] + b[0]) / 2, y + off * .3))
            x = max(a[0], b[0]) + off
            return ([[a, (x + off * .2, a[1])], [b, (x + off * .2, b[1])], [(x, a[1]), (x, b[1])]],
                    f"{v:.4g}", (x + off * .3, (a[1] + b[1]) / 2))
        if t in ("radius", "diameter"):
            e = self._ent(r[0][0])
            (cx, cy), R = e["c"], e["r"]
            u = (math.cos(math.radians(45)), math.sin(math.radians(45)))
            if t == "radius":
                q = (cx + R * u[0], cy + R * u[1])
                return ([[(cx, cy), q]], f"R{v:.4g}", (q[0] + off * .4 * u[0], q[1] + off * .4 * u[1]))
            q1, q2 = (cx - R * u[0], cy - R * u[1]), (cx + R * u[0], cy + R * u[1])
            return ([[q1, q2]], f"D{v:.4g}", (q2[0] + off * .4 * u[0], q2[1] + off * .4 * u[1]))
        if t == "angle":
            (a1, a2), (b1, b2) = [(self._xy(self._ent(q[0]), "p1"), self._xy(self._ent(q[0]), "p2")) for q in r]
            d1, d2 = (a2[0] - a1[0], a2[1] - a1[1]), (b2[0] - b1[0], b2[1] - b1[1])
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) < 1e-12:
                return [], "", (0, 0)
            s_ = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / den
            vx, vy = a1[0] + s_ * d1[0], a1[1] + s_ * d1[1]
            th1, th2 = math.atan2(d1[1], d1[0]), math.atan2(d2[1], d2[0])
            diff = math.atan2(math.sin(th2 - th1), math.cos(th2 - th1))
            R = off * 2.0
            arc_pts = [(vx + R * math.cos(th1 + diff * k / 24), vy + R * math.sin(th1 + diff * k / 24))
                       for k in range(25)]
            mid = th1 + diff / 2
            return [arc_pts], f"{v:.4g}°", (vx + R * 1.3 * math.cos(mid), vy + R * 1.3 * math.sin(mid))
        return [], "", (0, 0)

    def _marker_pos(self, c):
        off = 0.03 * self._extent()
        e = self._ent(c["refs"][0][0])
        if len(c["refs"][0]) == 2:
            q = self._xy(e, c["refs"][0][1])
            return (q[0] + off, q[1] + off)
        if e["t"] == "line":
            return ((e["p1"][0] + e["p2"][0]) / 2 + off, (e["p1"][1] + e["p2"][1]) / 2 + off)
        q = S.sample(e, 24)
        m = q[len(q) // 4]
        return (m[0] + off, m[1] + off)

    # --- 顯示 ---
    def _changed(self):
        self._redraw()
        if self.on_change:
            self.on_change()

    def view_normal(self):
        pl = self.scene.plotter
        pl.view_vector(tuple(self._vec(self.plane.zDir)), viewup=tuple(self._vec(self.plane.yDir)))
        pl.reset_camera()

    def start(self):
        self.scene.mode = "sketch"
        self.scene.clear_selection(notify=False)
        self.scene._draw_lock(render=False)        # 草圖模式下淡化鎖定平面
        self.view_normal()
        self.set_tool(self.tool)
        self._redraw()

    def stop(self):
        pl = self.scene.plotter
        for name in ACTORS:
            pl.remove_actor(name, render=False)
        self.scene.mode = "off"
        self.scene._draw_lock(render=False)
        pl.render()

    def _preview(self):
        h, t, p = self.hover_uv, self.tool, self.pts
        if h is None or not p:
            return []
        try:
            if t in ("line", "mirror2") or (t == "arc" and len(p) == 1):
                return [S.line(p[-1], h)]
            if t == "rect":
                return S.rectangle(p[0], h)
            if t == "circle":
                return [S.circle(p[0], S_dist(p[0], h))] if S_dist(p[0], h) > 1e-9 else []
            if t == "arc" and len(p) == 2:
                return [S.arc_from_3pts(p[0], p[1], h)]
        except ValueError:
            pass
        return []

    def _draw_constraints(self, pl):
            wp = self.wp
            pos_lbl, txt_lbl, dim_lines, mark_pos, mark_txt, coin = [], [], [], [], [], []
            for c in self.constraints:
                try:
                    if c["t"] in K.DIMENSIONAL:
                        lines, text, at = self._dim_shapes(c)
                        for ln in lines:
                            dim_lines.append(np.array([self.to3d(p) for p in ln]))
                        if text:
                            pos_lbl.append(self.to3d(at))
                            txt_lbl.append(text)
                    elif c["t"] == "coincident":
                        coin.append(self.to3d(self._xy(self._ent(c["refs"][0][0]), c["refs"][0][1])))
                    else:
                        mark_pos.append(self.to3d(self._marker_pos(c)))
                        mark_txt.append(SYMBOLS[c["t"]])
                except (StopIteration, KeyError):
                    continue
            if dim_lines:
                pl.add_mesh(lines_poly(dim_lines), color="#5fe05f", line_width=1.5, name="sk_dims", pickable=False)
            if pos_lbl:
                pl.add_point_labels(np.array(pos_lbl), txt_lbl, name="sk_dimlbl", font_size=14, text_color="#5fe05f",
                                    shape=None, show_points=False, always_visible=True, pickable=False)
            if mark_pos:
                pl.add_point_labels(np.array(mark_pos), mark_txt, name="sk_cons", font_size=12, text_color="#40c040",
                                    shape=None, show_points=False, always_visible=True, pickable=False)
            if coin:
                pl.add_mesh(pv.PolyData(np.array(coin)), color="#40c040", point_size=7,
                            render_points_as_spheres=True, name="sk_coin", pickable=False)
            hi = [e for e in self.entities if e["id"] in self.highlight]
            if hi:
                pl.add_mesh(lines_poly(S.polylines_global(hi, wp)), color="#00e5ff", line_width=6,
                            name="sk_hi", pickable=False)

    def _redraw(self):
        pl, wp = self.scene.plotter, self.wp
        for name in ACTORS:
            pl.remove_actor(name, render=False)
        normal = [e for i, e in enumerate(self.entities) if i not in self.sel]
        chosen = [e for i, e in enumerate(self.entities) if i in self.sel]
        for name, ents, color, width in (("sk_ent", normal, "#ff8c00", 3), ("sk_sel", chosen, "#ff4d4d", 5),
                                         ("sk_prev", self._preview(), "#7fe0ff", 2)):
            if ents:
                pl.add_mesh(lines_poly(S.polylines_global(ents, wp)), color=color, line_width=width,
                            name=name, pickable=False, render_lines_as_tubes=False)
        self._draw_constraints(pl)
        size = self.scene._plane_size() * 0.5
        ox = self._vec(self.plane.origin)
        for name, d, color in (("sk_axes", self._vec(self.plane.xDir), "#e05050"),):
            pl.add_mesh(lines_poly([np.array([ox, ox + d * size]),
                                    np.array([ox, ox + self._vec(self.plane.yDir) * size])]),
                        color="#5aa05a", line_width=1, name=name, pickable=False)
        if self.hover_uv is not None and self.snap_kind:
            pl.add_mesh(pv.PolyData(np.array([self.to3d(self.hover_uv)])), color="yellow", point_size=12,
                        render_points_as_spheres=True, name="sk_snap", pickable=False)
        pl.render()


def S_dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
