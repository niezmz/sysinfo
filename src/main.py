"""应用程序入口点。"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from src.mainwindow import MainWindow


def main():
    """启动系统信息查看器。"""
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SysInfo")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("SysInfo")

    # 设置应用图标（如果有的话）
    icon_path = Path(__file__).parent / "resources" / "icon.png"
    if icon_path.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
