"""通用參數對話框(繁體中文)。"""
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QLineEdit,
)


class ParamDialog(QDialog):
    """fields: [(key, 標籤, 型別, 預設/選項)],型別: num / combo / bool / text"""

    def __init__(self, title, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._w = {}
        form = QFormLayout(self)
        for key, label, kind, arg in fields:
            if kind == "num":
                w = QDoubleSpinBox()
                w.setRange(-1e6, 1e6)
                w.setDecimals(3)
                w.setValue(arg)
            elif kind == "combo":
                w = QComboBox()
                w.addItems(arg)
            elif kind == "bool":
                w = QCheckBox()
                w.setChecked(arg)
            else:
                w = QLineEdit(arg)
            self._w[key] = (kind, w)
            form.addRow(label, w)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("確定")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def values(self):
        out = {}
        for key, (kind, w) in self._w.items():
            out[key] = (w.value() if kind == "num" else w.currentText() if kind == "combo"
                        else w.isChecked() if kind == "bool" else w.text())
        return out


def ask(title, fields, parent=None):
    """顯示對話框,按取消回傳 None。"""
    dlg = ParamDialog(title, fields, parent)
    return dlg.values() if dlg.exec_() == QDialog.Accepted else None
