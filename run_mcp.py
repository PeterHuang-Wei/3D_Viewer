"""MCP 伺服器啟動入口:不依賴目前工作目錄,可直接被 MCP 用戶端以絕對路徑啟動。
用法:python D:\\path\\to\\Step\\run_mcp.py"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from mcp_server.server import main  # noqa: E402

if __name__ == "__main__":
    main()
