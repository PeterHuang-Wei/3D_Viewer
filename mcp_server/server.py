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
- 草圖可用 sketch_edit(修整/圓角/倒角/偏移/鏡射/陣列/投影)與 sketch_constrain(拘束與尺寸)精修。
- 曲面:add_feature 的 surface_extrude{sketch,depth}/surface_offset{body,faces,distance}/surface_trim{body,plane|tool,keep}/
  surface_knit{bodies:'1,2',tol}(封閉則成實體)/thicken{body,thickness,mode};get_state 的 type 為 surface 表示曲面體。
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


@app.tool()
def sketch_get(sketch: int) -> dict:
    """讀取草圖的圖元(含索引與 id)、拘束與自由度。"""
    return _call("sketch_get", sketch=sketch)


@app.tool()
def sketch_edit(sketch: int, action: str, indices: list[int] | None = None, params: dict | None = None) -> dict:
    """編輯草圖。action 與 params:
    add{entities:[同 create_sketch]} / delete(indices) / trim{index,click:[u,v]}(刪除點擊處那一段)/
    fillet{i,j,r} / chamfer{i,j,d1,d2?}(i,j 為相接的兩條直線索引)/ offset{index,distance}(封閉輪廓,正=向外)/
    mirror(indices){p,q,keep_original}(以 p-q 兩點連線為鏡射軸)/ linear_pattern(indices){n,dx,dy}/
    circular_pattern(indices){n,angle,center}/ project{body,construction}(把實體的邊投影進草圖)/
    construction(indices){on}(切換構造線,構造線不形成輪廓)。索引見 sketch_get。"""
    return _call("sketch_edit", sketch=sketch, action=action, indices=indices, **(params or {}))


@app.tool()
def sketch_constrain(sketch: int, add: list[dict] | None = None, remove: list[int] | None = None,
                     set_values: dict | None = None) -> dict:
    """為草圖加/移除拘束或修改尺寸值並求解(衝突時不改變)。add 例:
    {"t":"horizontal","refs":[[3]]}、{"t":"coincident","refs":[[1,"p2"],[2,"p1"]]}、
    {"t":"length","refs":[[1]],"v":50}、{"t":"radius","refs":[[4]],"v":8}、{"t":"angle","refs":[[1],[2]],"v":90}、
    {"t":"tangent","refs":[[1],[4]]}、{"t":"equal","refs":[[1],[2]]}。
    類型:coincident horizontal vertical parallel perpendicular tangent equal concentric fix midpoint point_on
    length distance hdist vdist radius diameter angle。refs 用圖元 id 與部位(p1/p2 端點、c 圓心、s/e 圓弧起訖)。
    set_values={拘束id: 新數值} 可驅動尺寸。回傳自由度(0=完全約束)。"""
    return _call("sketch_constrain", sketch=sketch, add=add, remove=remove, set_values=set_values)


@app.tool()
def suppress_feature(index: int, on: bool = True) -> dict:
    """抑制 / 取消抑制歷史中的特徵。"""
    return _call("suppress_feature", index=index, on=on)


@app.tool()
def rename_feature(index: int, name: str) -> dict:
    """重新命名歷史中的特徵。"""
    return _call("rename_feature", index=index, name=name)


@app.tool()
def move_feature(index: int, delta: int) -> dict:
    """把特徵在歷史中上移(-1)或下移(+1)並重算。"""
    return _call("move_feature", index=index, delta=delta)


@app.tool()
def set_rollback(index: int | None = None) -> dict:
    """回溯到指定特徵之後的狀態;不給 index 則回到最新。"""
    return _call("set_rollback", index=index)


@app.tool()
def import_step(path: str) -> dict:
    """匯入 STEP 檔為新實體。"""
    return _call("import_step", path=path)


