"""互動式草圖編輯器:在鎖定平面上以滑鼠(或數值輸入)畫線、矩形、圓、圓弧,並可修整、鏡射、陣列。"""
import copy
import math

import numpy as np
import pyvista as pv

from core import features as F
from core import sketch2d as S

TOOLS = {
    "select": "選取", "line": "線", "rect": "矩形", "circle": "圓", "arc": "圓弧(三點)",
    "trim": "修整", "delete": "刪除", "mirror2": "鏡射(兩點定軸)",
}
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
ACTORS = ("sk_ent", "sk_sel", "sk_prev", "sk_snap", "sk_axes")


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
    def __init__(self, scene, wp, entities=None, status=None):
        self.scene = scene
        self.wp = wp
        self.plane = F.plane_from_dict(wp)
        self.entities = copy.deepcopy(entities or [])
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

    def _mutate(self):
        self._undo.append(copy.deepcopy(self.entities))
        self._redo.clear()

    def _point(self, pt, raw, tol):
        t, ents = self.tool, self.entities
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
        self._changed()

    # --- 工具 / 編輯 ---
    def set_tool(self, tool):
        self.tool, self.pts = tool, []
        self.status(f"{TOOLS.get(tool, tool)}:{HINTS.get(tool, '')}")
        self._redraw()

    def cancel_op(self):
        self.pts = []
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
                self.entities.append(S.circle(self.pts[0], val))
                self.pts = []
                self._changed()
                return
            raise ValueError("目前工具不接受單一數字,請輸入 x,y 或 @dx,dy")
        self._point(list(val), list(val), 0.0)

    def undo(self):
        if self._undo:
            self._redo.append(copy.deepcopy(self.entities))
            self.entities = self._undo.pop()
            self.sel.clear()
            self.pts = []
            self._changed()

    def redo(self):
        if self._redo:
            self._undo.append(copy.deepcopy(self.entities))
            self.entities = self._redo.pop()
            self.sel.clear()
            self._changed()

    def delete_selected(self):
        if self.sel:
            self._mutate()
            self.entities = [e for i, e in enumerate(self.entities) if i not in self.sel]
            self.sel.clear()
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
        self._changed()

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
