"""便捷入口 — 直接运行此文件启动应用。"""

import os
import sys

# Wayland 不支持窗口定位/置顶/透明度，强制 X11 兼容层
if sys.platform == "linux":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from src.main import main

if __name__ == "__main__":
    main()
