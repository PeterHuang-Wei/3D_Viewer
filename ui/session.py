"""最近開啟的檔案與自動儲存備份(路徑/清單管理)。"""
import json
import os

from PyQt5.QtCore import QSettings, QStandardPaths

MAX_RECENT = 10


def _settings():
    return QSettings("3DViewer", "3DViewer")


def recent_files() -> list[str]:
    v = _settings().value("recent", [])
    if isinstance(v, str):
        v = [v]
    return [str(p) for p in (v or [])]


def _set_recent(files):
    _settings().setValue("recent", list(files))


def add_recent(path: str) -> None:
    path = os.path.abspath(path)
    files = [p for p in recent_files() if p != path]
    _set_recent([path] + files[:MAX_RECENT - 1])


def remove_recent(path: str) -> None:
    _set_recent([p for p in recent_files() if p != path])


def clear_recent() -> None:
    _set_recent([])


def backup_path() -> str:
    d = os.path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or os.path.expanduser("~/.3dviewer"),
                     "autosave")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "autosave.v3d")


def read_backup_info():
    """回傳備份檔的 dict(含 source 欄位),無備份或損毀則 None。"""
    p = backup_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("features") else None
    except (OSError, ValueError):
        return None


def clear_backup() -> None:
    for p in (backup_path(), backup_path() + ".tmp"):
        try:
            os.remove(p)
        except OSError:
            pass
