@echo off
REM ========================================
REM  Windows 打包脚本 — 生成独立 .exe 文件
REM  使用方法: 在 Windows 上运行此脚本
REM  需要: Python 3.9+ 和 pip
REM ========================================

echo [1/4] 安装依赖...
python -m pip install --upgrade pip
python -m pip install PySide6 pyinstaller

echo [2/4] 清理旧构建...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [3/4] 打包为单文件 exe...
python -m PyInstaller ^
    --name="SysInfo" ^
    --onefile ^
    --windowed ^
    --add-data="src;src" ^
    main.py

echo [4/4] 完成!
echo.
echo ========================================
echo  生成文件: dist\SysInfo.exe
echo  无需安装 Python，双击即可运行
echo  支持 Windows 7 / 8 / 10 / 11
echo ========================================
pause
