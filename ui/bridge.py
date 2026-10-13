"""MCP 橋接:在 App 內開本機 TCP 伺服器,接收 mcp_server 轉來的操作並在視窗的文件上執行。
只綁 127.0.0.1,每次啟用產生隨機 token(寫入 ~/.3dviewer/bridge.json),請求必須帶 token。"""
import json
import os
import secrets
import tempfile

from PyQt5.QtCore import QObject
from PyQt5.QtNetwork import QHostAddress, QTcpServer

from mcp_server.backends import BRIDGE_FILE
from mcp_server.engine import Engine


class BridgeServer(QObject):
    def __init__(self, win, port: int = 8765, info_path: str | None = None):
        super().__init__(win)
        self.win, self.token = win, secrets.token_hex(16)
        self.info_path = info_path or BRIDGE_FILE
        self.engine = Engine(win.doc, screenshotter=self._shot)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._on_conn)
        self.port = 0
        self._buf: dict = {}

    def start(self) -> int:
        if not (self.server.listen(QHostAddress.LocalHost, 8765) or self.server.listen(QHostAddress.LocalHost, 0)):
            raise OSError(self.server.errorString())
        self.port = self.server.serverPort()
        os.makedirs(os.path.dirname(self.info_path), exist_ok=True)
        with open(self.info_path, "w", encoding="utf-8") as f:
            json.dump({"port": self.port, "token": self.token, "pid": os.getpid()}, f)
        try:
            os.chmod(self.info_path, 0o600)
        except OSError:
            pass
        return self.port

    def stop(self):
        self.server.close()
        try:
            os.remove(self.info_path)
        except OSError:
            pass

    @property
    def running(self) -> bool:
        return self.server.isListening()

    def _on_conn(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self._buf[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._on_data(s))
            sock.disconnected.connect(lambda s=sock: (self._buf.pop(s, None), s.deleteLater()))

    def _on_data(self, sock):
        self._buf[sock] = self._buf.get(sock, b"") + bytes(sock.readAll())
        if b"\n" not in self._buf[sock]:
            return
        line, _, _ = self._buf[sock].partition(b"\n")
        self._buf[sock] = b""
        sock.write((json.dumps(self.handle(line), ensure_ascii=False) + "\n").encode("utf-8"))
        sock.flush()
        sock.disconnectFromHost()

    def handle(self, line: bytes) -> dict:
        try:
            req = json.loads(line.decode("utf-8"))
        except ValueError:
            return {"ok": False, "error": "請求格式錯誤"}
        if not secrets.compare_digest(str(req.get("token", "")), self.token):
            return {"ok": False, "error": "token 錯誤"}
        had_bodies = bool(self.win.doc.bodies)
        res = self.engine.dispatch(req.get("op", ""), req.get("args") or {})
        self.win._update(reset_camera=not had_bodies)
        return res

    def _shot(self, width, height, view):
        self.win.scene.set_view(view)
        self.win.scene.plotter.render()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.png")
            self.win.scene.plotter.screenshot(p)
            with open(p, "rb") as f:
                return f.read()
