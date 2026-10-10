"""量測工具:在 3D 視窗點選頂點/邊/面,量測距離、邊長/半徑、面積、角度。"""
from dataclasses import dataclass

import cadquery as cq
import numpy as np
import pyvista as pv

from core import measure as M
from .picking import face_at, nearest_body
from .sketch_editor import lines_poly

TOOLS = {
    "point": ("點到點距離", {"vertex", "edge", "face"}, 2),
    "dist": ("圖元間最短距離", {"vertex", "edge", "face"}, 2),
    "edge": ("邊長 / 半徑", {"edge"}, 1),
    "face": ("面積 / 面資訊", {"face"}, 1),
    "angle": ("角度", {"edge", "face"}, 2),
}
HINTS = {
    "point": "依序點選兩個點(頂點、邊上、面上皆可;靠近頂點會自動吸附)",
    "dist": "依序點選兩個圖元(頂點/邊/面),量測兩者之間的最短距離",
    "edge": "點選一條邊,顯示長度;圓/圓弧另顯示半徑、直徑、圓心",
    "face": "點選一個面,顯示面積;平面顯示法向,圓柱/球顯示半徑",
    "angle": "依序點選兩個平面、兩條直線,或一條直線與一個平面",
}
NAMES = ("ms_lines", "ms_pts", "ms_lbl", "ms_hi_e")
COLOR = "#ffe04a"


@dataclass
class Pick:
    kind: str            # vertex / edge / face
    body: int
    sub: cq.Shape
    point: np.ndarray    # 點選位置(頂點/邊上最近點/面上點)
    index: int = -1


def _fmt(v: float) -> str:
    if abs(v) < 5e-4:
        v = 0.0                                  # 避免顯示 -0
    return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:.4g}"


