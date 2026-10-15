"""文件模型:以「特徵歷史」記錄建模步驟,可重算、復原/重做、存成專案檔。"""
import copy
import json
import os
from dataclasses import dataclass, field

import cadquery as cq

from .io_step import export_step, shapes_to_step_text
from . import features as F
from . import paths as PA
from . import measure as MS
from .expr import evaluate_all, resolve_params
from .ops import SURFACE_KINDS, CREATORS, MODIFIERS, LABELS, PLACEABLE, sketch_solid, sweep_solid, loft_solid

FORMAT_VERSION = 1

# STL 精細度預設: 名稱 -> (弦高誤差 mm, 角度誤差 rad)
STL_QUALITY = {"標準": (0.05, 0.2), "高(預設)": (0.01, 0.1), "超高": (0.002, 0.05)}


def stl_triangle_count(path: str) -> int:
    """讀取 STL(二進位或 ASCII)的三角形數量。"""
    import os
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(84)
        if len(head) == 84:
            n = int.from_bytes(head[80:84], "little")
            if 84 + 50 * n == size:
                return n
    with open(path, encoding="utf-8", errors="ignore") as f:
        return sum(1 for line in f if line.strip().startswith("facet normal"))


@dataclass
class Body:
    id: int
    name: str
    shape: cq.Shape


@dataclass
class Feature:
    kind: str
    params: dict = field(default_factory=dict)
    out_ids: list = field(default_factory=list)   # 建立類特徵產生的實體編號
    error: str | None = None                       # 最近一次重算的錯誤(不存檔)
    suppressed: bool = False                       # 已抑制:重算時略過
    name: str | None = None                        # 使用者自訂名稱

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)

    @property
    def title(self) -> str:
        """歷史清單顯示的名稱(自訂名稱優先)。"""
        return self.name or self.label

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "params": self.params, "out_ids": self.out_ids}
        if self.suppressed:
            d["suppressed"] = True
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        return cls(d["kind"], d.get("params", {}), list(d.get("out_ids", [])),
                   suppressed=bool(d.get("suppressed", False)), name=d.get("name"))


