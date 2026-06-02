# 🖥️ SysInfo — 跨平台系统信息查看器

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://python.org)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-green)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)]()

SysInfo 是一个基于 PySide6 的跨平台桌面应用，用于查看详细的系统硬件信息和实时性能监控。

## ✨ 功能

| 模块 | 说明 |
|------|------|
| 📋 **系统概览** | 操作系统、主机名、处理器、语言、时区、IP 地址 |
| 🖥️ **硬件详情** | CPU、内存、GPU、磁盘、网络接口、主板信息 |
| ⚡ **运行实况** | CPU/GPU 使用率、温度、频率、功耗；内存、磁盘 I/O、网络速率 |
| 🪟 **悬浮监控窗** | 半透明、无边框、置顶的迷你仪表盘，拖拽式定位 |
| 📈 **折线图** | 每个性能指标包含 60 秒历史记录折线图 |

### 硬件信息采集

- **CPU**：型号、物理/逻辑核心数、频率、架构
- **内存**：总量、可用、已用百分比、交换空间
- **GPU**：型号、显存、使用率、温度、功耗、频率
- **磁盘**：物理磁盘列表、分区挂载点、使用情况
- **网络**：接口名称、状态、IP/MAC 地址、链路速率
- **主板**：制造商、型号、BIOS 版本等固件信息

### 平台支持

| 平台 | 硬件采集 | 实时监控 | 数据来源 |
|------|:--------:|:--------:|----------|
| 🐧 Linux | ✅ 完整 | ✅ 完整 | `/proc` / `/sys`、`lspci`、`lsblk`、`DMI`、AMD GPU sysfs |
| 🪟 Windows | ✅ 完整 | ✅ 完整 | Win32 API (`ctypes`)、注册表、NVML (NVIDIA GPU) |
| 🍎 macOS | ⚠️ 基础 | ❌ 未实现 | `sysctl`、`system_profiler` |

### 平台能力对比

| 能力 | Linux | Windows | 备注 |
|------|:-----:|:-------:|------|
| CPU 型号 / 核心数 | ✅ | ✅ | Win32: `GetSystemInfo` + `GetLogicalProcessorInformation` |
| CPU 实时频率 | ✅ | ✅ | Win32: `CallNtPowerInformation` |
| CPU 实时温度 | ✅ | ❌ | Windows 无标准 API，需内核驱动 |
| 物理内存 / 交换空间 | ✅ | ✅ | Win32: `GlobalMemoryStatusEx` |
| GPU 型号 / 显存 | ✅ | ✅ | Win32: 注册表 Display 类 |
| GPU 实时利用率 | ✅ (AMD) | ✅ (NVIDIA) | Windows 依赖 NVML，AMD/Intel 暂不支持 |
| GPU 实时温度/功耗 | ✅ (AMD) | ✅ (NVIDIA) | 同上 |
| 磁盘列表 / 用量 | ✅ | ✅ | Win32: `GetDiskFreeSpaceExW` + WMI |
| 磁盘 I/O 速率 | ✅ | ✅ | Win32: `DeviceIoControl(DISK_PERFORMANCE)`，需管理员权限 |
| 网络接口 / IP / MAC | ✅ | ✅ | Win32: `GetAdaptersAddresses` |
| 网络实时速率 | ✅ | ✅ | Win32: `GetIfTable` |
| 主板 / BIOS 信息 | ✅ | ✅ | Win32: 注册表 `HKLM\HARDWARE\DESCRIPTION\System\BIOS` |
| 系统语言 / 时区 | ✅ | ✅ | Win32: `GetUserDefaultLocaleName` + `GetDynamicTimeZoneInformation` |
| 悬浮监控窗 | ✅ | ✅ | |

## 🚀 快速开始

### 环境要求

- Python 3.9+
- pip

### 安装与运行

```bash
# 1. 克隆项目
git clone <repo-url> && cd sysinfo

# 2. 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行
python main.py
```

### 命令行参数

```bash
# Linux: 默认强制 X11 后端（Wayland 下悬浮窗功能受限）
python main.py
QT_QPA_PLATFORM=wayland python main.py   # Wayland 原生（无悬浮窗）

# Windows: 推荐以管理员身份运行（磁盘 I/O 监控需要）
python main.py
```

## 📦 打包为独立可执行文件

### Linux

```bash
# 单文件二进制
bash build_linux.sh

# AppImage（需要 appimagetool）
bash build_linux.sh appimage
```

### Windows

```cmd
:: 运行打包脚本
build_windows.bat
```

生成文件位于 `dist/` 目录下，无需安装 Python 环境即可运行。

## 🏗️ 项目结构

```
sysinfo/
├── main.py              # 便捷入口
├── pyproject.toml         # 项目元数据
├── requirements.txt       # 依赖列表
├── build_linux.sh         # Linux 打包脚本
├── build_windows.bat      # Windows 打包脚本
├── SysInfo.spec           # PyInstaller 规格文件
└── src/
    ├── __init__.py
    ├── main.py            # 应用入口（QApplication 初始化）
    ├── mainwindow.py      # 主窗口 UI（卡片、选项卡、悬浮窗）
    ├── sysinfo.py         # 硬件信息采集模块
    ├── perfmon.py         # 实时性能监控模块
    └── resources/         # 图标等资源文件
```

### 模块说明

| 模块 | 职责 |
|------|------|
| `main.py` | 入口文件，设置平台兼容环境变量 |
| `src/main.py` | QApplication 初始化、高 DPI 支持 |
| `src/mainwindow.py` | 主窗口、卡片 UI、选项卡、实时仪表盘、悬浮窗 |
| `src/sysinfo.py` | 跨平台硬件信息采集 — 平台分发到 Win32 API / `/proc`&`/sys` / `sysctl` |
| `src/perfmon.py` | 性能采样器 — 平台分发到 Win32 API / NVML / `/proc`&`/sys`，delta 计算 |

## 🎨 UI 特性

- **卡片式布局**：每个硬件类别独立卡片，带彩色侧边条
- **选项卡切换**：「系统概览」「硬件信息」「运行实况」
- **实时折线图**：60 秒历史数据用 QPainter 自绘（无需额外图表库）
- **悬浮监控窗**：置顶、半透明、可拖拽，每个指标 160×90 迷你卡片
- **颜色阈值**：绿色（正常）→ 黄色（警告）→ 红色（高温/高负载）
- **Wayland 兼容**：自动检测并强制使用 X11 后端（`QT_QPA_PLATFORM=xcb`）

## 🔧 技术栈

- **GUI**：[PySide6](https://pypi.org/project/PySide6/)（Qt 6 for Python）
- **打包**：[PyInstaller](https://pyinstaller.org/)
- **Windows 硬件采集**：`ctypes` 调用 Win32 API（kernel32 / iphlpapi / powrprof），零第三方依赖
- **Windows GPU 监控**：NVIDIA NVML (`nvml.dll`)，随 NVIDIA 驱动自带
- **跨平台**：仅依赖标准库 + PySide6，零额外 pip 依赖

## 📄 许可证

Apache-2.0 license

---

*Made with PySide6 & ❤️*
