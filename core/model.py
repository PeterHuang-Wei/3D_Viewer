"""文件模型:以「特徵歷史」記錄建模步驟,可重算、復原/重做、存成專案檔。"""
import copy
import json
from dataclasses import dataclass, field

import cadquery as cq

from .io_step import export_step, shapes_to_step_text
from .ops import CREATORS, MODIFIERS, LABELS

FORMAT_VERSION = 1


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

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "params": self.params, "out_ids": self.out_ids}

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        return cls(d["kind"], d.get("params", {}), list(d.get("out_ids", [])))


class Document:
    def __init__(self):
        self.features: list[Feature] = []
        self.states: list[dict] = []        # states[k] = 第 k 個特徵之後的 {id: (名稱, 形狀)}
        self.path: str | None = None
        self.dirty = False
        self._next_id = 1
        self._undo, self._redo = [], []

    # --- 目前實體 ---
    @property
    def bodies(self) -> list[Body]:
        last = self.states[-1] if self.states else {}
        return [Body(i, n, s) for i, (n, s) in last.items()]

    def clear(self) -> None:
        self.__init__()

    # --- 重算 ---
    def _apply(self, feat: Feature, bodies: dict) -> None:
        p, k = feat.params, feat.kind
        if k in CREATORS:
            shapes = CREATORS[k](p)
            if not feat.out_ids:
                feat.out_ids = [self._alloc() for _ in shapes]
            names = p.get("names") or [f"{feat.label}{i}" for i in feat.out_ids]
            for i, shape, name in zip(feat.out_ids, shapes, names):
                bodies[i] = (name, shape)
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

    def _alloc(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    def recompute(self, start: int = 0) -> None:
        """從第 start 個特徵起重算;失敗的特徵會被標記並略過。"""
        del self.states[start:]
        for feat in self.features[start:]:
            base = dict(self.states[-1]) if self.states else {}
            work = dict(base)
            try:
                self._apply(feat, work)
                feat.error = None
            except Exception as e:  # noqa: BLE001
                feat.error = str(e) or type(e).__name__
                work = base
            self.states.append(work)

    # --- 復原 / 重做 ---
    def _snapshot(self):
        return copy.deepcopy(self.features), list(self.states)

    def _push_undo(self):
        self._undo.append(self._snapshot())
        self._redo.clear()
        self.dirty = True

    def _restore(self, snap):
        self.features, self.states = copy.deepcopy(snap[0]), list(snap[1])
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
        self.features.append(feat)
        return self._commit(len(self.features) - 1, feat)

    def edit_feature(self, index: int, params: dict) -> str | None:
        self._push_undo()
        feat = self.features[index]
        feat.params.update(params)
        return self._commit(index, feat)

    def delete_feature(self, index: int) -> None:
        self._push_undo()
        del self.features[index]
        self.recompute(index)

    # --- 檔案 ---
    def import_step(self, path: str) -> str | None:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = f.read()
        import os
        return self.add_feature("step", {"data": data, "source": os.path.basename(path)})

    def export_step(self, path: str) -> None:
        export_step([b.shape for b in self.bodies], path)

    def save_project(self, path: str) -> None:
        data = {"app": "3D Viewer", "version": FORMAT_VERSION,
                "features": [f.to_dict() for f in self.features]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        self.path, self.dirty = path, False

    def load_project(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version", 0) > FORMAT_VERSION:
            raise ValueError("專案檔版本過新,請更新程式")
        self.clear()
        self.features = [Feature.from_dict(d) for d in data["features"]]
        ids = [i for f in self.features for i in f.out_ids]
        self._next_id = max(ids, default=0) + 1
        self.recompute(0)
        self.path = path
