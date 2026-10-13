"""與介面無關的操作引擎:在 core.model.Document 上執行 LLM 工具指令。
無頭模式直接持有 Document;即時模式由 App 內的橋接(ui/bridge.py)以同一引擎操作視窗的文件。
所有操作回傳可轉成 JSON 的 dict:成功 {"ok": True, ...},失敗 {"ok": False, "error": 訊息}。"""
import base64
import math
import os

import numpy as np

from core import features as F
from core import measure as MS
from core import materials as MAT
from core import numfmt
from core import sketch2d as SK
from core.model import Document
from ui.schemas import SCHEMAS


def _r(v, n=4):
    return round(float(v), n) + 0.0


def _vec(v):
    return [_r(v.x), _r(v.y), _r(v.z)]


class EngineError(Exception):
    pass


class Engine:
    def __init__(self, doc: Document | None = None, screenshotter=None):
        self.doc = doc if doc is not None else Document()
        self.screenshotter = screenshotter or self._offscreen_shot

    def dispatch(self, op: str, args: dict | None = None) -> dict:
        fn = getattr(self, "op_" + op, None)
        if fn is None:
            return {"ok": False, "error": f"未知操作:{op}"}
        try:
            return fn(**(args or {}))
        except EngineError as e:
            return {"ok": False, "error": str(e)}
        except TypeError as e:
            return {"ok": False, "error": f"參數錯誤:{e}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # --- 輔助 ---
    def _body(self, bid: int):
        b = next((b for b in self.doc.bodies if b.id == bid), None)
        if b is None:
            raise EngineError(f"找不到實體 {bid}(現有:{[b.id for b in self.doc.bodies]})")
        return b

    def _plane(self, plane, offset=0.0) -> dict:
        """plane 可為 'XY'/'XZ'/'YZ',或參考面編號。"""
        if isinstance(plane, int):
            p = next((p for p in self.doc.planes if p[0] == plane), None)
            if p is None:
                raise EngineError(f"找不到參考面 {plane}")
            wp = p[2]
        elif plane in F.WORLD_PLANES:
            wp = F.WORLD_PLANES[plane]
        else:
            raise EngineError("plane 需為 XY / XZ / YZ 或參考面編號")
        return F.offset_plane(wp, offset) if offset else dict(wp)

    def _summary(self) -> dict:
        return {"bodies": [{"id": b.id, "name": b.name} for b in self.doc.bodies]}

    def _add(self, kind, params, on_plane=None):
        before = {b.id for b in self.doc.bodies}
        before_all = {i for f in self.doc.features for i in f.out_ids}
        params = dict(params)
        if on_plane is not None:
            params["wp"] = self._plane(on_plane)
            if isinstance(on_plane, int):
                params["plane_id"] = on_plane
        err = self.doc.add_feature(kind, params)
        if err:
            return {"ok": False, "error": err}
        new = [i for f in self.doc.features for i in f.out_ids if i not in before_all]
        return {"ok": True, "feature_index": self._feature_index(kind), "new_ids": new,
                "new_bodies": [i for i in new if i not in before], **self._summary()}

    def _feature_index(self, kind):
        i = self.doc.rollback if self.doc.rollback is not None else len(self.doc.features) - 1
        return i

    # --- 專案 ---
    def op_get_state(self):
        d = self.doc
        bodies = []
        for b in d.bodies:
            p = MS.body_properties(b.shape)
            bodies.append({"id": b.id, "name": b.name, "volume": _r(p["volume"]), "area": _r(p["area"]),
                           "min": [_r(x) for x in p["min"]], "max": [_r(x) for x in p["max"]],
                           "material": d.materials.get(b.id, {}).get("material")})
        return {"ok": True, "path": d.path, "dirty": d.dirty, "bodies": bodies,
                "sketches": [{"id": i, "name": n, "entities": len(s["entities"]), "plane_normal": s["wp"]["normal"]}
                             for i, n, s in d.sketches],
                "planes": [{"id": i, "name": n} for i, n, _ in d.planes],
                "features": [{"index": k, "kind": f.kind, "label": f.title, "error": f.error,
                              "suppressed": f.suppressed, "out_ids": f.out_ids} for k, f in enumerate(d.features)],
                "variables": d.variables, "can_undo": d.can_undo(), "can_redo": d.can_redo(),
                "unit": "mm", "feature_error_count": sum(1 for f in d.features if f.error)}

    def op_feature_kinds(self):
        out = {}
        for k, (title, fields) in SCHEMAS.items():
            out[k] = {"title": title, "fields": [
                {"key": f[0], "label": f[1], "type": f[2],
                 ("options" if f[2] == "combo" else "default"): f[3]} for f in fields]}
        return {"ok": True, "kinds": out,
                "notes": "未列出的欄位(如 body、edges、faces、target、tool、sketch)請依特徵需要自行提供;"
                         "缺少的欄位會以預設值補上。"}

    def op_new_project(self):
        self.doc.clear()
        return {"ok": True}

    def op_open_project(self, path: str):
        self.doc.load_project(path)
        return {"ok": True, **self._summary(), "errors": [f.title for f in self.doc.features if f.error]}

    def op_save_project(self, path: str | None = None):
        path = path or self.doc.path
        if not path:
            raise EngineError("尚未指定存檔路徑")
        if not path.lower().endswith(".v3d"):
            path += ".v3d"
        self.doc.save_project(path)
        return {"ok": True, "path": path}

    def op_undo(self):
        if not self.doc.can_undo():
            raise EngineError("沒有可復原的操作")
        self.doc.undo()
        return {"ok": True, **self._summary()}

    def op_redo(self):
        if not self.doc.can_redo():
            raise EngineError("沒有可重做的操作")
        self.doc.redo()
        return {"ok": True, **self._summary()}

    def op_set_variables(self, variables: dict):
        err = self.doc.set_variables({str(k): v for k, v in variables.items()})
        return {"ok": False, "error": err} if err else {"ok": True, "variables": self.doc.variables}

    # --- 特徵 ---
    def op_add_feature(self, kind: str, params: dict | None = None, on_plane=None):
        from core.ops import LABELS
        if kind not in LABELS:
            raise EngineError(f"未知特徵:{kind}(可用:{', '.join(LABELS)})")
        merged = {f[0]: (f[3][0] if f[2] == "combo" else f[3]) for f in SCHEMAS.get(kind, ("", []))[1]}
        merged.update(params or {})
        return self._add(kind, merged, on_plane)

    def op_edit_feature(self, index: int, params: dict):
        if not 0 <= index < len(self.doc.features):
            raise EngineError("特徵索引超出範圍")
        err = self.doc.edit_feature(index, params)
        return {"ok": False, "error": err} if err else {"ok": True, **self._summary()}

    def op_delete_feature(self, index: int):
        if not 0 <= index < len(self.doc.features):
            raise EngineError("特徵索引超出範圍")
        self.doc.delete_feature(index)
        return {"ok": True, **self._summary()}

    def op_create_primitive(self, kind: str, params: dict | None = None, position=None, on_plane=None):
        if kind not in ("box", "cylinder", "sphere", "cone", "torus"):
            raise EngineError("kind 需為 box / cylinder / sphere / cone / torus")
        res = self.op_add_feature(kind, params, on_plane)
        if res["ok"] and position and any(abs(v) > 1e-12 for v in position) and res["new_bodies"]:
            mv = self._add("translate", {"body": res["new_bodies"][0], "x": position[0], "y": position[1],
                                         "z": position[2]})
            if not mv["ok"]:
                return mv
            res["new_bodies"] = res["new_bodies"]
        return res

    def op_create_sketch(self, plane, entities: list, name: str = "", offset: float = 0.0, constraints=None):
        ents = []
        for e in entities:
            t = e.get("t")
            if t == "rect":
                (x1, y1), (x2, y2) = e["p1"], e["p2"]
                pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                ents += [SK.line(pts[i], pts[(i + 1) % 4]) for i in range(4)]
            elif t == "polygon":
                pts = e["pts"]
                ents += [SK.line(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
            elif t == "line":
                ents.append(SK.line(e["p1"], e["p2"]))
            elif t == "circle":
                ents.append(SK.circle(e["c"], e["r"]))
            elif t == "arc":
                ents.append(SK.arc(e["c"], e["r"], e["a0"], e["a1"]))
            elif t == "ellipse":
                ents.append(SK.ellipse(e["c"], e["a"], e["b"], e.get("rot", 0.0)))
            elif t == "spline":
                ents.append(SK.spline(e["pts"]))
            else:
                raise EngineError(f"未知草圖圖元:{t}(可用 line/rect/polygon/circle/arc/ellipse/spline)")
        return self._add("sketch", {"entities": ents, "wp": self._plane(plane, offset), "name": name,
                                    "constraints": constraints or []})

    def op_create_ref_plane(self, base_plane, offset: float, name: str = "", rx: float = 0.0, ry: float = 0.0):
        return self._add("refplane", {"wp": self._plane(base_plane), "offset": offset, "name": name,
                                      "rx": rx, "ry": ry})

    # --- 查詢面 / 邊 ---
    def op_find_faces(self, body: int, normal=None, geom_type: str | None = None, tol_deg: float = 5.0,
                      extreme: str | None = None):
        """normal=[x,y,z] 篩選平面法向;geom_type 如 PLANE/CYLINDER;extreme='max_z' 等取中心座標極值。"""
        shape = self._body(body).shape
        n = np.array(normal, float) / np.linalg.norm(normal) if normal else None
        rows = []
        for i, f in enumerate(shape.Faces()):
            t = f.geomType()
            if geom_type and t != geom_type.upper():
                continue
            row = {"index": i, "type": t, "center": _vec(f.Center()), "area": _r(f.Area())}
            if t == "PLANE":
                fn = f.normalAt()
                row["normal"] = _vec(fn)
                if n is not None and math.degrees(math.acos(max(-1, min(1, float(np.dot(n, [fn.x, fn.y, fn.z])))))) > tol_deg:
                    continue
            elif n is not None:
                continue
            rows.append(row)
        return {"ok": True, "faces": self._extreme(rows, extreme)}

    def op_find_edges(self, body: int, geom_type: str | None = None, direction=None, tol_deg: float = 5.0,
                      extreme: str | None = None, min_length: float = 0.0):
        shape = self._body(body).shape
        d = np.array(direction, float) / np.linalg.norm(direction) if direction else None
        rows = []
        for i, e in enumerate(shape.Edges()):
            t = e.geomType()
            if geom_type and t != geom_type.upper():
                continue
            if e.Length() < min_length:
                continue
            row = {"index": i, "type": t, "length": _r(e.Length()), "center": _vec(e.Center())}
            if t == "LINE":
                a, b = e.startPoint(), e.endPoint()
                v = np.array([b.x - a.x, b.y - a.y, b.z - a.z])
                v = v / np.linalg.norm(v)
                row["direction"] = [_r(x) for x in v]
                if d is not None and math.degrees(math.acos(min(1.0, abs(float(np.dot(d, v)))))) > tol_deg:
                    continue
            elif d is not None:
                continue
            rows.append(row)
        return {"ok": True, "edges": self._extreme(rows, extreme)}

    @staticmethod
    def _extreme(rows, extreme):
        if not extreme or not rows:
            return rows
        which, axis = extreme.split("_")
        k = "xyz".index(axis)
        vals = [r["center"][k] for r in rows]
        t = max(vals) if which == "max" else min(vals)
        return [r for r in rows if abs(r["center"][k] - t) < 1e-6]

    # --- 量測 ---
    def op_body_info(self, body: int):
        b = self._body(body)
        p = MS.body_properties(b.shape)
        mat = self.doc.materials.get(body, {"material": "鋼", "density": 7.85})
        m = MAT.mass_props(b.shape, mat["density"])
        return {"ok": True, "id": b.id, "name": b.name, "volume": _r(p["volume"]), "area": _r(p["area"]),
                "center": _vec(p["center"]), "size": [_r(x) for x in p["size"]],
                "min": [_r(x) for x in p["min"]], "max": [_r(x) for x in p["max"]],
                "material": mat["material"], "density": mat["density"], "mass_g": _r(m["mass"])}

    def op_distance(self, body_a: int, body_b: int):
        d, pa, pb = MS.min_distance(self._body(body_a).shape, self._body(body_b).shape)
        return {"ok": True, "distance": _r(d), "point_a": _vec(pa), "point_b": _vec(pb)}

    # --- 輸出 ---
    def op_export_step(self, path: str):
        if not self.doc.bodies:
            raise EngineError("沒有可匯出的實體")
        self.doc.export_step(path)
        return {"ok": True, "path": path}

    def op_export_stl(self, path: str, tolerance: float = 0.01):
        n = self.doc.export_stl(path, tolerance)
        return {"ok": True, "path": path, "triangles": n}

    def op_screenshot(self, width: int = 900, height: int = 700, view: str = "等角視"):
        data = self.screenshotter(width, height, view)
        return {"ok": True, "png_base64": base64.b64encode(data).decode()}

    def _offscreen_shot(self, width, height, view):
        import tempfile
        import pyvista as pv
        from viewer.mesh import shape_to_mesh
        if not self.doc.bodies:
            raise EngineError("沒有實體可截圖")
        pl = pv.Plotter(off_screen=True, window_size=(width, height))
        ap = self.doc.appearance
        for b in self.doc.bodies:
            a = ap.get(b.id, {})
            if not a.get("visible", True):
                continue
            pl.add_mesh(shape_to_mesh(b.shape, 0.05, 0.2), color=a.get("color") or "#9db4d0", smooth_shading=False,
                        show_edges=False, opacity=a.get("opacity", 1.0))
        pl.add_axes()
        views = {"等角視": "iso", "前視": "xz", "上視": "xy", "右視": "yz"}
        pl.camera_position = views.get(view, "iso")
        pl.reset_camera()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.png")
            pl.screenshot(p)
            pl.close()
            with open(p, "rb") as f:
                return f.read()
