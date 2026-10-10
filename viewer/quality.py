"""顯示精細度(只影響畫面,不影響模型與匯出)。"""

# 名稱 -> 網格弦高誤差(mm)、角度誤差(rad)、每條曲線邊的取樣點數、草圖圓每圈線段數
QUALITY = {
    "低": {"tol": 0.1, "ang": 0.3, "edge_pts": 32, "sketch_segs": 64},
    "標準": {"tol": 0.03, "ang": 0.15, "edge_pts": 64, "sketch_segs": 128},
    "高": {"tol": 0.01, "ang": 0.08, "edge_pts": 128, "sketch_segs": 256},
    "超高": {"tol": 0.002, "ang": 0.03, "edge_pts": 256, "sketch_segs": 512},
}
DEFAULT = "高"
