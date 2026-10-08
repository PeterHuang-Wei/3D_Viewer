"""文件模型:保存場景中的所有實體。"""
from dataclasses import dataclass, field
import cadquery as cq

from .io_step import import_step, export_step


@dataclass
class Body:
    name: str
    shape: cq.Shape


@dataclass
class Document:
    bodies: list[Body] = field(default_factory=list)
    path: str | None = None

    def clear(self) -> None:
        self.bodies.clear()
        self.path = None

    def add(self, shape: cq.Shape, name: str | None = None) -> Body:
        body = Body(name or f"實體{len(self.bodies) + 1}", shape)
        self.bodies.append(body)
        return body

    def open_step(self, path: str) -> None:
        self.clear()
        for shape in import_step(path):
            self.add(shape)
        self.path = path

    def save_step(self, path: str) -> None:
        export_step([b.shape for b in self.bodies], path)
        self.path = path
