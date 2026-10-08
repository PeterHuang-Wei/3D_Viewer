import sys

from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.load(sys.argv[1])
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