@app.tool()
def measure(kind: str, body: int | None = None, index: int | None = None, body_b: int | None = None,
            index_b: int | None = None, entity: str = "face", contact: bool = True) -> dict:
    """量測。kind: edge(body,index:邊長/半徑/圓心)、face(body,index:面積/法向/半徑)、
    angle(entity=face|edge, body,index,body_b,index_b)、mass(整體質量/質心/慣性矩)、
    interference(各實體兩兩干涉,contact=是否也列出僅接觸)。"""
    return _call("measure", kind=kind, body=body, index=index, body_b=body_b, index_b=index_b,
                 entity=entity, contact=contact)


@app.tool()
def export_drawing(path: str, paper: str = "A3", views: list[str] | None = None, scale: str = "自動",
                   third_angle: bool = True, hidden: bool = True, dims: bool = True, hole_pos: bool = True,
                   radii: bool = True, chain: bool = False, section_axis: str | None = None,
                   section_offset: float = 0.0, title: str = "", part: str = "", author: str = "") -> dict:
    """輸出工程圖到 .pdf/.svg/.png/.dxf。paper: A4/A3/A2(橫式);views 預設 前視/上視/右視/等角視;
    scale 如 自動、1:2、2:1;section_axis: XZ(前剖)/YZ(側剖)/XY(上剖) 啟用剖視(與等角視共用位置)。"""
    return _call("export_drawing", path=path, paper=paper, views=views, scale=scale, third_angle=third_angle,
                 hidden=hidden, dims=dims, hole_pos=hole_pos, radii=radii, chain=chain, section_axis=section_axis,
                 section_offset=section_offset, title=title, part=part, author=author)


@app.tool()
def set_display(unit: str | None = None, precision: int | None = None) -> dict:
    """設定顯示單位(mm/cm/m/in)與小數位數(只影響 App 內量測/屬性文字)。"""
    return _call("set_display", unit=unit, precision=precision)


@app.tool()
def lock_plane(plane: str | int | dict | None = None) -> dict:
    """鎖定工作平面(等同 F3)。plane: XY/XZ/YZ、參考面編號、{"body":id,"face":索引}(實體的平面);
    不給則解除。鎖定後 create_sketch(plane="locked")、add_feature(on_plane="locked") 皆以此平面為準。
    on_plane / plane 也可直接傳 {"body","face"} 或 "locked"。"""
    return _call("lock_plane", plane=plane)


@app.tool()
def set_section(plane: str | int | dict | None = None, offset: float = 0.0, flip: bool = False) -> dict:
    """截面視圖(僅畫面,需即時模式):切掉平面法向正側;不給 plane 則關閉。"""
    return _call("set_section", plane=plane, offset=offset, flip=flip)


@app.tool()
def set_quality(name: str) -> dict:
    """顯示精細度(僅畫面,需即時模式):低/標準/高/超高。"""
    return _call("set_quality", name=name)


@app.tool()
def set_view(name: str) -> dict:
    """切換視角(需即時模式):等角視/前視/上視/右視等。"""
    return _call("set_view", name=name)


@app.tool()
def add_dimension_annotation(body: int, kind: str, index: int, mode: str = "半徑") -> dict:
    """在圓/圓弧邊(kind=edge)或圓柱/球面(kind=face)加 3D 半徑/直徑標註(mode=半徑|直徑)。"""
    return _call("add_dimension_annotation", body=body, kind=kind, index=index, mode=mode)


@app.tool()
def set_appearance(body: int, color: str | None = None, opacity: float | None = None,
                   visible: bool | None = None) -> dict:
    """設定實體顏色(#rrggbb)、透明度(0.05~1)、顯示或隱藏。"""
    return _call("set_appearance", body=body, color=color, opacity=opacity, visible=visible)


@app.tool()
def set_material(body: int, material: str, density: float = 1.0) -> dict:
    """指定實體材料(內建名稱見 list_materials;自訂材料給 density g/cm³),影響質量計算。"""
    return _call("set_material", body=body, material=material, density=density)


@app.tool()
def list_materials() -> dict:
    """列出內建材料與密度(g/cm³)。"""
    return _call("list_materials")


def main():
    app.run()
