"""STEP/STP 讀寫。"""
import cadquery as cq


def import_step(path: str) -> list[cq.Shape]:
    """讀取 STEP 檔,回傳實體(Solid)清單;若無實體則回傳整體形狀。"""
    shape = cq.importers.importStep(path).val()
    solids = shape.Solids()
    return list(solids) if solids else [shape]


def export_step(shapes: list[cq.Shape], path: str) -> None:
    """將多個形狀輸出成單一 STEP 檔。"""
    if not shapes:
        raise ValueError("沒有可匯出的物件")
    compound = cq.Compound.makeCompound(shapes)
    cq.exporters.export(cq.Workplane(obj=compound), path, exportType="STEP")


def step_text_to_shapes(text: str) -> list[cq.Shape]:
    """由 STEP 文字內容建立實體(專案檔內嵌 STEP 用)。"""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "in.step")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return import_step(path)


def shapes_to_step_text(shapes: list[cq.Shape]) -> str:
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.step")
        export_step(shapes, path)
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
