"""MCP 引擎(無頭)、橋接(視窗)與 stdio 協定測試。"""
import asyncio
import os
import sys

import pytest

from mcp_server.engine import Engine


def test_headless_workflow(tmp_path):
    e = Engine()
    assert e.dispatch("get_state")["bodies"] == []
    r = e.dispatch("create_primitive", {"kind": "box", "params": {"x": 40, "y": 30, "z": 20}, "position": [10, 0, 0]})
    assert r["ok"] and len(r["new_bodies"]) == 1
    bid = r["new_bodies"][0]
    st = e.dispatch("get_state")
    assert st["bodies"][0]["min"][0] == pytest.approx(-10) and st["bodies"][0]["volume"] == pytest.approx(24000)
    # 頂面 / 垂直邊
    top = e.dispatch("find_faces", {"body": bid, "normal": [0, 0, 1], "extreme": "max_z"})["faces"]
    assert len(top) == 1 and top[0]["center"][2] == pytest.approx(10)
    vert = e.dispatch("find_edges", {"body": bid, "geom_type": "LINE", "direction": [0, 0, 1]})["edges"]
    assert len(vert) == 4
    r = e.dispatch("add_feature", {"kind": "fillet", "params": {"body": bid, "edges": [v["index"] for v in vert], "r": 3}})
    assert r["ok"], r
    assert e.dispatch("body_info", {"body": bid})["volume"] < 24000
    # 草圖 -> 拉伸切除
    sk = e.dispatch("create_sketch", {"plane": "XY", "entities": [{"t": "circle", "c": [0, 0], "r": 5}], "name": "孔"})
    sid = sk["new_ids"][0]
    r = e.dispatch("add_feature", {"kind": "sketch_extrude", "params": {"sketch": sid, "depth": 40, "sym": True,
                                                                         "op": "切除", "target": bid}})
    assert r["ok"], r
    # 失敗訊息回傳且模型不變
    n = len(e.dispatch("get_state")["features"])
    r = e.dispatch("add_feature", {"kind": "fillet", "params": {"body": bid, "edges": [0], "r": 999}})
    assert not r["ok"] and r["error"] and len(e.dispatch("get_state")["features"]) == n
    # 變數 / 編輯
    assert e.dispatch("set_variables", {"variables": {"w": 50}})["ok"]
    assert not e.dispatch("set_variables", {"variables": {"a": "=b", "b": "=a"}})["ok"]
    # 輸出與存取
    stl = tmp_path / "o.stl"
    assert e.dispatch("export_stl", {"path": str(stl)})["triangles"] > 0
    assert e.dispatch("export_step", {"path": str(tmp_path / "o.step")})["ok"]
    pr = tmp_path / "p.v3d"
    assert e.dispatch("save_project", {"path": str(pr)})["ok"]
    e2 = Engine()
    assert e2.dispatch("open_project", {"path": str(pr)})["ok"] and len(e2.dispatch("get_state")["bodies"]) == 1
    assert e.dispatch("undo")["ok"] and e.dispatch("redo")["ok"]
    assert not e.dispatch("nope")["ok"]
    assert "box" in e.dispatch("feature_kinds")["kinds"]


def test_two_bodies_distance_and_ref_plane():
    e = Engine()
    a = e.dispatch("create_primitive", {"kind": "box", "params": {"x": 10, "y": 10, "z": 10}})["new_bodies"][0]
    b = e.dispatch("create_primitive", {"kind": "sphere", "params": {"r": 2}, "position": [20, 0, 0]})["new_bodies"][0]
    assert e.dispatch("distance", {"body_a": a, "body_b": b})["distance"] == pytest.approx(13)
    pl = e.dispatch("create_ref_plane", {"base_plane": "XY", "offset": 15})
    assert pl["ok"]
    sk = e.dispatch("create_sketch", {"plane": pl["new_ids"][0], "entities": [{"t": "rect", "p1": [0, 0], "p2": [5, 5]}]})
    assert sk["ok"]
    assert not e.dispatch("find_faces", {"body": 999})["ok"]


def test_offscreen_screenshot():
    e = Engine()
    e.dispatch("create_primitive", {"kind": "box"})
    r = e.dispatch("screenshot", {"width": 200, "height": 150})
    if not r["ok"]:
        pytest.skip("無離屏繪圖環境:" + r["error"])
    import base64
    assert base64.b64decode(r["png_base64"])[:4] == b"\x89PNG"


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="需要 X 顯示")
def test_bridge_controls_window(tmp_path):
    from PyQt5.QtWidgets import QApplication
    from mcp_server.backends import Backends
    from ui.bridge import BridgeServer
    from ui.main_window import MainWindow
    import threading
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    info = str(tmp_path / "bridge.json")
    br = BridgeServer(w, info_path=info)
    br.start()
    result = {}

    def client():
        b = Backends(bridge_file=info)
        result["a"] = b.call("create_primitive", {"kind": "box", "params": {"x": 10, "y": 10, "z": 10}})
        result["bad"] = b.call("get_state", {"oops": 1})
        result["st"] = b.call("get_state")

    t = threading.Thread(target=client)
    t.start()
    while t.is_alive():
        app.processEvents()
        t.join(0.02)
    br.stop()
    assert result["a"]["ok"] and result["a"]["mode"] == "live"
    assert len(w.doc.bodies) == 1 and w.tree.count() == 1          # 視窗已同步
    assert not result["bad"]["ok"]
    assert result["st"]["bodies"][0]["volume"] == pytest.approx(1000)
    # token 錯誤被拒
    assert br.handle(b'{"token":"x","op":"get_state"}')["ok"] is False
    # 橋接關閉後退回無頭
    b = Backends(bridge_file=info)
    assert b.call("get_state")["mode"] == "headless"


def test_stdio_protocol(tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    env = {**os.environ, "HOME": str(tmp_path)}              # 避免讀到真實橋接檔

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], env=env,
                                       cwd=os.path.dirname(os.path.dirname(__file__)))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("create_primitive", {"kind": "cylinder", "params": {"r": 5, "h": 10}})
                st = await s.call_tool("get_state", {})
                return tools, res, st

    tools, res, st = asyncio.run(run())
    assert {"get_state", "add_feature", "find_faces", "screenshot", "create_sketch"} <= tools
    assert not getattr(res, "is_error", getattr(res, "isError", False)) and "headless" in str(res.content)
    assert "圓柱" in str(st.content)
