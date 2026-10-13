"""後端選擇:優先連到執行中的 3D Viewer(橋接),否則使用無頭引擎。"""
import json
import os
import socket

from .engine import Engine

BRIDGE_FILE = os.path.join(os.path.expanduser("~"), ".3dviewer", "bridge.json")


def read_bridge_info(path: str | None = None):
    try:
        with open(path or BRIDGE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class LiveBackend:
    """透過本機 TCP 把操作交給執行中的視窗(每次呼叫一個連線,一行 JSON 請求/回應)。"""

    def __init__(self, info: dict, timeout: float = 180.0):
        self.info, self.timeout = info, timeout

    def call(self, op: str, args: dict) -> dict:
        req = json.dumps({"token": self.info["token"], "op": op, "args": args}, ensure_ascii=False) + "\n"
        with socket.create_connection(("127.0.0.1", int(self.info["port"])), timeout=self.timeout) as s:
            s.sendall(req.encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8"))


class Backends:
    def __init__(self, bridge_file: str | None = None):
        self.bridge_file = bridge_file
        self.headless = Engine()

    def call(self, op: str, args: dict | None = None) -> dict:
        args = args or {}
        info = read_bridge_info(self.bridge_file)
        if info:
            try:
                res = LiveBackend(info).call(op, args)
                res["mode"] = "live"
                return res
            except (OSError, ValueError):
                pass                                   # 視窗已關閉 -> 無頭
        res = self.headless.dispatch(op, args)
        res["mode"] = "headless"
        return res
