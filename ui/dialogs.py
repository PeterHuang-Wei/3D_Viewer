"""通用參數對話框(繁體中文)。數值欄位可輸入數字,或以 = 開頭的算式(可引用「變數與公式」,例如 =板厚/2)。"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QComboBox, QCheckBox, QLineEdit, QMessageBox,
)


def fmt_num(v) -> str:
    """數字轉成欄位文字;字串(算式)原樣顯示。"""
    return v if isinstance(v, str) else format(float(v), ".10g")


def parse_num(text: str):
    """欄位文字 -> 數字或算式字串(以 = 開頭)。無法解析時丟出 ValueError。"""
    t = text.strip()
    if t.startswith("="):
        if len(t) < 2:
            raise ValueError("算式是空的")
        return t
    return float(t)


class ParamDialog(QDialog):
    """fields: [(key, 標籤, 型別, 預設/選項)],型別: num / combo / bool / text"""

    changed = pyqtSignal()            # 任一欄位改變(供即時預覽)

    def __init__(self, title, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._w = {}
        self._labels = {}
        form = QFormLayout(self)
        for key, label, kind, arg in fields:
            if kind == "num":
                w = QLineEdit(fmt_num(arg))
                w.setToolTip("輸入數字,或以 = 開頭的算式(例如 =板厚/2,變數在「編輯 → 變數與公式」設定)")
            elif kind == "combo":
                w = QComboBox()
                w.addItems(arg)
            elif kind == "bool":
                w = QCheckBox()
                w.setChecked(arg)
            else:
                w = QLineEdit(arg)
            (w.textChanged if isinstance(w, QLineEdit) else w.currentTextChanged if isinstance(w, QComboBox)
             else w.toggled).connect(lambda *_: self.changed.emit())
            self._w[key] = (kind, w)
            self._labels[key] = label
            form.addRow(label, w)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("確定")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _try_accept(self):
        for key, (kind, w) in self._w.items():
            if kind == "num":
                try:
                    parse_num(w.text())
                except ValueError:
                    QMessageBox.warning(self, "輸入錯誤", f"「{self._labels[key]}」請輸入數字,或以 = 開頭的算式")
                    w.setFocus()
                    return
        self.accept()

    def set_values(self, initial):
        for key, val in initial.items():
            if key not in self._w:
                continue
            kind, w = self._w[key]
            if kind == "num":
                w.setText(fmt_num(val))
            elif kind == "combo":
                w.setCurrentText(val)
            elif kind == "bool":
                w.setChecked(val)
            else:
                w.setText(val)

    def values(self):
        out = {}
        for key, (kind, w) in self._w.items():
            out[key] = (parse_num(w.text()) if kind == "num" else w.currentText() if kind == "combo"
                        else w.isChecked() if kind == "bool" else w.text())
        return out


def ask(title, fields, parent=None, initial=None):
    """顯示對話框,按取消回傳 None。initial 為各欄位初始值。"""
    dlg = ParamDialog(title, fields, parent)
    if initial:
        dlg.set_values(initial)
    return dlg.values() if dlg.exec_() == QDialog.Accepted else None
