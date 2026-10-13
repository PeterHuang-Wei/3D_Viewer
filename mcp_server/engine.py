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
from core import sketch_solver as K
from core import interference as IFC
from core import drawing as DR
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
        self.gui = None                  # 視窗專屬功能的轉接器(即時模式由橋接提供)
        self.locked = None               # 鎖定的工作平面 (wp, 參考面編號或 None)

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
        """plane 可為 'XY'/'XZ'/'YZ'、參考面編號、'locked'(lock_plane 鎖定的平面),
        或 {"body": 實體編號, "face": 面索引}(平面的面)。"""
        if plane == "locked":
            if not self.locked:
                raise EngineError("尚未鎖定平面(先呼叫 lock_plane)")
            wp = self.locked[0]
        elif isinstance(plane, dict):
            try:
                wp = F.plane_from_face(self._body(plane["body"]).shape.Faces()[plane["face"]])
            except (KeyError, IndexError):
                raise EngineError("面參照需為 {body, face},且面索引存在") from None
            except ValueError as e:
                raise EngineError(str(e)) from None
        elif isinstance(plane, int):
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
            pid = self.locked[1] if on_plane == "locked" and self.locked else on_plane
            if isinstance(pid, int) and not isinstance(pid, bool):
                params["plane_id"] = pid
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

    @staticmethod
    def _expand(entities: list) -> list:
        ents = []
        for e in entities:
            t = e.get("t")
            if t == "rect":
                (x1, y1), (x2, y2) = e["p1"], e["p2"]
                pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                new = [SK.line(pts[i], pts[(i + 1) % 4]) for i in range(4)]
            elif t == "polygon":
                pts = e["pts"]
                new = [SK.line(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
            elif t == "line":
                new = [SK.line(e["p1"], e["p2"])]
            elif t == "circle":
                new = [SK.circle(e["c"], e["r"])]
            elif t == "arc":
                new = [SK.arc(e["c"], e["r"], e["a0"], e["a1"])]
            elif t == "ellipse":
                new = [SK.ellipse(e["c"], e["a"], e["b"], e.get("rot", 0.0))]
            elif t == "spline":
                new = [SK.spline(e["pts"])]
            else:
                raise EngineError(f"未知草圖圖元:{t}(可用 line/rect/polygon/circle/arc/ellipse/spline)")
            if e.get("construction"):
                for n in new:
                    n["construction"] = True
            ents += new
        return ents

    def op_create_sketch(self, plane, entities: list, name: str = "", offset: float = 0.0, constraints=None):
        ents = SK.assign_ids(self._expand(entities))
        return self._add("sketch", {"entities": ents, "wp": self._plane(plane, offset), "name": name,
                                    "constraints": constraints or []})

    # --- 草圖編輯 / 拘束 ---
    def _sk(self, sid):
        for k, f in enumerate(self.doc.features):
            if f.kind == "sketch" and sid in f.out_ids:
                return k, f
        raise EngineError(f"找不到草圖 {sid}")

    @staticmethod
    def _sk_view(ents, cons):
        rows = []
        for i, e in enumerate(ents):
            row = {"index": i, **{k: v for k, v in e.items()}}
            rows.append(row)
        return {"entities": rows, "constraints": cons}

    def op_sketch_get(self, sketch: int):
        k, f = self._sk(sketch)
        ents = SK.assign_ids(list(f.params["entities"]))
        cons = f.params.get("constraints", [])
        return {"ok": True, **self._sk_view(ents, cons), "dof": K.dof(ents, cons) if cons else None,
                "constraint_types": K.NAMES}

    def _sk_save(self, k, f, ents, cons, extra=None):
        ids = {e["id"] for e in ents if "id" in e}
        cons = [c for c in cons if all(r[0] in ids for r in c["refs"])]
        err = self.doc.edit_feature(k, {"entities": ents, "constraints": cons})
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "entity_count": len(ents), "constraint_count": len(cons), **(extra or {}), **self._summary()}

    def op_sketch_edit(self, sketch: int, action: str, indices: list[int] | None = None, **kw):
        """action: add / delete / trim / fillet / chamfer / offset / mirror / linear_pattern / circular_pattern /
        project / construction。indices 為圖元索引(見 sketch_get)。"""
        k, f = self._sk(sketch)
        import copy
        ents = SK.assign_ids(copy.deepcopy(f.params["entities"]))
        cons = copy.deepcopy(f.params.get("constraints", []))
        idx = list(indices or [])
        n = len(ents)
        for i in idx + [kw.get(x) for x in ("index", "i", "j") if kw.get(x) is not None]:
            if not 0 <= i < n:
                raise EngineError(f"圖元索引 {i} 超出範圍(共 {n} 個)")
        try:
            if action == "add":
                ents = ents + self._expand(kw["entities"])
            elif action == "delete":
                ents = [e for i, e in enumerate(ents) if i not in set(idx)]
            elif action == "trim":
                ents = SK.trim(ents, kw["index"], kw["click"])
            elif action == "fillet":
                ents = SK.fillet_corner(ents, kw["i"], kw["j"], kw["r"])
            elif action == "chamfer":
                ents = SK.chamfer_corner(ents, kw["i"], kw["j"], kw["d1"], kw.get("d2"))
            elif action == "offset":
                ents = ents + SK.offset_loop(ents, kw["index"], kw["distance"])
            elif action == "mirror":
                ents = SK.mirror(ents, idx, kw["p"], kw["q"], kw.get("keep_original", True))
            elif action == "linear_pattern":
                ents = SK.linear_pattern(ents, idx, kw["n"], kw["dx"], kw["dy"])
            elif action == "circular_pattern":
                ents = SK.circular_pattern(ents, idx, kw["n"], kw.get("angle", 360.0), kw.get("center", [0, 0]))
            elif action == "project":
                ents = ents + SK.project_shape_edges(self._body(kw["body"]).shape, f.params["wp"],
                                                     kw.get("construction", True))
            elif action == "construction":
                for i in idx:
                    ents[i]["construction"] = bool(kw.get("on", True))
            else:
                raise EngineError(f"未知動作:{action}")
        except KeyError as e:
            raise EngineError(f"缺少參數:{e}") from None
        except ValueError as e:
            raise EngineError(str(e)) from None
        seen, fixed = set(), []
        for e in ents:                                           # 複製出的圖元可能帶重複編號
            if e.get("id") in seen:
                e = {kk: v for kk, v in e.items() if kk != "id"}
            seen.add(e.get("id"))
            fixed.append(e)
        return self._sk_save(k, f, SK.assign_ids(fixed), cons)

    def op_sketch_constrain(self, sketch: int, add: list[dict] | None = None, remove: list[int] | None = None,
                            set_values: dict | None = None):
        """add: 拘束清單 {"t":類型,"refs":[[圖元id,部位],...],"v":數值};remove: 拘束 id;set_values: {拘束id: 新數值}。
        refs 的圖元用 id(見 sketch_get),部位 p1/p2/c/s/e;整個圖元用 [id]。回傳自由度,衝突則整體還原。"""
        import copy
        k, f = self._sk(sketch)
        ents = SK.assign_ids(copy.deepcopy(f.params["entities"]))
        cons = copy.deepcopy(f.params.get("constraints", []))
        cons = [c for c in cons if c["id"] not in set(remove or [])]
        for cid, v in (set_values or {}).items():
            c = next((c for c in cons if c["id"] == int(cid)), None)
            if c is None:
                raise EngineError(f"找不到拘束 {cid}")
            c["v"] = float(v)
        nxt = max((c["id"] for c in cons), default=0) + 1
        ids = {e["id"] for e in ents}
        for c in add or []:
            if c.get("t") not in K.NAMES:
                raise EngineError(f"未知拘束類型:{c.get('t')}(可用 {', '.join(K.NAMES)})")
            if not c.get("refs") or any(r[0] not in ids for r in c["refs"]):
                raise EngineError(f"拘束參照的圖元 id 不存在:{c.get('refs')}")
            c = {**c, "id": nxt}
            nxt += 1
            if c["t"] in K.DIMENSIONAL:
                if "v" not in c:
                    raise EngineError("尺寸拘束需要 v 數值")
                if c["t"] in ("hdist", "vdist") and "sign" not in c:
                    a, b = (K.point_coords(ents, r) for r in c["refs"])
                    c["sign"] = -1 if b[0 if c["t"] == "hdist" else 1] - a[0 if c["t"] == "hdist" else 1] < 0 else 1
            cons.append(c)
        ok, out, dof, err = K.solve(ents, cons)
        if not ok:
            raise EngineError(f"拘束衝突或無法求解(殘差 {err:.3g}),未做任何改變")
        res = self._sk_save(k, f, out, cons, {"dof": dof, "constraint_ids": [c["id"] for c in cons]})
        return res

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

    # --- 檢視 / 視窗專屬 ---
    def _need_gui(self):
        if self.gui is None:
            raise EngineError("此功能需要 3D Viewer 視窗(即時模式):請啟用「說明 → 啟用 MCP 橋接」")
        return self.gui

    def op_lock_plane(self, plane=None):
        """鎖定工作平面(等同 F3),之後 add_feature/create_sketch 可用 on_plane/plane='locked'。
        plane 同 on_plane 格式(XY/XZ/YZ、參考面編號、{body,face});不給則解除鎖定。"""
        if plane is None:
            self.locked = None
            if self.gui:
                self.gui.lock_plane(None, None)
            return {"ok": True, "locked": None}
        wp = self._plane(plane)
        pid = plane if isinstance(plane, int) and not isinstance(plane, bool) else None
        self.locked = (wp, pid)
        if self.gui:
            self.gui.lock_plane(wp, pid)
        return {"ok": True, "locked": wp}

    def op_set_section(self, plane=None, offset: float = 0.0, flip: bool = False):
        """截面視圖(只影響畫面):切掉平面法向正側。plane 同 on_plane 格式(含 'locked');不給則關閉。"""
        gui = self._need_gui()
        if plane is None:
            gui.set_section(None, None)
            return {"ok": True, "section": None}
        wp = self._plane(plane)
        n = np.array(wp["normal"], float) * (-1 if flip else 1)
        o = np.array(wp["origin"], float) + n * offset
        gui.set_section(o, n)
        return {"ok": True, "origin": [_r(x) for x in o], "normal": [_r(x) for x in n]}

    def op_set_quality(self, name: str):
        from viewer.quality import QUALITY
        if name not in QUALITY:
            raise EngineError(f"name 需為 {list(QUALITY)}")
        self._need_gui().set_quality(name)
        return {"ok": True, "quality": name}

    def op_set_view(self, name: str):
        self._need_gui().set_view(name)
        return {"ok": True, "view": name}

    # --- 標註 / 外觀 / 材料 ---
    def op_add_dimension_annotation(self, body: int, kind: str, index: int, mode: str = "半徑"):
        """在圓/圓弧邊(kind=edge)或圓柱/球面(kind=face)上加半徑或直徑標註(mode=半徑|直徑)。"""
        if kind not in ("edge", "face") or mode not in ("半徑", "直徑"):
            raise EngineError("kind 需為 edge/face,mode 需為 半徑/直徑")
        sh = self._body(body).shape
        items = sh.Edges() if kind == "edge" else sh.Faces()
        if not 0 <= index < len(items):
            raise EngineError(f"{kind} 索引無效(共 {len(items)} 個)")
        c = items[index].Center()
        return self._add("annotation", {"body": body, "kind": kind, "index": index,
                                        "at": [c.x, c.y, c.z], "mode": mode})

    def op_set_appearance(self, body: int, color: str | None = None, opacity: float | None = None,
                          visible: bool | None = None):
        """顏色(#rrggbb)、透明度(0.05~1)、顯示/隱藏。"""
        self._body(body)
        p = {"body": body}
        if color is not None:
            p["color"] = color
        if opacity is not None:
            p["opacity"] = opacity
        if visible is not None:
            p["visible"] = visible
        if len(p) == 1:
            raise EngineError("至少指定 color / opacity / visible 其中之一")
        return self._add("appearance", p)

    def op_set_material(self, body: int, material: str, density: float = 1.0):
        """指定材料(內建名稱見 list_materials;自訂材料名稱搭配 density g/cm³)。"""
        self._body(body)
        return self._add("material", {"body": body, "material": material, "density": density})

    def op_list_materials(self):
        return {"ok": True, "materials": MAT.MATERIALS}

    # --- 特徵歷史 ---
    def _fi(self, index):
        if not 0 <= index < len(self.doc.features):
            raise EngineError("特徵索引超出範圍")
        return index

    def op_suppress_feature(self, index: int, on: bool = True):
        self.doc.set_suppressed(self._fi(index), on)
        return {"ok": True, **self._summary()}

    def op_rename_feature(self, index: int, name: str):
        self.doc.rename_feature(self._fi(index), name)
        return {"ok": True}

    def op_move_feature(self, index: int, delta: int):
        if not self.doc.move_feature(self._fi(index), delta):
            raise EngineError("無法移動(超出範圍)")
        return {"ok": True, **self._summary()}

    def op_set_rollback(self, index: int | None = None):
        if index is not None:
            self._fi(index)
        self.doc.set_rollback(index)
        return {"ok": True, "rollback": self.doc.rollback, **self._summary()}

    def op_import_step(self, path: str):
        if not os.path.exists(path):
            raise EngineError(f"檔案不存在:{path}")
        err = self.doc.import_step(path)
        return {"ok": False, "error": err} if err else {"ok": True, **self._summary()}

    def op_set_display(self, unit: str | None = None, precision: int | None = None):
        if unit:
            numfmt.set_unit(unit)
        if precision is not None:
            numfmt.set_precision(precision)
        return {"ok": True, "unit": numfmt.UNIT, "precision": numfmt.PRECISION}

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

    def op_measure(self, kind: str, body: int | None = None, index: int | None = None,
                   body_b: int | None = None, index_b: int | None = None, contact: bool = True,
                   entity: str = "face"):
        """kind: edge{body,index} / face{body,index} / angle{entity:face|edge, body,index,body_b,index_b}/
        mass(整體質量屬性) / interference(實體間干涉)。"""
        j = lambda v: _vec(v) if hasattr(v, "x") else v  # noqa: E731
        if kind in ("edge", "face"):
            sh = self._body(body).shape
            items = sh.Edges() if kind == "edge" else sh.Faces()
            if index is None or not 0 <= index < len(items):
                raise EngineError(f"{kind} 索引無效(共 {len(items)} 個)")
            info = (MS.edge_info if kind == "edge" else MS.face_info)(items[index])
            return {"ok": True, **{k: (j(v) if not isinstance(v, (int, float, str, bool)) else (_r(v) if isinstance(v, float) else v))
                                   for k, v in info.items()}}
        if kind == "angle":
            a_sh, b_sh = self._body(body).shape, self._body(body_b).shape
            get = (lambda sh: sh.Faces()) if entity == "face" else (lambda sh: sh.Edges())
            try:
                r = MS.angle_between(get(a_sh)[index], get(b_sh)[index_b])
            except IndexError:
                raise EngineError("索引超出範圍") from None
            return {"ok": True, **{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()}}
        if kind == "mass":
            mats, items = self.doc.materials, []
            for b in self.doc.bodies:
                items.append((b.name, b.shape, mats.get(b.id, {"density": 7.85})["density"]))
            if not items:
                raise EngineError("沒有實體")
            r = MAT.assembly_props(items)
            return {"ok": True, "mass_g": _r(r["mass"]), "volume": _r(r["volume"]), "com": [_r(x) for x in r["com"]],
                    "inertia_g_mm2": [[_r(x) for x in row] for row in r["inertia"]],
                    "parts": [{"name": p["name"], "mass_g": _r(p["mass"]), "volume": _r(p["volume"])} for p in r["parts"]],
                    "note": "未指定材料的實體以 7.85 g/cm³(鋼)計算"}
        if kind == "interference":
            res = IFC.check([(b.id, b.name, b.shape) for b in self.doc.bodies], include_contact=contact)
            return {"ok": True, "results": [{"a": r["a"][0], "b": r["b"][0], "kind": r["kind"],
                                             "volume": _r(r["volume"]) if r["kind"] == "干涉" else 0.0,
                                             "center": _vec(r["center"])} for r in res]}
        raise EngineError("kind 需為 edge / face / angle / mass / interference")

    def op_export_drawing(self, path: str, paper: str = "A3", views: list[str] | None = None, scale: str = "自動",
                          third_angle: bool = True, hidden: bool = True, dims: bool = True, hole_pos: bool = True,
                          radii: bool = True, chain: bool = False, section_axis: str | None = None,
                          section_offset: float = 0.0, title: str = "", part: str = "", author: str = ""):
        """輸出工程圖(.pdf/.svg/.png/.dxf)。views 預設 前視/上視/右視/等角視;section_axis 為 XZ(前剖)/YZ(側剖)/XY(上剖) 啟用剖視。"""
        ap = self.doc.appearance
        shapes = [b.shape for b in self.doc.bodies if ap.get(b.id, {}).get("visible", True)]
        if not shapes:
            raise EngineError("沒有可繪製的實體")
        if paper not in DR.PAPERS:
            raise EngineError(f"紙張需為 {list(DR.PAPERS)}")
        name = os.path.splitext(os.path.basename(self.doc.path))[0] if self.doc.path else "未命名"
        if section_axis not in (None, "XZ", "YZ", "XY"):
            raise EngineError("section_axis 需為 XZ / YZ / XY")
        if not path.lower().endswith((".pdf", ".svg", ".png", ".dxf")):
            raise EngineError("副檔名需為 .pdf / .svg / .png / .dxf")
        sheet = DR.build_sheet(shapes, tuple(views or ("前視", "上視", "右視", "等角視")), paper, third_angle, scale,
                               hidden, dims, {"title": title or f"{name} 工程圖", "part": part or name,
                                              "author": author, "paper": paper},
                               section={"axis": section_axis, "offset": section_offset} if section_axis else None,
                               hole_pos=hole_pos, radii=radii, chain=chain)
        if path.lower().endswith(".dxf"):
            DR.export_dxf(sheet, path)
        else:
            self._qt_app()
            from ui.drawing_render import export_sheet
            export_sheet(sheet, path)
        return {"ok": True, "path": path, "scale": f"{sheet.scale[0]}:{sheet.scale[1]}"}

    @staticmethod
    def _qt_app():
        from PyQt5.QtWidgets import QApplication
        if QApplication.instance() is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            Engine._app = QApplication(["3dviewer-mcp"])

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
