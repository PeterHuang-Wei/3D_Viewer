"""把 core.drawing 的圖元畫到 Qt(PDF / SVG / PNG)。座標單位 mm。"""
import math

from PyQt5.QtCore import QRectF, QSizeF, Qt, QPointF
from PyQt5.QtGui import (QColor, QFont, QImage, QPageSize, QPainter, QPen, QPdfWriter, QPolygonF)

from core.drawing import Sheet, export_dxf, sheet_items

STYLES = {  # 樣式 -> (顏色, 線寬 mm, 線型)
    "visible": ("#000000", 0.45, Qt.SolidLine), "hidden": ("#6a6a6a", 0.2, Qt.DashLine),
    "dim": ("#0a5a9c", 0.18, Qt.SolidLine), "center": ("#b00020", 0.15, Qt.DashDotLine),
    "frame": ("#000000", 0.7, Qt.SolidLine), "thin": ("#000000", 0.25, Qt.SolidLine),
}


def _font(h_mm: float) -> QFont:
    f = QFont()
    f.setFamilies(["Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC", "WenQuanYi Zen Hei", "Arial"])
    f.setPixelSize(max(1, int(round(h_mm * 10))))          # 以 0.1 mm 為單位繪製,避免整數字級過粗
    return f


def draw_sheet(p: QPainter, sheet: Sheet) -> None:
    """p 的座標系需為 mm、原點在左上。"""
    pw, ph = sheet.paper
    p.fillRect(QRectF(0, 0, pw, ph), QColor("white"))
    p.setRenderHint(QPainter.Antialiasing)
    Y = lambda y: ph - y  # noqa: E731    圖紙座標 y 向上 -> 畫布 y 向下
    for it in sheet_items(sheet):
        if it["t"] == "poly":
            color, w, style = STYLES[it["style"]]
            pen = QPen(QColor(color), w, style)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            pts = [QPointF(x, Y(y)) for x, y in it["pts"]]
            p.drawPolyline(QPolygonF(pts))
        elif it["t"] == "arrow":
            tx, ty = it["tip"]
            dx, dy = it["dir"]
            nx, ny = -dy, dx
            tri = QPolygonF([QPointF(tx, Y(ty)), QPointF(tx + dx * 3 + nx * 0.9, Y(ty + dy * 3 + ny * 0.9)),
                             QPointF(tx + dx * 3 - nx * 0.9, Y(ty + dy * 3 - ny * 0.9))])
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(STYLES["dim"][0]))
            p.drawPolygon(tri)
        else:
            p.save()
            p.translate(it["pos"][0], Y(it["pos"][1]))
            p.rotate(-it["rot"])
            p.scale(0.1, 0.1)
            p.setFont(_font(it["h"]))
            p.setPen(QColor("#102030") if it["h"] > 3 else QColor("#444"))
            w = 4000
            align = {"c": Qt.AlignHCenter, "l": Qt.AlignLeft, "r": Qt.AlignRight}[it["anchor"]]
            x = {"c": -w / 2, "l": 0, "r": -w}[it["anchor"]]
            p.drawText(QRectF(x, -it["h"] * 10 * 0.5, w, it["h"] * 10 * 1.4), align | Qt.AlignTop, it["s"])
            p.restore()


def render_image(sheet: Sheet, dpi: int = 100) -> QImage:
    pw, ph = sheet.paper
    k = dpi / 25.4
    img = QImage(int(pw * k), int(ph * k), QImage.Format_RGB32)
    p = QPainter(img)
    p.scale(k, k)
    draw_sheet(p, sheet)
    p.end()
    return img


def export_sheet(sheet: Sheet, path: str) -> None:
    """依副檔名輸出 .pdf / .svg / .png / .dxf。"""
    low = path.lower()
    pw, ph = sheet.paper
    if low.endswith(".dxf"):
        export_dxf(sheet, path)
    elif low.endswith(".png"):
        if not render_image(sheet, 200).save(path, "PNG"):
            raise ValueError("PNG 儲存失敗")
    elif low.endswith(".svg"):
        from PyQt5.QtSvg import QSvgGenerator
        g = QSvgGenerator()
        g.setFileName(path)
        g.setSize(__import__("PyQt5.QtCore", fromlist=["QSize"]).QSize(int(pw * 4), int(ph * 4)))
        g.setViewBox(QRectF(0, 0, pw, ph))
        g.setTitle("3D Viewer 工程圖")
        p = QPainter(g)
        draw_sheet(p, sheet)
        p.end()
    elif low.endswith(".pdf"):
        w = QPdfWriter(path)
        w.setPageSize(QPageSize(QSizeF(pw, ph), QPageSize.Millimeter))
        w.setPageMargins(__import__("PyQt5.QtCore", fromlist=["QMarginsF"]).QMarginsF(0, 0, 0, 0))
        w.setResolution(300)
        p = QPainter(w)
        k = 300 / 25.4
        p.scale(k, k)
        draw_sheet(p, sheet)
        p.end()
    else:
        raise ValueError("支援的格式:.pdf .svg .png .dxf")
