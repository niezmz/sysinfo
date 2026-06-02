@echo off
chcp 65001 >nul
REM ========================================
REM  SysInfo — Windows 一键打包脚本
REM  生成独立的 SysInfo.exe（无需 Python）
REM  使用方法: 双击运行 或 build_windows.bat
REM ========================================

setlocal enabledelayedexpansion
set "APPNAME=SysInfo"
set "ICON_FILE=src\resources\icon.ico"

echo ========================================
echo   SysInfo — Windows 打包工具
echo ========================================
echo.

REM —— 1. 检查 Python ——
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo   下载: https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo [检测] Python %%v

REM —— 2. 检查/创建虚拟环境 ——
if not exist ".venv" (
    echo [1/5] 创建虚拟环境...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [错误] 无法创建虚拟环境，请确保 Python 中已安装 venv 模块
        pause
        exit /b 1
    )
) else (
    echo [1/5] 使用已有虚拟环境
)

REM —— 3. 激活虚拟环境 & 安装依赖 ——
call .venv\Scripts\activate.bat
echo [2/5] 安装依赖...
python -m pip install --upgrade pip -q
python -m pip install PySide6 pyinstaller -q
if %ERRORLEVEL% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)

REM —— 4. 清理旧构建 ——
echo [3/5] 清理旧构建...
if exist "dist\%APPNAME%" rmdir /s /q "dist\%APPNAME%" 2>nul
if exist "dist\%APPNAME%.exe" del /q "dist\%APPNAME%.exe" 2>nul
if exist "build" rmdir /s /q "build" 2>nul

REM —— 5. PyInstaller 打包 ——
echo [4/5] PyInstaller 打包中（可能需要几分钟）...

set "ICON_FLAG="
if exist "%ICON_FILE%" (
    set "ICON_FLAG=--icon=%ICON_FILE%"
    echo   使用图标: %ICON_FILE%
) else (
    echo   未找到图标文件，将使用默认图标
)

python -m PyInstaller ^
    --name="%APPNAME%" ^
    --onefile ^
    --windowed ^
    --clean ^
    %ICON_FLAG% ^
    --add-data="src;src" ^
    main.py

if %ERRORLEVEL% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

REM —— 6. 完成 ——
echo.
echo [5/5] 打包完成!
echo.
echo ========================================
if exist "dist\%APPNAME%.exe" (
    for %%A in ("dist\%APPNAME%.exe") do (
        echo   生成文件: dist\%APPNAME%.exe  (%%~zA 字节)
    )
    echo   无需安装 Python，双击即可运行
    echo   支持 Windows 10 / 11
    echo ========================================
) else (
    echo   生成目录: dist\%APPNAME%\
    echo ========================================
)
pause
