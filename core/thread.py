"""螺牙:螺旋線掃出牙型,再與圓柱做布林運算。ISO 公制 60° 簡化牙型。"""
import math
import cadquery as cq

# 公稱直徑 -> 螺距 (mm)
ISO_COARSE = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75,
              14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0, 30: 3.5}
ISO_FINE = {8: 1.0, 10: 1.25, 12: 1.5, 14: 1.5, 16: 1.5, 20: 1.5, 24: 2.0, 30: 2.0}

CUSTOM = "自訂"


def spec_list() -> list[str]:
    items = [f"M{d} 粗牙 (P{p})" for d, p in ISO_COARSE.items()]
    items += [f"M{d} 細牙 (P{p})" for d, p in ISO_FINE.items()]
    return items + [CUSTOM]


def parse_spec(text: str) -> tuple[float, float]:
    """'M10 粗牙 (P1.5)' -> (10, 1.5)"""
    d = float(text.split()[0][1:])
    p = float(text.split("(P")[1].rstrip(")"))
    return d, p


def make_threaded_rod(diameter: float, pitch: float, length: float,
                      left_hand: bool = False) -> cq.Shape:
    """沿 +Z 由 z=0 到 z=length 的外螺紋螺桿(也可當內螺紋的切削工具體)。"""
    if pitch <= 0 or diameter <= 0 or length <= 0:
        raise ValueError("直徑、螺距、長度必須大於 0")
    depth = 0.6134 * pitch                      # 牙高
    if depth >= diameter / 2:
        raise ValueError("螺距相對直徑過大")
    r_major = diameter / 2
    r_root = r_major - depth
    emb = 0.05 * pitch                          # 牙型嵌入core的量,確保融合
    t30 = math.tan(math.radians(30))
    base_half = 0.4375 * pitch
    crest_half = base_half - depth * t30
    prof = [(r_root - emb, -(base_half + emb * t30)), (r_major, -crest_half),
            (r_major, crest_half), (r_root - emb, base_half + emb * t30)]

    helix = cq.Wire.makeHelix(pitch, length, r_root, lefthand=left_hand)
    ridge = (cq.Workplane("XZ").polyline(prof).close()
             .sweep(cq.Workplane(obj=helix), isFrenet=True))
    core = cq.Workplane().circle(r_root).extrude(length)
    rod = core.union(ridge)
    clip = cq.Workplane().circle(r_major * 1.1).extrude(length)   # 切齊兩端
    result = rod.intersect(clip).val()
    if not result.Solids() or not result.isValid():
        raise ValueError("螺牙產生失敗,請調整參數")
    return result


def place(shape: cq.Shape, pos, axis: str) -> cq.Shape:
    """把沿 +Z 建立的工具體轉到指定軸向(+X/+Y/+Z)並移到 pos。"""
    if axis == "X":
        shape = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 90)
    elif axis == "Y":
        shape = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), -90)
    return shape.moved(cq.Location(cq.Vector(*pos)))


def threaded_hole(body: cq.Shape, diameter, pitch, depth, pos, axis="Z",
                  left_hand=False) -> cq.Shape:
    """在實體上由 pos 沿軸向切出內螺紋孔(螺桿工具體差集)。"""
    return cut_tool(body, place(make_threaded_rod(diameter, pitch, depth, left_hand), pos, axis))


def cut_tool(body: cq.Shape, tool: cq.Shape) -> cq.Shape:
    res = body.cut(tool).clean()
    if abs(res.Volume() - body.Volume()) < 1e-6:
        raise ValueError("螺紋孔未與實體相交,請確認位置與方向")
    return res
