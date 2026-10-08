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