class MeasureTool:
    def __init__(self, scene):
        self.scene = scene
        self.tool = "point"
        self.buf: list[Pick] = []
        self.items: list[dict] = []        # 已完成的量測標註
        self.on_result = None              # 回呼 on_result(text)
        self.status = lambda m: None

    # --- 外部介面 ---
    def set_tool(self, tool: str):
        self.tool, self.buf = tool, []
        self.status(f"量測:{TOOLS[tool][0]} — {HINTS[tool]}")
        self.redraw()

    def clear(self):
        self.buf, self.items = [], []
        self.redraw()

    def cancel(self):
        self.buf = []
        self.redraw()

    # --- 點選解析 ---
    def resolve(self, P) -> Pick | None:
        sc = self.scene
        body = nearest_body(sc._meshes, P)
        if body is None:
            return None
        shape = sc._doc.bodies[body].shape
        want = TOOLS[self.tool][1]
        tol = sc.world_per_pixel(P, 12)
        if "vertex" in want:
            best, bd = None, tol
            for v in shape.Vertices():
                d = float(np.linalg.norm(np.array(v.toTuple()) - P))
                if d <= bd:
                    best, bd = v, d
            if best is not None:
                return Pick("vertex", body, best, np.array(best.toTuple()))
        info = sc._edge_idx[body].nearest_info(P)
        if "edge" in want and info is not None and (info[1] <= tol or "face" not in want):
            return Pick("edge", body, shape.Edges()[info[0]], info[2], info[0])
        if "face" in want:
            fid = face_at(sc._meshes[body], P)
            if fid is not None:
                return Pick("face", body, shape.Faces()[fid], np.asarray(P, float), fid)
        return None

    def click(self, P):
        pick = self.resolve(np.asarray(P, float))
        if pick is None:
            self.status("量測:沒有點到可量測的圖元")
            return
        self.buf.append(pick)
        need = TOOLS[self.tool][2]
        if len(self.buf) < need:
            self.status(f"量測:已選第 {len(self.buf)} 個({self._kind_name(pick)}),請選第 {len(self.buf) + 1} 個")
            self.redraw()
            return
        picks, self.buf = self.buf, []
        try:
            item = getattr(self, f"_do_{self.tool}")(picks)
        except ValueError as e:
            self.status(f"量測失敗:{e}")
            self.redraw()
            return
        self.items.append(item)
        self.redraw()
        if self.on_result:
            self.on_result(item["text"])
        self.status("量測:" + item["text"].replace("\n", "  "))

    @staticmethod
    def _kind_name(p: Pick) -> str:
        return {"vertex": "頂點", "edge": "邊", "face": "面"}[p.kind]

    # --- 各量測 ---
    @staticmethod
    def _v(p) -> cq.Vector:
        return cq.Vector(*[float(c) for c in p])

    def _do_point(self, picks):
        a, b = picks
        r = M.point_distance(self._v(a.point), self._v(b.point))
        text = (f"點到點距離 = {_fmt(r['distance'])} mm\n  ΔX={_fmt(r['dx'])}  ΔY={_fmt(r['dy'])}  ΔZ={_fmt(r['dz'])}\n"
                f"  P1=({_fmt(a.point[0])}, {_fmt(a.point[1])}, {_fmt(a.point[2])})  "
                f"P2=({_fmt(b.point[0])}, {_fmt(b.point[1])}, {_fmt(b.point[2])})")
        return {"text": text, "lines": [np.array([a.point, b.point])], "points": [a.point, b.point],
                "label": ((a.point + b.point) / 2, _fmt(r["distance"])), "hi": []}

    def _do_dist(self, picks):
        a, b = picks
        d, p, q = M.min_distance(a.sub, b.sub)
        p, q = np.array(p.toTuple()), np.array(q.toTuple())
        text = (f"最短距離({self._kind_name(a)}-{self._kind_name(b)}) = {_fmt(d)} mm\n"
                f"  最近點 ({_fmt(p[0])}, {_fmt(p[1])}, {_fmt(p[2])}) → ({_fmt(q[0])}, {_fmt(q[1])}, {_fmt(q[2])})")
        return {"text": text, "lines": [np.array([p, q])] if d > 1e-9 else [], "points": [p, q],
                "label": ((p + q) / 2, _fmt(d)), "hi": [self._hi(a), self._hi(b)]}

    def _do_edge(self, picks):
        (a,) = picks
        i = M.edge_info(a.sub)
        lines = [f"邊 長度 = {_fmt(i['length'])} mm({M.EDGE_TYPES.get(i['type'], i['type'])})"]
        label = f"L {_fmt(i['length'])}"
        if "radius" in i:
            c = i["center"]
            lines.append(f"  半徑 R = {_fmt(i['radius'])}  直徑 D = {_fmt(i['diameter'])}  "
                         f"圓心 ({_fmt(c.x)}, {_fmt(c.y)}, {_fmt(c.z)})")
            label = f"R {_fmt(i['radius'])}  D {_fmt(i['diameter'])}"
        return {"text": "\n".join(lines), "lines": [], "points": [a.point], "label": (a.point, label),
                "hi": [self._hi(a)]}

    def _do_face(self, picks):
        (a,) = picks
        i = M.face_info(a.sub)
        lines = [f"面 面積 = {_fmt(i['area'])} mm²({M.FACE_TYPES.get(i['type'], i['type'])})"]
        label = f"A {_fmt(i['area'])}"
        if "normal" in i:
            n = i["normal"]
            lines.append(f"  法向 ({_fmt(n.x)}, {_fmt(n.y)}, {_fmt(n.z)})")
        if "radius" in i:
            lines.append(f"  半徑 R = {_fmt(i['radius'])}" + (f"  直徑 D = {_fmt(i['diameter'])}" if "diameter" in i else ""))
            label += f"  R {_fmt(i['radius'])}"
        c = i["center"]
        lines.append(f"  中心 ({_fmt(c.x)}, {_fmt(c.y)}, {_fmt(c.z)})")
        return {"text": "\n".join(lines), "lines": [], "points": [a.point], "label": (a.point, label),
                "hi": [self._hi(a)]}

    def _do_angle(self, picks):
        a, b = picks
        r = M.angle_between(a.sub, b.sub)
        extra = {"面-面": f"(兩面法向夾角 {_fmt(r.get('normals', 0))}°)", "線-線": f"(補角 {_fmt(r.get('supplement', 0))}°)",
                 "線-面": ""}[r["kind"]]
        text = f"角度({r['kind']}) = {_fmt(r['angle'])}° {extra}".rstrip()
        mid = (a.point + b.point) / 2
        return {"text": text, "lines": [], "points": [a.point, b.point], "label": (mid, f"{_fmt(r['angle'])}°"),
                "hi": [self._hi(a), self._hi(b)]}

    # --- 顯示 ---
    def _hi(self, p: Pick):
        """被量測圖元的強調顯示:邊用折線,面用該面的網格,頂點用點。"""
        sc = self.scene
        if p.kind == "edge":
            e = sc._edge_polys[p.body]
            ids = e.cell_data["edge_id"]
            return ("edge", e.extract_cells([i for i, k in enumerate(ids) if k == p.index]))
        if p.kind == "face":
            m = sc._meshes[p.body]
            ids = m.cell_data["face_id"]
            return ("face", m.extract_cells([i for i, k in enumerate(ids) if k == p.index]))
        return ("point", pv.PolyData(np.array([p.point])))

    def redraw(self):
        pl = self.scene.plotter
        for name in [n for n in pl.renderer.actors if str(n).startswith("ms_")]:
            pl.remove_actor(name, render=False)
        lines, pts, lbl_p, lbl_t, hi = [], [], [], [], []
        for it in self.items:
            lines += it["lines"]
            pts += list(it["points"])
            lbl_p.append(it["label"][0])
            lbl_t.append(it["label"][1])
            hi += it["hi"]
        for b in self.buf:                       # 已選第一個(尚未完成)的暫時標示
            pts.append(b.point)
            hi.append(self._hi(b))
        if lines:
            pl.add_mesh(lines_poly(lines), color=COLOR, line_width=3, name="ms_lines", pickable=False)
        if pts:
            pl.add_mesh(pv.PolyData(np.array(pts)), color=COLOR, point_size=10, render_points_as_spheres=True,
                        name="ms_pts", pickable=False)
        if lbl_p:
            pl.add_point_labels(np.array(lbl_p), lbl_t, name="ms_lbl", font_size=14, text_color="#ffe04a",
                                shape="rounded_rect", shape_color="#1c2530", shape_opacity=0.8,
                                show_points=False, always_visible=True, pickable=False)
        for k, (kind, mesh) in enumerate(hi):
            if mesh.n_points == 0:
                continue
            if kind == "face":
                pl.add_mesh(mesh, color="#ffb347", opacity=0.6, name=f"ms_hi_f{k}", pickable=False)
            elif kind == "edge":
                pl.add_mesh(mesh, color="#00e5ff", line_width=6, name=f"ms_hi_e{k}", pickable=False)
            else:
                pl.add_mesh(mesh, color="#00e5ff", point_size=12, render_points_as_spheres=True,
                            name=f"ms_hi_p{k}", pickable=False)
        pl.render()
