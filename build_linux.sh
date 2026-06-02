#!/bin/bash
# ========================================
#  Linux 打包脚本 — 生成独立二进制 / AppImage
#  使用方法: bash build_linux.sh [appimage|binary]
# ========================================

set -e

MODE="${1:-binary}"
APPNAME="SysInfo"
DIST_DIR="dist"
BUILD_DIR="build"

echo "=== SysInfo Linux 打包 ==="
echo "模式: $MODE"

# 1. 安装依赖
echo "[1/4] 安装依赖..."
pip install --upgrade pip
pip install PySide6 pyinstaller

# 2. 清理
echo "[2/4] 清理旧构建..."
rm -rf "$DIST_DIR" "$BUILD_DIR"

# 3. PyInstaller 打包
echo "[3/4] PyInstaller 打包..."

if [ "$MODE" = "appimage" ]; then
    # AppImage 模式：onedir + 手动打包
    python -m PyInstaller \
        --name="$APPNAME" \
        --onedir \
        --windowed \
        --add-data="src:src" \
        main.py

    APPDIR="$DIST_DIR/${APPNAME}Dir"
    mkdir -p "$APPDIR/usr/bin"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    mkdir -p "$APPDIR/usr/share/applications"

    # 复制 PyInstaller 产物
    cp -r "$DIST_DIR/$APPNAME/"* "$APPDIR/usr/bin/"

    # 创建 .desktop 文件
    cat > "$APPDIR/usr/share/applications/${APPNAME}.desktop" << EOF
[Desktop Entry]
Type=Application
Name=SysInfo
Comment=系统信息查看器
Exec=${APPNAME}
Icon=${APPNAME}
Categories=Utility;
EOF

    # 创建 AppRun
    cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
exec "${HERE}/usr/bin/SysInfo" "$@"
APPRUN
    chmod +x "$APPDIR/AppRun"

    # 检查 appimagetool
    if command -v appimagetool &>/dev/null; then
        echo "[4/4] 生成 AppImage..."
        appimagetool "$APPDIR" "$DIST_DIR/${APPNAME}-x86_64.AppImage"
        echo "✓ AppImage 已生成: $DIST_DIR/${APPNAME}-x86_64.AppImage"
    else
        echo ""
        echo "========================================"
        echo "  AppDir 已准备: $APPDIR"
        echo "  下载 appimagetool 后运行:"
        echo "  appimagetool $APPDIR $DIST_DIR/${APPNAME}-x86_64.AppImage"
        echo "  下载地址: https://github.com/AppImage/AppImageKit/releases"
        echo "========================================"
    fi

else
    # 单文件二进制模式（简单）
    python -m PyInstaller \
        --name="$APPNAME" \
        --onefile \
        --windowed \
        --add-data="src:src" \
        main.py

    echo ""
    echo "========================================"
    echo "  ✓ 二进制已生成: $DIST_DIR/$APPNAME"
    echo "  直接运行: ./$DIST_DIR/$APPNAME"
    echo "========================================"
fi
