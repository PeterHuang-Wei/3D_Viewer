# 3D Viewer

以 Python 製作的 3D CAD 檢視/建模工具(CadQuery + PyVista + PyQt5),繁體中文介面。

## 安裝與執行(Windows 11)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py [檔案.step]
```

## 進度

- [x] 第一階段:主視窗、3D 顯示、STEP/STP 讀寫、標準視角、線框/邊線
- [ ] 第二階段:基本實體、草圖拉伸、平移旋轉、布林運算
- [ ] 第三階段:面/邊選取、倒角、圓角
- [ ] 第四階段:螺牙(外/內)
- [ ] 第五階段:特徵樹、參數重算、復原/重做、專案檔

## 測試

```
pip install pytest
python -m pytest tests
```