class Document:
    def __init__(self):
        self.features: list[Feature] = []
        self.states: list[dict] = []        # states[k] = 第 k 個特徵之後的 {id: (名稱, 形狀)}
        self.path: str | None = None
        self.dirty = False
        self._next_id = 1
        self._undo, self._redo = [], []
        self.rollback: int | None = None    # 回溯點:只計算到此特徵(含);None = 最新
        self.variables: dict = {}           # 變數與公式 {名稱: 數字或 "=算式"},依序求值
        self._values: dict = {}             # 目前求得的變數值

    # --- 目前實體 ---
    @property
    def bodies(self) -> list[Body]:
        last = self.states[-1] if self.states else {}
        return [Body(i, n, s) for i, (n, s) in last.items() if not isinstance(s, dict)]

    @property
    def planes(self) -> list[tuple[int, str, dict]]:
        """目前的參考面 [(編號, 名稱, 平面 dict)]。"""
        last = self.states[-1] if self.states else {}
        return [(i, n, s) for i, (n, s) in last.items() if isinstance(s, dict) and "origin" in s]

    @property
    def appearance(self) -> dict:
        """各實體的外觀 {實體編號: {"color": "#rrggbb"|None, "opacity": 0~1, "visible": bool}}(依特徵順序累積)。"""
        out = {}
        for k, f in enumerate(self.features):
            if f.kind != "appearance" or f.suppressed or (self.rollback is not None and k > self.rollback) or f.error:
                continue
            cur = out.setdefault(f.params["body"], {"color": None, "opacity": 1.0, "visible": True})
            for key in ("color", "opacity", "visible"):
                if key in f.params:
                    cur[key] = f.params[key]
        return out

    @property
    def materials(self) -> dict:
        """各實體指定的材料 {實體編號: {"material": 名稱, "density": g/cm³}}(後指定者覆蓋)。"""
        out = {}
        for k, f in enumerate(self.features):
            if f.kind != "material" or f.suppressed or (self.rollback is not None and k > self.rollback) or f.error:
                continue
            out[f.params["body"]] = {"material": f.params["material"], "density": f.params["density"]}
        return out

    @property
    def annotations(self) -> list[tuple[int, str, dict]]:
        """目前的半徑/直徑標註 [(編號, 名稱, 標註資料)]。"""
        last = self.states[-1] if self.states else {}
        return [(i, n, s["annotation"]) for i, (n, s) in last.items() if isinstance(s, dict) and "annotation" in s]

    @property
    def helices(self) -> list[tuple[int, str, dict]]:
        """目前的螺旋線路徑 [(編號, 名稱, {"helix", "wp"})]。"""
        last = self.states[-1] if self.states else {}
        return [(i, n, s) for i, (n, s) in last.items() if isinstance(s, dict) and "helix" in s]

    @property
    def sketches(self) -> list[tuple[int, str, dict]]:
        """目前的草圖 [(編號, 名稱, {"entities", "wp"})]。"""
        last = self.states[-1] if self.states else {}
        return [(i, n, s) for i, (n, s) in last.items() if isinstance(s, dict) and "entities" in s]

    def clear(self) -> None:
        self.__init__()

    # --- 重算 ---
    def _apply(self, feat: Feature, bodies: dict) -> None:
        p, k = resolve_params(feat.params, self._values), feat.kind
        pid = p.get("plane_id")                    # 綁定參考面時,以參考面目前位置為準
        if pid in bodies and isinstance(bodies[pid][1], dict) and "origin" in bodies[pid][1]:
            p = {**p, "wp": bodies[pid][1]}
        if k == "refplane":
            if not p.get("wp"):
                raise ValueError("缺少基準平面")
            if not feat.out_ids:
                feat.out_ids = [self._alloc()]
            name = p.get("name") or f"參考面{feat.out_ids[0]}"
            bodies[feat.out_ids[0]] = (name, F.offset_plane(
                p["wp"], p["offset"], p.get("rx", 0), p.get("ry", 0)))
        elif k == "appearance":
            if p["body"] not in bodies:
                raise KeyError(p["body"])               # 實體不存在 -> 標示錯誤
            op = p.get("opacity", 1.0)
            if not 0.05 <= op <= 1.0:
                raise ValueError("透明度需介於 5% 與 100%")
        elif k == "material":
            if p["body"] not in bodies:
                raise KeyError(p["body"])
            from .materials import density_of
            p["density"] = density_of(p["material"], p.get("density", 1.0))     # 內建材料以密度表為準;自訂需大於 0
            feat.params["density"] = p["density"]
        elif k == "annotation":
            name, shape = bodies[p["body"]]              # 實體不存在會丟 KeyError -> 標記失敗
            geo = MS.circular_geometry(shape, p["kind"], p["index"], p["at"])
            if not feat.out_ids:
                feat.out_ids = [self._alloc()]
            bodies[feat.out_ids[0]] = (f"{p['mode']}標註{feat.out_ids[0]}",
                                       {"annotation": {**geo, "mode": p["mode"], "body": p["body"]}})
        elif k == "helix":
            if not p.get("wp"):
                raise ValueError("螺旋線缺少工作平面")
            if not feat.out_ids:
                feat.out_ids = [self._alloc()]
            h = {key: p[key] for key in ("pitch", "height", "radius", "taper", "left") if key in p}
            PA.helix_wire(h, p["wp"])                    # 先驗證參數
            bodies[feat.out_ids[0]] = (p.get("name") or f"螺旋線{feat.out_ids[0]}", {"helix": h, "wp": p["wp"]})
        elif k == "sketch":
            if not p.get("wp"):
                raise ValueError("草圖缺少工作平面")
            if not feat.out_ids:
                feat.out_ids = [self._alloc()]
            name = p.get("name") or f"草圖{feat.out_ids[0]}"
            bodies[feat.out_ids[0]] = (name, {"entities": p["entities"], "wp": p["wp"],
                                              "constraints": p.get("constraints", [])})
        elif k in ("sketch_extrude", "sketch_revolve", "sketch_sweep", "sketch_loft"):
            def sk_by_id(i, allow_helix=False):
                sk = bodies.get(i, (None, None))[1]
                if not (isinstance(sk, dict) and ("entities" in sk or (allow_helix and "helix" in sk))):
                    raise ValueError("找不到草圖/路徑")
                return sk
            if k == "sketch_sweep":
                shape = sweep_solid(p, sk_by_id(p["profile"]), sk_by_id(p["path"], True))
            elif k == "sketch_loft":
                shape = loft_solid(p, [sk_by_id(i) for i in p["profiles"]])
            else:
                shape = sketch_solid(k, p, sk_by_id(p["sketch"]))
            op = p.get("op", "新實體")
            if op == "新實體":
                if not feat.out_ids:
                    feat.out_ids = [self._alloc()]
                bodies[feat.out_ids[0]] = (f"{feat.label}{feat.out_ids[0]}", shape)
            else:
                tname, target = bodies[p["target"]]
                res = F.boolean("聯集" if op == "聯集" else "差集", target, shape)
                if op == "切除" and abs(res.Volume() - target.Volume()) < 1e-9:
                    raise ValueError("切除範圍與目標實體沒有重疊")
                bodies[p["target"]] = (tname, res)
        elif k in CREATORS:
            shapes = CREATORS[k](p)
            if p.get("wp") and k in PLACEABLE:
                shapes = [F.to_plane(x, p["wp"], p.get("flip", False), PLACEABLE[k]) for x in shapes]
            if not feat.out_ids:
                feat.out_ids = [self._alloc() for _ in shapes]
            names = p.get("names") or [f"{feat.label}{i}" for i in feat.out_ids]
            for i, shape, name in zip(feat.out_ids, shapes, names):
                bodies[i] = (name, shape)
        elif k == "mirror":
            wp = p.get("wp") if p.get("plane") == "鎖定平面" else F.WORLD_PLANES.get(p.get("plane", ""))
            if wp is None:
                raise ValueError("鏡射平面未指定(請選 XY/XZ/YZ,或先鎖定平面)")
            name, shape = bodies[p["body"]]
            m = F.mirror_shape(shape, wp)
            if p["op"] == "另建新實體":
                if not feat.out_ids:
                    feat.out_ids = [self._alloc()]
                bodies[feat.out_ids[0]] = (f"{name}(鏡射)", m)
            else:
                bodies[p["body"]] = (name, shape.fuse(m).clean())
        elif k in SURFACE_KINDS:
            self._apply_surface(feat, k, p, bodies)
        elif k == "mate":
            from .assembly import mate_shape
            if p["fixed"] == p["moving"]:
                raise ValueError("配合的兩個實體不可相同")
            _, fx = bodies[p["fixed"]]
            name, mv = bodies[p["moving"]]
            bodies[p["moving"]] = (name, mate_shape(fx, p["face_a"], mv, p["face_b"], p["type"],
                                                    p.get("offset", 0.0), p.get("flip", False)))
        elif k == "rib":
            name, shape = bodies[p["body"]]
            sk = bodies.get(p["sketch"], (None, None))[1]
            if not isinstance(sk, dict) or "entities" not in sk:
                raise ValueError("找不到草圖")
            from . import sketch2d as SK
            wire = SK.path_wire(sk["entities"], sk["wp"])
            bodies[p["body"]] = (name, F.rib_solid(shape, wire, sk["wp"]["normal"], p["thickness"],
                                                    p.get("symmetric", True), p.get("flip", False)))
        elif k in MODIFIERS:
            name, shape = bodies[p["body"]]
            bodies[p["body"]] = (name, MODIFIERS[k](p, shape))
        elif k == "boolean":
            from .features import boolean
            a, b = p["target"], p["tool"]
            name, shape = bodies[a]
            bodies[a] = (name, boolean(p["op"], shape, bodies[b][1]))
            if not p.get("keep"):
                del bodies[b]
        elif k == "delete":
            del bodies[p["body"]]
        else:
            raise ValueError(f"未知特徵: {k}")

    def _new_body(self, feat: Feature, bodies: dict, name: str, shape) -> None:
        if not feat.out_ids:
            feat.out_ids = [self._alloc()]
        bodies[feat.out_ids[0]] = (f"{name}{feat.out_ids[0]}", shape)

    def _apply_surface(self, feat: Feature, k: str, p: dict, bodies: dict) -> None:
        from . import surface as SF
        if k == "surface_extrude":
            sk = bodies.get(p["sketch"], (None, None))[1]
            if not (isinstance(sk, dict) and "entities" in sk):
                raise ValueError("找不到草圖")
            depth = -p["depth"] if p.get("flip") else p["depth"]
            self._new_body(feat, bodies, "曲面", SF.extrude_surface(sk["entities"], sk["wp"], depth, p.get("sym", False)))
        elif k == "surface_offset":
            _, shape = bodies[p["body"]]
            res = SF.offset_faces(shape, set(p.get("faces") or []), p["distance"])
            self._new_body(feat, bodies, "偏移面", res)
        elif k == "surface_trim":
            name, shape = bodies[p["body"]]
            if not SF.is_surface(shape):
                raise ValueError("修剪只能用在曲面")
            tool = int(p.get("tool") or 0)
            if tool and (tool not in bodies or isinstance(bodies[tool][1], dict)):
                raise ValueError("找不到工具實體")
            if tool:
                res = SF.trim_by_tool(shape, bodies[tool][1], p.get("keep", "正側"))
            else:
                wp = p.get("wp") if p.get("plane") == "鎖定平面" else F.WORLD_PLANES.get(p.get("plane", ""))
                if wp is None:
                    raise ValueError("修剪平面未指定(選 XY/XZ/YZ、先鎖定平面,或指定工具實體)")
                if p.get("offset"):
                    wp = F.offset_plane(wp, p["offset"])
                res = SF.trim_by_plane(shape, wp, p.get("keep", "正側") in ("正側", "外側"))
            bodies[p["body"]] = (name, res)
        elif k == "surface_knit":
            raw = p["bodies"]
            ids = [int(i) for i in (raw.replace(",", " ").replace(";", " ").split() if isinstance(raw, str) else raw)]
            if len(ids) < 1:
                raise ValueError("請指定要縫合的實體編號")
            for i in ids:
                if i not in bodies or isinstance(bodies[i][1], dict):
                    raise KeyError(i)
            res = SF.knit([bodies[i][1] for i in ids], p.get("tol", 1e-3))
            if p.get("keep"):
                self._new_body(feat, bodies, "縫合", res)
            else:
                name = bodies[ids[0]][0]
                for i in ids[1:]:
                    del bodies[i]
                bodies[ids[0]] = (name, res)
        elif k == "thicken":
            name, shape = bodies[p["body"]]
            bodies[p["body"]] = (name, SF.thicken(shape, p["thickness"], p.get("mode", "單側")))

    def _alloc(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    def recompute(self, start: int = 0) -> None:
        """從第 start 個特徵起重算;失敗的特徵會被標記並略過。"""
        del self.states[start:]
        try:
            self._values = evaluate_all(self.variables)
        except ValueError:
            self._values = {}
        for k, feat in enumerate(self.features[start:], start):
            base = dict(self.states[-1]) if self.states else {}
            work = dict(base)
            if feat.suppressed or (self.rollback is not None and k > self.rollback):
                feat.error = None                      # 被抑制或在回溯點之後:不計算
                self.states.append(work)
                continue
            try:
                self._apply(feat, work)
                feat.error = None
            except KeyError as e:
                feat.error = f"找不到被參照的項目(編號 {e.args[0] if e.args else '?'}):可能已被刪除、抑制,或排在此特徵之後"
                work = base
            except Exception as e:  # noqa: BLE001
                feat.error = str(e) or type(e).__name__
                work = base
            self.states.append(work)

    # --- 復原 / 重做 ---
    def _snapshot(self):
        return copy.deepcopy(self.features), list(self.states), self.rollback, dict(self.variables)

    def _push_undo(self):
        self._undo.append(self._snapshot())
        self._redo.clear()
        self.dirty = True

    def _restore(self, snap):
        self.features, self.states, self.rollback = copy.deepcopy(snap[0]), list(snap[1]), snap[2]
        self.variables = dict(snap[3])
        try:
            self._values = evaluate_all(self.variables)
        except ValueError:
            self._values = {}
        self.dirty = True

    def can_undo(self): return bool(self._undo)
    def can_redo(self): return bool(self._redo)

    def undo(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())

    def _commit(self, start: int, check: Feature | None):
        """重算並檢查指定特徵;出錯則還原並回傳錯誤訊息。"""
        self.recompute(start)
        if check is not None and check.error:
            err = check.error
            self.undo()
            self._redo.pop()
            return err
        return None

    # --- 編輯操作(回傳錯誤訊息或 None) ---
    def add_feature(self, kind: str, params: dict) -> str | None:
        self._push_undo()
        feat = Feature(kind, params)
        idx = len(self.features) if self.rollback is None else self.rollback + 1
        self.features.insert(idx, feat)                # 回溯中:插入在回溯點之後
        if self.rollback is not None:
            self.rollback = idx
        return self._commit(idx, feat)

    def edit_feature(self, index: int, params: dict) -> str | None:
        self._push_undo()
        feat = self.features[index]
        feat.params.update(params)
        return self._commit(index, feat)

    def delete_feature(self, index: int) -> None:
        self._push_undo()
        del self.features[index]
        if self.rollback is not None and index <= self.rollback:
            self.rollback = self.rollback - 1 if self.rollback > 0 else None
        self.recompute(index)

    def set_variables(self, variables: dict) -> str | None:
        """設定變數與公式並全部重算;算式無效則不改變並回傳錯誤訊息。"""
        try:
            evaluate_all(variables)
        except ValueError as e:
            return str(e)
        self._push_undo()
        self.variables = dict(variables)
        self.recompute(0)
        return None

    def set_suppressed(self, index: int, on: bool) -> None:
        """抑制 / 取消抑制特徵(抑制後重算時略過,依賴它的特徵會標示錯誤)。"""
        self._push_undo()
        self.features[index].suppressed = on
        self.recompute(index)

    def rename_feature(self, index: int, name: str) -> None:
        self._push_undo()
        self.features[index].name = name.strip() or None

    def move_feature(self, index: int, delta: int) -> bool:
        """把特徵上移(-1)/下移(+1)並重算;超出範圍回傳 False。"""
        j = index + delta
        if not 0 <= j < len(self.features):
            return False
        self._push_undo()
        self.features[index], self.features[j] = self.features[j], self.features[index]
        self.recompute(min(index, j))
        return True

    def set_rollback(self, index: int | None) -> None:
        """回溯到指定特徵之後的狀態(None 回到最新)。不納入復原堆疊。"""
        last = len(self.features) - 1
        if index is not None and index >= last:
            index = None
        old = self.rollback
        self.rollback = index
        a = last if old is None else old
        b = last if index is None else index
        self.recompute(min(a, b) + 1 if self.features else 0)

    # --- 檔案 ---
    def import_step(self, path: str) -> str | None:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = f.read()
        import os
        return self.add_feature("step", {"data": data, "source": os.path.basename(path)})

    def export_step(self, path: str) -> None:
        export_step([b.shape for b in self.bodies], path)

    def export_stl(self, path: str, tolerance: float = 0.01, angular: float = 0.1, ascii: bool = False) -> int:
        """匯出所有實體為 STL。tolerance 為弦高誤差(mm,絕對值),angular 為角度誤差(弧度)。
        回傳三角形數量。"""
        shapes = [b.shape for b in self.bodies]
        if not shapes:
            raise ValueError("沒有可匯出的實體")
        comp = cq.Compound.makeCompound(shapes)
        if not comp.exportStl(path, tolerance, angular, ascii, relative=False):
            raise ValueError("STL 匯出失敗")
        return stl_triangle_count(path)

    def to_data(self) -> dict:
        return {"app": "3D Viewer", "version": FORMAT_VERSION,
                "features": [f.to_dict() for f in self.features], "rollback": self.rollback,
                "variables": self.variables}

    def save_project(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_data(), f, ensure_ascii=False)
        self.path, self.dirty = path, False

    def write_backup(self, path: str, source: str | None = None) -> None:
        """寫入自動儲存備份:不改變 path / dirty。source 記錄原專案路徑。"""
        data = self.to_data()
        data["source"] = source
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def load_project(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.load_data(data)
        self.path = path

    def load_data(self, data: dict) -> None:
        if data.get("version", 0) > FORMAT_VERSION:
            raise ValueError("專案檔版本過新,請更新程式")
        self.clear()
        self.features = [Feature.from_dict(d) for d in data["features"]]
        self.rollback = data.get("rollback")
        self.variables = dict(data.get("variables", {}))
        ids = [i for f in self.features for i in f.out_ids]
        self._next_id = max(ids, default=0) + 1
        self.recompute(0)
