"""主窗口 — 系统信息展示（卡片式 UI + 实时仪表盘）。"""

import os
import sys
from collections import deque

# Wayland 不支持窗口定位/置顶/透明度操作，强制 X11 后端
if sys.platform == "linux" and "WAYLAND_DISPLAY" in os.environ:
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QLabel,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QStatusBar,
    QScrollArea,
    QGridLayout,
    QFrame,
    QSizePolicy,
    QProgressBar,
    QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QColor, QLinearGradient

from src import sysinfo as si
from src.perfmon import PerfMonitor

# ── 卡片样式表 ──────────────────────────────────

CARD_STYLE = """
HardwareCard {
    background: #ffffff;
    border: 1px solid #dcdcdc;
    border-radius: 8px;
    padding: 0px;
}
HardwareCard:hover {
    border: 1px solid #4a9eff;
}
"""

CARD_TITLE_STYLE = """
    font-size: 16px;
    font-weight: bold;
    color: #333333;
    padding: 4px 0px;
"""

CARD_VALUE_STYLE = """
    color: #555555;
    font-size: 16px;
"""

# ── 卡片组件 ────────────────────────────────────

class HardwareCard(QFrame):
    """硬件信息卡片。

    带标题头和表单内容的可复用卡片组件。
    """

    def __init__(self, title: str, icon: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HardwareCard")
        self.setStyleSheet(CARD_STYLE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 16)
        self._layout.setSpacing(8)

        # 标题行
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧色条
        color_bar = QFrame()
        color_bar.setFixedSize(4, 20)
        color_bar.setStyleSheet(
            f"background: {self._color_for(title)}; border-radius: 2px; border: none;"
        )
        title_layout.addWidget(color_bar)

        # 标题文字
        title_label = QLabel(f"{icon}  {title}")
        title_label.setStyleSheet(CARD_TITLE_STYLE)
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self._layout.addWidget(title_widget)

        # 分割线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #eeeeee;")
        self._layout.addWidget(sep)

        # 内容区域（表单布局）
        self._form = QFormLayout()
        self._form.setSpacing(6)
        self._form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self._layout.addLayout(self._form)

    @staticmethod
    def _color_for(title: str) -> str:
        """根据卡片类别返回左侧色条颜色。"""
        colors = {
            "CPU": "#e74c3c",
            "处理器": "#e74c3c",
            "内存": "#3498db",
            "Memory": "#3498db",
            "GPU": "#9b59b6",
            "显卡": "#9b59b6",
            "磁盘": "#2ecc71",
            "存储": "#2ecc71",
            "网络": "#1abc9c",
            "Network": "#1abc9c",
            "主板": "#f39c12",
            "Motherboard": "#f39c12",
            "BIOS": "#e67e22",
            "系统": "#7f8c8d",
            "System": "#7f8c8d",
        }
        for key, color in colors.items():
            if key in title:
                return color
        return "#95a5a6"

    def add_row(self, label: str, value: str):
        """添加一行键值对。"""
        val_label = QLabel(str(value))
        val_label.setStyleSheet(CARD_VALUE_STYLE)
        val_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val_label.setWordWrap(True)
        val_label.setMinimumWidth(120)

        key_label = QLabel(label)
        key_label.setStyleSheet("color: #888888; font-size: 16px;")
        self._form.addRow(key_label, val_label)

    def add_widget(self, widget: QWidget):
        """添加自定义组件。"""
        self._form.addRow(widget)

    def clear_rows(self):
        """清空所有行。"""
        while self._form.count():
            item = self._form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_empty_hint(self, text: str = "无数据"):
        """显示空状态提示。"""
        hint = QLabel(text)
        hint.setStyleSheet("color: #bbbbbb; font-style: italic; padding: 8px;")
        hint.setAlignment(Qt.AlignCenter)
        self._form.addRow(hint)


# ── 实时仪表组件 ──────────────────────────────

def _color_for_value(value: float, thresholds: tuple[float, float] = (50, 80)) -> str:
    """根据数值返回颜色：绿 → 黄 → 红。"""
    if value < thresholds[0]:
        return "#27ae60"  # 绿色
    elif value < thresholds[1]:
        return "#f39c12"  # 黄色
    else:
        return "#e74c3c"  # 红色


class LiveMetricWidget(QFrame):
    """实时性能指标卡片。

    大号数字 + 颜色随阈值变化 + 进度条 + 背景折线图。
    """

    _HISTORY_MAX = 60  # 保留最近 60 个采样点（60 秒）

    def __init__(self, title: str, icon: str, unit: str = "%",
                 thresholds: tuple[float, float] = (50, 80),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._thresholds = thresholds
        self._unit = unit
        self._value = 0.0
        self._title = title
        self._color = "#27ae60"
        self._history: deque[float] = deque(maxlen=self._HISTORY_MAX)
        self._floating_mode = False  # 悬浮窗模式，禁用样式覆盖

        self.setObjectName("LiveMetric")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setMinimumHeight(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 10)
        layout.setSpacing(4)

        # 标题行
        header = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 18px; background: transparent;")
        header.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #555; background: transparent;"
        )
        header.addWidget(title_label)
        header.addStretch()
        layout.addLayout(header)

        # 大号数值
        self._value_label = QLabel("--")
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(
            "font-size: 48px; font-weight: bold; color: #27ae60; background: transparent;"
        )
        layout.addWidget(self._value_label)

        # 单位
        unit_label = QLabel(unit)
        unit_label.setAlignment(Qt.AlignCenter)
        unit_label.setStyleSheet(
            "font-size: 12px; color: #999; background: transparent;"
        )
        layout.addWidget(unit_label)

        # 进度条
        self._bar = QProgressBar()
        self._bar.setMaximum(100)
        self._bar.setMinimum(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(5)
        self._bar.setStyleSheet("""
            QProgressBar {
                background: transparent;
                border: none;
            }
            QProgressBar::chunk {
                background: #27ae60;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self._bar)

        self._apply_card_style("#27ae60")

    # ── 公开 API ──

    def push_history(self, value: float):
        """记录一个数据点到历史缓冲区。"""
        self._history.append(value)
        self.update()  # 触发重绘

    def _apply_card_style(self, color: str):
        self._color = color
        if self._floating_mode:
            return  # 悬浮窗保持自己独立的深色样式
        self.setStyleSheet(f"""
            LiveMetric {{
                background: #ffffff;
                border: 2px solid {color}30;
                border-radius: 12px;
            }}
        """)

    def update_value(self, value: float, suffix: str | None = None):
        self._value = value
        self._color = _color_for_value(value, self._thresholds)

        if value >= 100:
            text = f"{value:.0f}"
        elif value >= 10:
            text = f"{value:.1f}"
        else:
            text = f"{value:.1f}"
        self._value_label.setText(text)

        fs = "16px" if self._floating_mode else "48px"
        self._value_label.setStyleSheet(
            f"font-size: {fs}; font-weight: bold; color: {self._color}; background: transparent;"
        )

        bar_val = min(int(value), 100)
        self._bar.setValue(bar_val)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: transparent;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {self._color};
                border-radius: 2px;
            }}
        """)
        self._apply_card_style(self._color)

    def update_text(self, text: str, color: str = "#555"):
        self._color = color
        self._value_label.setText(text)
        fs = "16px" if self._floating_mode else "48px"
        self._value_label.setStyleSheet(
            f"font-size: {fs}; font-weight: bold; color: {color}; background: transparent;"
        )
        self._apply_card_style(color)
        self._bar.setValue(0)

    def update_network(self, rx_kbps: float, tx_kbps: float):
        def fmt(v: float) -> str:
            if v >= 1024:
                return f"{v / 1024:.1f} MB/s"
            return f"{v:.0f} KB/s"

        self._color = "#2980b9"
        self._value_label.setText(fmt(rx_kbps))
        fs = "11px" if self._floating_mode else "36px"
        self._value_label.setStyleSheet(
            f"font-size: {fs}; font-weight: bold; color: #2980b9; background: transparent;"
        )
        self._apply_card_style("#2980b9")
        self._bar.setValue(0)

    # ── 折线图绘制 ──

    def paintEvent(self, event):
        """先调父类绘制控件，再叠加折线图。"""
        super().paintEvent(event)

        if len(self._history) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制区域：卡片中下部（数值和进度条之间的背景区域）
        w = self.width()
        h = self.height()
        # 折线图占据底部约 35% 的空间
        chart_top = int(h * 0.6)
        chart_bottom = h - 8
        chart_left = 12
        chart_right = w - 12
        chart_h = chart_bottom - chart_top

        if chart_h < 10:
            painter.end()
            return

        # 数据归一化
        vals = list(self._history)
        vmin = min(vals)
        vmax = max(vals)
        if vmax - vmin < 0.1:
            vmax = vmin + 1  # 避免除零，画平线

        # 颜色
        base_color = QColor(self._color)
        line_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 80)
        fill_color_top = QColor(base_color.red(), base_color.green(), base_color.blue(), 40)
        fill_color_bot = QColor(base_color.red(), base_color.green(), base_color.blue(), 5)

        # 构建路径
        n = len(vals)
        dx = (chart_right - chart_left) / (n - 1)
        path = QPainterPath()

        for i, v in enumerate(vals):
            x = chart_left + i * dx
            y = chart_bottom - ((v - vmin) / (vmax - vmin)) * chart_h
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        # 填充区域
        area_path = QPainterPath(path)
        area_path.lineTo(chart_left + (n - 1) * dx, chart_bottom)
        area_path.lineTo(chart_left, chart_bottom)
        area_path.closeSubpath()

        gradient = QLinearGradient(0, chart_top, 0, chart_bottom)
        gradient.setColorAt(0, fill_color_top)
        gradient.setColorAt(1, fill_color_bot)
        painter.fillPath(area_path, gradient)

        # 画线
        pen = QPen(line_color, 1.5)
        painter.setPen(pen)
        painter.drawPath(path)

        painter.end()


# ── 悬浮监控窗 ──────────────────────────────────

class FloatingMonitorWindow(QFrame):
    """屏幕右上角悬浮监控窗。

    半透明、无边框、置顶，卡片 160×90，自动分组排列。
    """

    _HISTORY_MAX = 60

    def __init__(self, perfmon: PerfMonitor):
        super().__init__()
        self._perfmon = perfmon
        self._live_widgets: dict[str, LiveMetricWidget] = {}
        self._dragging = False
        self._drag_start: QPointF | None = None

        # 无边框 + 置顶 + 工具窗口
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.setMinimumWidth(360)
        self.setMaximumWidth(720)

        self._build_ui()
        self._position_top_right()

        # 所有子控件对鼠标透明，点击事件直达窗口本体
        self._make_children_transparent(self)

        # 独立定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

    def _build_ui(self):
        """构建分组卡片布局。"""
        # 悬浮窗：白色半透明背景，让深色卡片自然凸显
        self.setStyleSheet("""
            FloatingMonitorWindow {
                background: rgba(255, 255, 255, 180);
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        # 卡片分组
        groups = [
            ("#e74c3c", [
                ("f_cpu_percent",  "CPU占用",  "🧮", "%",   (50, 80)),
                ("f_cpu_temp",     "CPU温度",  "🌡️", "°C",  (60, 80)),
                ("f_cpu_freq",     "CPU频率",  "⚡",  "MHz", None),
            ]),
            ("#9b59b6", [
                ("f_gpu_percent",  "GPU占用",  "🎮", "%",   (50, 80)),
                ("f_gpu_temp",     "GPU温度",  "🔥",  "°C",  (60, 80)),
                ("f_gpu_power",    "GPU功耗",  "🔌",  "W",   None),
            ]),
            ("#3498db", [
                ("f_memory",       "内存占用", "🧠", "%",   (50, 80)),
            ]),
            ("#2ecc71", [
                ("f_disk_read",    "磁盘读取", "📖", "KB/s", None),
                ("f_disk_write",   "磁盘写入", "📝", "KB/s", None),
            ]),
            ("#f39c12", [
                ("f_net_rx",       "网络接收", "📥", "KB/s", None),
                ("f_net_tx",       "网络发送", "📤", "KB/s", None),
            ]),
        ]

        for accent, items in groups:
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            h_layout = QHBoxLayout(row)
            h_layout.setSpacing(6)
            h_layout.setContentsMargins(0, 2, 0, 2)

            for key, card_title, icon, unit, thresholds in items:
                w = self._make_mini_card(card_title, icon, unit, accent,
                                          thresholds or (999, 999))
                self._live_widgets[key] = w
                h_layout.addWidget(w)

            h_layout.addStretch()
            outer.addWidget(row)

    def _make_mini_card(self, title: str, icon: str, unit: str,
                        accent: str,
                        thresholds: tuple[float, float]) -> 'LiveMetricWidget':
        """创建 160×90 的小型指标卡片，深色主题 + 独立边框。"""
        w = LiveMetricWidget(title, icon, unit, thresholds)
        w._floating_mode = True
        w.setFixedSize(160, 90)

        # 卡片独立边框：亮色边框让卡片在白色底板上清晰可见
        w.setStyleSheet(f"""
            LiveMetric {{
                background: #252540;
                border: 2px solid rgba(255, 255, 255, 60);
                border-radius: 6px;
            }}
        """)

        # 缩小内边距
        w.layout().setContentsMargins(6, 4, 6, 4)
        w.layout().setSpacing(1)

        # 标题文字缩小 — 遍历找标题 label
        header_item = w.layout().itemAt(0)
        if header_item and header_item.layout():
            hl = header_item.layout()
            for i in range(hl.count()):
                child = hl.itemAt(i)
                if child and child.widget():
                    child_w = child.widget()
                    if isinstance(child_w, QLabel):
                        current = child_w.text()
                        if icon in current or title in current:
                            child_w.setStyleSheet(
                                "font-size: 10px; font-weight: bold; color: #ccccdd; background: transparent;"
                            )
                        elif len(current) <= 2:
                            # 图标
                            child_w.setStyleSheet(
                                "font-size: 13px; background: transparent;"
                            )

        # 数值文字缩小
        w._value_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #27ae60; background: transparent;"
        )
        w._value_label.setMinimumWidth(0)

        # 单位文字缩小 — 第3个元素
        unit_item = w.layout().itemAt(2)
        if unit_item and unit_item.widget():
            unit_w = unit_item.widget()
            if isinstance(unit_w, QLabel):
                unit_w.setStyleSheet(
                    "font-size: 9px; color: #8888aa; background: transparent;"
                )

        # 进度条更细
        w._bar.setFixedHeight(2)

        return w

    def _position_top_right(self):
        """定位到屏幕右上角。"""
        from PySide6.QtGui import QScreen
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            self.adjustSize()
            x = geo.right() - self.width() - 20
            y = geo.top() + 20
            self.move(x, y)

    def _refresh(self):
        """刷新悬浮窗数据。"""
        snap = self._perfmon.snapshot()
        w = self._live_widgets

        # CPU
        w["f_cpu_percent"].update_value(snap["cpu_percent"])
        w["f_cpu_percent"].push_history(snap["cpu_percent"])
        ct = snap.get("cpu_temp_c", 0)
        w["f_cpu_temp"].update_text(f"{ct}", _color_for_value(ct, (60, 80)))
        w["f_cpu_temp"].push_history(ct)
        freq = snap.get("cpu_freq_mhz", 0)
        if freq > 0:
            w["f_cpu_freq"].update_text(f"{freq:.0f}", "#4a9eff")
            w["f_cpu_freq"].push_history(freq)

        # GPU
        w["f_gpu_percent"].update_value(snap["gpu_percent"])
        w["f_gpu_percent"].push_history(snap["gpu_percent"])
        gt = snap.get("gpu_temp_c", 0)
        w["f_gpu_temp"].update_text(f"{gt}", _color_for_value(gt, (60, 80)))
        w["f_gpu_temp"].push_history(gt)
        pwr = snap.get("gpu_power_w", 0)
        if pwr > 0:
            w["f_gpu_power"].update_text(f"{pwr:.0f}", "#c39bdb")
            w["f_gpu_power"].push_history(pwr)

        # 内存
        w["f_memory"].update_value(snap["memory_percent"])
        w["f_memory"].push_history(snap["memory_percent"])

        # 磁盘
        w["f_disk_read"].update_network(snap["disk_read_kbps"], 0)
        w["f_disk_read"].push_history(snap["disk_read_kbps"])
        w["f_disk_write"].update_network(snap["disk_write_kbps"], 0)
        w["f_disk_write"].push_history(snap["disk_write_kbps"])

        # 网络
        w["f_net_rx"].update_network(snap["network_rx_kbps"], 0)
        w["f_net_rx"].push_history(snap["network_rx_kbps"])
        w["f_net_tx"].update_network(snap["network_tx_kbps"], 0)
        w["f_net_tx"].push_history(snap["network_tx_kbps"])

    # ── 拖拽：子控件透明 + 原生系统移动 ──

    def _make_children_transparent(self, parent: QWidget):
        """递归设置所有子控件对鼠标事件透明。"""
        for child in parent.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_start is not None:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._drag_start = None
            event.accept()


# ── 主窗口 ──────────────────────────────────────

class MainWindow(QMainWindow):
    """系统信息查看器主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("系统信息查看器 — SysInfo")
        self.resize(960, 760)
        self.setMinimumSize(640, 480)

        self._cards: dict[str, HardwareCard] = {}
        self._live_widgets: dict[str, LiveMetricWidget] = {}
        self._perfmon = PerfMonitor()

        # 悬浮窗
        self._floating = FloatingMonitorWindow(self._perfmon)

        self._setup_ui()
        self._setup_statusbar()
        self._refresh_info()

        # 实时刷新定时器（1 秒）
        self._live_timer = QTimer()
        self._live_timer.timeout.connect(self._refresh_live)
        self._live_timer.start(1000)

    # ═══════════════════════════════════════════
    #  UI 搭建
    # ═══════════════════════════════════════════

    def _setup_ui(self):
        """初始化界面布局。"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 8)

        # ── 悬浮窗开关 ──
        float_bar = QWidget()
        float_layout = QHBoxLayout(float_bar)
        float_layout.setContentsMargins(0, 0, 0, 0)
        float_layout.addStretch()
        self._float_checkbox = QCheckBox("悬浮监控窗")
        self._float_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                color: #555;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 2px solid #bbb;
            }
            QCheckBox::indicator:checked {
                background: #4a9eff;
                border-color: #4a9eff;
            }
        """)
        self._float_checkbox.toggled.connect(self._toggle_floating)
        float_layout.addWidget(self._float_checkbox)
        main_layout.addWidget(float_bar)

        # ── 选项卡 ──
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: #f5f6f8;
            }
            QTabBar::tab {
                padding: 8px 20px;
                font-size: 13px;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                border-bottom: 2px solid #4a9eff;
                color: #4a9eff;
                font-weight: bold;
            }
        """)
        main_layout.addWidget(self.tabs)

        # ── 概览选项卡 ──
        self.overview_group = QGroupBox()
        self.overview_group.setStyleSheet("QGroupBox { border: none; }")
        self.overview_layout = QFormLayout()
        self.overview_layout.setSpacing(8)
        self.overview_group.setLayout(self.overview_layout)
        self.tabs.addTab(self.overview_group, "📋 系统概览")

        # ── 硬件详情选项卡（卡片区）──
        self._setup_hardware_tab()

    def _setup_hardware_tab(self):
        """构建硬件卡片区域。"""
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        scroll.setWidget(container)

        # 外层垂直布局：网格 + 底部弹簧
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)

        # 卡片网格
        self.card_grid = QGridLayout()
        self.card_grid.setSpacing(12)
        self.card_grid.setContentsMargins(4, 4, 4, 4)
        outer.addLayout(self.card_grid)
        outer.addStretch()

        self.tabs.addTab(scroll, "🖥️ 硬件信息")

        # ── 运行实况选项卡 ──
        self._setup_live_tab()

    def _setup_live_tab(self):
        """构建实时性能仪表盘（分组布局）。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        scroll.setWidget(container)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(14)

        # ── 分组定义 ──
        groups = [
            ("🔴 CPU", "#e74c3c", [
                ("cpu_percent",    "CPU 使用率",     "🧮", "%",     (50, 80)),
                ("cpu_temp",       "CPU 温度",       "🌡️", "°C",   (60, 80)),
                ("cpu_freq",       "CPU 频率",       "⚡", "MHz",   None),
            ]),
            ("🟣 GPU", "#9b59b6", [
                ("gpu_percent",    "GPU 使用率",     "🎮", "%",     (50, 80)),
                ("gpu_temp",       "GPU 温度",       "🔥", "°C",   (60, 80)),
                ("gpu_power",      "GPU 功耗",       "🔌", "W",    None),
            ]),
            ("🔵 内存", "#3498db", [
                ("memory_percent", "内存使用率",     "🧠", "%",     (50, 80)),
            ]),
            ("🟢 磁盘", "#2ecc71", [
                ("disk_read",      "磁盘读取",       "📖", "KB/s",  None),
                ("disk_write",     "磁盘写入",       "📝", "KB/s",  None),
            ]),
            ("🟡 网络", "#f39c12", [
                ("network_rx",     "网络接收",       "📥", "KB/s",  None),
                ("network_tx",     "网络发送",       "📤", "KB/s",  None),
            ]),
        ]

        for group_title, accent_color, items in groups:
            group_box = self._create_group_box(group_title, accent_color, items)
            outer.addWidget(group_box)

        outer.addStretch()
        self.tabs.addTab(scroll, "⚡ 运行实况")

    def _create_group_box(self, title: str, accent_color: str,
                          items: list) -> QGroupBox:
        """创建一个卡片分组框，内部水平排列指标卡片。"""
        box = QGroupBox()
        box.setStyleSheet(f"""
            QGroupBox {{
                background: #ffffff;
                border: 1px solid #e0e0e0;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
                margin-top: 12px;
                padding: 16px 12px 12px 12px;
                font-size: 14px;
                font-weight: bold;
                color: #333;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
            }}
        """)
        box.setTitle(title)

        # 水平排列卡片
        h_layout = QHBoxLayout(box)
        h_layout.setSpacing(12)

        for key, card_title, icon, unit, thresholds in items:
            w = LiveMetricWidget(card_title, icon, unit,
                                  thresholds=thresholds or (999, 999))
            self._live_widgets[key] = w
            h_layout.addWidget(w)

        return box

    def _toggle_floating(self, checked: bool):
        """切换悬浮窗显示/隐藏。"""
        if checked:
            self._floating.show()
        else:
            self._floating.hide()

    def _setup_statusbar(self):
        """设置状态栏。"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    # ═══════════════════════════════════════════
    #  数据刷新
    # ═══════════════════════════════════════════

    def _refresh_info(self):
        """刷新所有系统信息。"""
        self.status_bar.showMessage("正在收集系统信息...")
        hw = si.get_all_hardware()
        self._populate_overview(hw)
        self._populate_hardware_cards(hw)
        self.status_bar.showMessage("信息已更新 ✓")

    # ═══════════════════════════════════════════
    #  概览选项卡
    # ═══════════════════════════════════════════

    def _add_form_row(self, layout: QFormLayout, label: str, value: str):
        val_label = QLabel(str(value))
        val_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val_label.setWordWrap(True)
        val_label.setStyleSheet("color: #444; font-size: 28px;")
        key_label = QLabel(label)
        key_label.setStyleSheet("color: #999; font-size: 32px;")
        layout.addRow(key_label, val_label)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate_overview(self, hw: dict):
        self._clear_layout(self.overview_layout)

        os_info = hw["os"]
        cpu = hw["cpu"]
        locale_info = si.get_locale_info()

        info = {
            "操作系统": f"{os_info['system']} {os_info['release']}",
            "主机名": os_info["hostname"],
            "处理器": cpu["name"],
            "当前用户": os.environ.get("USER", os.environ.get("USERNAME", "未知")),
            "系统语言": locale_info.get("language", "未知"),
            "时区": locale_info.get("timezone", "未知"),
            "当前 IP 地址": si.get_primary_ip(),
        }

        for label, value in info.items():
            self._add_form_row(self.overview_layout, label, value)

    # ═══════════════════════════════════════════
    #  硬件卡片选项卡
    # ═══════════════════════════════════════════

    def _populate_hardware_cards(self, hw: dict):
        """以卡片形式展示所有硬件信息。"""
        # 清空旧卡片
        self._clear_layout(self.card_grid)
        self._cards.clear()

        cpu = hw["cpu"]
        mem = hw["memory"]
        gpus = hw["gpu"]
        disks = hw["disks"]
        network = hw["network"]
        mb = hw["motherboard"]
        os_info = hw["os"]

        row = 0
        col = 0
        max_cols = 2

        # ── CPU 卡片 ──
        cpu_card = self._create_card("处理器", "💻")
        cpu_card.add_row("型号", cpu["name"])
        cpu_card.add_row("架构", cpu["architecture"])
        cpu_card.add_row("物理核心", f"{cpu['cores_physical']} 核")
        cpu_card.add_row("逻辑线程", f"{cpu['cores_logical']} 线程")
        if cpu.get("frequency_mhz"):
            cpu_card.add_row("主频", f"{cpu['frequency_mhz']} MHz")
        self._add_to_grid(cpu_card, row, col)
        col += 1
        if col >= max_cols:
            col = 0
            row += 1

        # ── 内存卡片 ──
        mem_card = self._create_card("内存", "🧠")
        mem_card.add_row("总内存", f"{mem['total_gb']} GB")
        mem_card.add_row("可用内存", f"{mem['available_gb']} GB")
        used_pct = round((1 - mem['available_gb'] / max(mem['total_gb'], 0.1)) * 100, 1)
        mem_card.add_row("已使用", f"{used_pct}%")
        if mem.get("swap_gb", 0) > 0:
            mem_card.add_row("交换空间", f"{mem['swap_gb']} GB (可用 {mem.get('swap_free_gb', 0)} GB)")
        self._add_to_grid(mem_card, row, col)
        col += 1
        if col >= max_cols:
            col = 0
            row += 1

        # ── GPU 卡片(们) ──
        for i, gpu in enumerate(gpus):
            gpu_card = self._create_card(f"显卡 #{i+1}", "🎮")
            gpu_card.add_row("名称", gpu["name"])
            if gpu.get("bus"):
                gpu_card.add_row("PCI 总线", gpu["bus"])
            self._add_to_grid(gpu_card, row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        if not gpus:
            self._add_empty_card("显卡", "🎮", "未检测到独立显卡", row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # ── 磁盘卡片 ──
        physical_disks = [d for d in disks if d.get("model")]
        partitions = [d for d in disks if d.get("mountpoint")]

        disk_card = self._create_card("磁盘 / 存储", "💾")
        if physical_disks:
            disk_card.add_row("物理磁盘", "")
            for d in physical_disks:
                disk_card.add_row(f"  {d['name']}", f"{d['size']} — {d.get('model', '')}")
        if partitions:
            disk_card.add_row("分区挂载", "")
            for p in partitions:
                disk_card.add_row(
                    f"  {p['mountpoint']}",
                    f"{p.get('used', '?')}/{p.get('size', '?')} (可用 {p.get('avail', '?')})"
                )
        if not physical_disks and not partitions:
            disk_card.set_empty_hint()
        self._add_to_grid(disk_card, row, col)
        col += 1
        if col >= max_cols:
            col = 0
            row += 1

        # ── 网络卡片 ──
        net_card = self._create_card("网络接口", "🌐")
        if network:
            for iface in network:
                status_icon = "🟢" if iface["state"] == "UP" else "🔴"
                header = f"{status_icon} {iface['name']}"
                # 收集该接口的多行信息
                lines = []
                if iface.get("ips"):
                    lines.append(f"IP: {iface['ips']}")
                if iface.get("model"):
                    lines.append(f"型号: {iface['model']}")
                if iface.get("speed"):
                    lines.append(f"速率: {iface['speed']}")
                if iface.get("mac"):
                    lines.append(f"MAC: {iface['mac']}")
                net_card.add_row(header, "\n".join(lines) if lines else "无详细信息")
        else:
            net_card.set_empty_hint()
        self._add_to_grid(net_card, row, col)
        col += 1
        if col >= max_cols:
            col = 0
            row += 1

        # ── 主板卡片 ──
        mb_card = self._create_card("主板", "🔧")
        if mb:
            for key, val in mb.items():
                mb_card.add_row(key, val)
        else:
            mb_card.set_empty_hint()
        self._add_to_grid(mb_card, row, col)

    # ═══════════════════════════════════════════
    #  卡片工具方法
    # ═══════════════════════════════════════════

    def _create_card(self, title: str, icon: str) -> HardwareCard:
        """创建一张硬件信息卡片。"""
        card = HardwareCard(title, icon)
        self._cards[title] = card
        return card

    def _add_to_grid(self, card: HardwareCard, row: int, col: int):
        """将卡片添加到网格布局。"""
        self.card_grid.addWidget(card, row, col)

    def _add_empty_card(self, title: str, icon: str, hint: str,
                        row: int, col: int):
        """添加一个空状态卡片。"""
        card = self._create_card(title, icon)
        card.set_empty_hint(hint)
        self._add_to_grid(card, row, col)

    # ═══════════════════════════════════════════
    #  运行实况 — 实时刷新
    # ═══════════════════════════════════════════

    def _refresh_live(self):
        """每秒刷新实时性能数据。"""
        snap = self._perfmon.snapshot()

        w = self._live_widgets

        # CPU 使用率
        w["cpu_percent"].update_value(snap["cpu_percent"])
        w["cpu_percent"].push_history(snap["cpu_percent"])

        # CPU 温度
        cpu_temp = snap.get("cpu_temp_c", 0)
        cpu_temp_color = _color_for_value(cpu_temp, (60, 80))
        w["cpu_temp"].update_text(f"{cpu_temp}", cpu_temp_color)
        w["cpu_temp"].push_history(cpu_temp)

        # CPU 频率
        freq = snap.get("cpu_freq_mhz", 0)
        if freq > 0:
            w["cpu_freq"].update_text(f"{freq:.0f}", "#2980b9")
            w["cpu_freq"].push_history(freq)
        else:
            w["cpu_freq"].update_text("--", "#bbb")

        # 内存
        w["memory_percent"].update_value(snap["memory_percent"])
        w["memory_percent"].push_history(snap["memory_percent"])

        # GPU 使用率
        w["gpu_percent"].update_value(snap["gpu_percent"])
        w["gpu_percent"].push_history(snap["gpu_percent"])

        # GPU 温度
        temp = snap.get("gpu_temp_c", 0)
        temp_color = _color_for_value(temp, (60, 80))
        w["gpu_temp"].update_text(f"{temp}", temp_color)
        w["gpu_temp"].push_history(temp)

        # GPU 功耗
        power = snap.get("gpu_power_w", 0)
        if power > 0:
            w["gpu_power"].update_text(f"{power:.0f}", "#8e44ad")
            w["gpu_power"].push_history(power)
        else:
            w["gpu_power"].update_text("--", "#bbb")

        # 网络速率
        w["network_rx"].update_network(snap["network_rx_kbps"], 0)
        w["network_rx"].push_history(snap["network_rx_kbps"])
        w["network_tx"].update_network(snap["network_tx_kbps"], 0)
        w["network_tx"].push_history(snap["network_tx_kbps"])

        # 磁盘 I/O
        w["disk_read"].update_network(snap["disk_read_kbps"], 0)
        w["disk_read"].push_history(snap["disk_read_kbps"])
        w["disk_write"].update_network(snap["disk_write_kbps"], 0)
        w["disk_write"].push_history(snap["disk_write_kbps"])

        # 更新状态栏
        self.status_bar.showMessage(
            f"实时监控中 | CPU: {snap['cpu_percent']}% ({snap.get('cpu_temp_c', 0)}°C)  "
            f"内存: {snap['memory_percent']}%  "
            f"GPU: {snap['gpu_percent']}% ({snap.get('gpu_temp_c', 0)}°C)  "
            f"RX: {snap['network_rx_kbps']:.0f} KB/s  "
            f"TX: {snap['network_tx_kbps']:.0f} KB/s  "
            f"DiskR: {snap['disk_read_kbps']:.0f} KB/s  "
            f"DiskW: {snap['disk_write_kbps']:.0f} KB/s"
        )
