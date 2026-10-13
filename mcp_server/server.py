"""3D Viewer MCP 伺服器(stdio)。啟動:python -m mcp_server"""
import base64

try:
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:                                   # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from .backends import Backends

INSTRUCTIONS = """控制 3D Viewer(CAD)。單位 mm、角度為度。流程:get_state 看現況 → 建立/修改 → 用 screenshot 或 get_state 驗證。
- 基本實體(方塊/圓柱/球...)以原點為中心建立,可用 position 平移。
- 邊/面以索引指定:先用 find_faces / find_edges 取得索引(例如頂面:normal=[0,0,1], extreme='max_z'),再傳給 add_feature。
- 草圖:create_sketch 之後用 add_feature('sketch_extrude', {'sketch': 草圖編號, 'depth': ...}) 拉伸;op 可為 新實體/聯集/切除(切除與聯集需 target 實體編號)。
- add_feature 通用:kind 與欄位用 feature_kinds 查詢;常用 fillet {body, edges:[索引], r}、chamfer {body, edges, d}、boolean {op:'聯集'|'差集'|'交集', target, tool, keep}、
  translate/rotate {body,x,y,z}、shell {body, faces:[索引], thickness}。
- 失敗時回傳 error(中文),模型已自動還原,可修正參數後重試。"""

app = _Server("3D Viewer", instructions=INSTRUCTIONS)
B = Backends()


def _call(op, **args):
    return B.call(op, args)


@app.tool()
def get_state() -> dict:
    """取得目前專案狀態:實體(體積/邊界/材料)、草圖、參考面、特徵歷史(含錯誤)、變數。"""
    return _call("get_state")


@app.tool()
def feature_kinds() -> dict:
    """列出所有特徵種類及其參數欄位(型別/預設/選項),供 add_feature 使用。"""
    return _call("feature_kinds")


@app.tool()
def new_project() -> dict:
    """清空並建立新專案。"""
    return _call("new_project")


@app.tool()
def open_project(path: str) -> dict:
    """開啟 .v3d 專案檔。"""
    return _call("open_project", path=path)


@app.tool()
def save_project(path: str | None = None) -> dict:
    """儲存專案(.v3d);未給路徑則存回目前檔案。"""
    return _call("save_project", path=path)


@app.tool()
def undo() -> dict:
    """復原上一個操作。"""
    return _call("undo")


@app.tool()
def redo() -> dict:
    """重做。"""
    return _call("redo")


@app.tool()
def create_primitive(kind: str, params: dict | None = None, position: list[float] | None = None) -> dict:
    """建立基本實體。kind: box{x,y,z} / cylinder{r,h} / sphere{r} / cone{r1,r2,h} / torus{R,r}。
    以原點為中心,position=[x,y,z] 可平移到指定位置。"""
    return _call("create_primitive", kind=kind, params=params, position=position)


@app.tool()
def create_sketch(plane: str | int, entities: list[dict], name: str = "", offset: float = 0.0) -> dict:
    """在平面(XY/XZ/YZ 或參考面編號)建立草圖。entities 為圖元清單(座標為平面內 u,v):
    {"t":"line","p1":[u,v],"p2":[u,v]}、{"t":"rect","p1":..,"p2":..}、{"t":"polygon","pts":[[u,v],...]}、
    {"t":"circle","c":[u,v],"r":r}、{"t":"arc","c":[u,v],"r":r,"a0":度,"a1":度}、
    {"t":"ellipse","c":..,"a":..,"b":..,"rot":度}、{"t":"spline","pts":[...]}。offset 為沿平面法向偏移。"""
    return _call("create_sketch", plane=plane, entities=entities, name=name, offset=offset)


@app.tool()
def create_ref_plane(base_plane: str | int, offset: float, name: str = "", rx: float = 0.0, ry: float = 0.0) -> dict:
    """建立參考面(平行偏移,可繞 X/Y 軸傾斜 rx/ry 度)。"""
    return _call("create_ref_plane", base_plane=base_plane, offset=offset, name=name, rx=rx, ry=ry)


@app.tool()
def add_feature(kind: str, params: dict | None = None, on_plane: str | int | None = None) -> dict:
    """新增任意特徵(fillet/chamfer/boolean/translate/rotate/scale/shell/draft/hole/pattern/mirror/
    sketch_extrude/sketch_revolve/sketch_sweep/sketch_loft/rib/material/appearance/insert/mate/delete...)。
    欄位請用 feature_kinds 查詢;缺少的欄位以預設補上。on_plane 可指定工作平面(XY/XZ/YZ 或參考面編號)。"""
    return _call("add_feature", kind=kind, params=params, on_plane=on_plane)


@app.tool()
def edit_feature(index: int, params: dict) -> dict:
    """修改歷史中第 index 個特徵的參數並重算(參數式建模)。"""
    return _call("edit_feature", index=index, params=params)


@app.tool()
def delete_feature(index: int) -> dict:
    """刪除歷史中的特徵。"""
    return _call("delete_feature", index=index)


@app.tool()
def set_variables(variables: dict) -> dict:
    """設定全域變數與公式,例如 {"w": 40, "h": "=w/2"};特徵參數可用 "=w+5" 引用。"""
    return _call("set_variables", variables=variables)


@app.tool()
def find_faces(body: int, normal: list[float] | None = None, geom_type: str | None = None,
               tol_deg: float = 5.0, extreme: str | None = None) -> dict:
    """查詢實體的面。normal 篩選平面法向(如 [0,0,1] 為朝上);geom_type: PLANE/CYLINDER/CONE/SPHERE...;
    extreme: max_x/min_x/max_y/min_y/max_z/min_z 取中心座標極值的面。回傳索引、中心、面積。"""
    return _call("find_faces", body=body, normal=normal, geom_type=geom_type, tol_deg=tol_deg, extreme=extreme)


@app.tool()
def find_edges(body: int, geom_type: str | None = None, direction: list[float] | None = None,
               tol_deg: float = 5.0, extreme: str | None = None, min_length: float = 0.0) -> dict:
    """查詢實體的邊。geom_type: LINE/CIRCLE...;direction 篩選直線方向(如 [0,0,1] 為垂直邊);
    extreme 同 find_faces。回傳索引、長度、中心。"""
    return _call("find_edges", body=body, geom_type=geom_type, direction=direction, tol_deg=tol_deg,
                 extreme=extreme, min_length=min_length)


@app.tool()
def body_info(body: int) -> dict:
    """實體的體積、表面積、質心、尺寸、邊界框、材料與質量。"""
    return _call("body_info", body=body)


@app.tool()
def distance(body_a: int, body_b: int) -> dict:
    """兩實體間的最短距離與最近點。"""
    return _call("distance", body_a=body_a, body_b=body_b)


@app.tool()
def export_step(path: str) -> dict:
    """匯出所有實體為 STEP。"""
    return _call("export_step", path=path)


@app.tool()
def export_stl(path: str, tolerance: float = 0.01) -> dict:
    """匯出所有實體為 STL(tolerance 為弦高誤差 mm,越小越精細)。"""
    return _call("export_stl", path=path, tolerance=tolerance)


@app.tool()
def screenshot(width: int = 900, height: int = 700, view: str = "等角視"):
    """擷取目前模型的畫面(view: 等角視/前視/上視/右視),回傳圖片供檢視結果。"""
    res = _call("screenshot", width=width, height=height, view=view)
    if not res.get("ok"):
        return res
    return Image(data=base64.b64decode(res["png_base64"]), format="png")


def main():
    app.run()
