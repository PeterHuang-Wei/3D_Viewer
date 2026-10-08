"""各特徵的參數欄位定義:(key, 標籤, 型別, 預設/選項)。"""
from core import features as F
from core import thread as T

SKETCH = [
    ("plane", "草圖平面", "combo", list(F.PLANES)),
    ("offset", "平面偏移", "num", 0),
    ("kind", "輪廓", "combo", ["矩形", "圓", "正多邊形", "自訂多邊形"]),
    ("w", "矩形寬", "num", 20), ("h", "矩形高", "num", 10),
    ("r", "圓/多邊形半徑", "num", 10), ("n", "多邊形邊數", "num", 6),
    ("pts", "自訂點(x,y; x,y; ...)", "text", "0,0; 20,0; 10,15"),
    ("cx", "輪廓中心偏移 X", "num", 0), ("cy", "輪廓中心偏移 Y", "num", 0),
]
THREAD = [
    ("spec", "規格", "combo", T.spec_list()),
    ("d", "自訂:公稱直徑", "num", 10), ("p", "自訂:螺距", "num", 1.5),
    ("left", "左旋", "bool", False),
]
XYZ = lambda a, b, c: [("x", a, "num", 0), ("y", b, "num", 0), ("z", c, "num", 0)]  # noqa: E731

# kind -> (對話框標題, 欄位)
SCHEMAS = {
    "box": ("方塊", [("x", "長 X", "num", 20), ("y", "寬 Y", "num", 20), ("z", "高 Z", "num", 20)]),
    "cylinder": ("圓柱", [("r", "半徑", "num", 10), ("h", "高度", "num", 20)]),
    "sphere": ("球", [("r", "半徑", "num", 10)]),
    "cone": ("圓錐", [("r1", "底半徑", "num", 10), ("r2", "頂半徑", "num", 0),
                      ("h", "高度", "num", 20)]),
    "torus": ("環", [("R", "大半徑", "num", 15), ("r", "小半徑", "num", 3)]),
    "extrude": ("草圖拉伸", SKETCH + [("depth", "拉伸距離", "num", 10),
                                       ("sym", "雙向對稱", "bool", False)]),
    "revolve": ("草圖旋轉(繞草圖局部 Y 軸)", SKETCH + [("angle", "旋轉角度", "num", 360)]),
    "rod": ("外螺紋螺桿(沿 Z 軸)", THREAD + [("len", "長度", "num", 20)]),
    "thread_tool": ("內螺紋切削工具體", THREAD + [("len", "長度", "num", 20)]),
    "translate": ("平移", XYZ("ΔX", "ΔY", "ΔZ")),
    "scale": ("縮放", [("uniform", "等比例(只用 X 倍率)", "bool", True),
                       ("sx", "X 倍率", "num", 1), ("sy", "Y 倍率", "num", 1),
                       ("sz", "Z 倍率", "num", 1),
                       ("c", "以物件中心為基準(否則以原點)", "bool", True)]),
    "refplane": ("參考面(平行 / 傾斜)", [
        ("name", "名稱(可留空)", "text", ""),
        ("offset", "沿法向偏移距離", "num", 10),
        ("rx", "繞平面 X 軸傾斜(度)", "num", 0), ("ry", "繞平面 Y 軸傾斜(度)", "num", 0)]),
    "rotate": ("旋轉(度)", XYZ("繞 X", "繞 Y", "繞 Z")
               + [("c", "繞物件中心(否則繞原點)", "bool", True)]),
    "fillet": ("圓角", [("r", "半徑", "num", 2)]),
    "chamfer": ("倒角", [("d", "距離 1", "num", 2), ("d2", "距離 2(0 = 同距離 1)", "num", 0)]),
    "thread_hole": ("螺紋孔(由起點沿軸向切入)", THREAD + [
        ("depth", "孔深", "num", 10), ("axis", "孔軸向", "combo", ["Z", "X", "Y"]),
        ("x", "起點 X", "num", 0), ("y", "起點 Y", "num", 0), ("z", "起點 Z", "num", 0)]),
    "boolean": ("布林運算", [("keep", "保留原工具實體", "bool", False)]),
}
