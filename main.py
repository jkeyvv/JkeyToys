"""JkeyToys - PySide6 UART 调试工具入口."""

import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from version import __version__


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JkeyToys")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
