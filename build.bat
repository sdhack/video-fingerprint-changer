@echo off
rem 一键打包脚本:产出 dist\视频指纹修改器\ 目录(onedir,秒开)
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul || (echo [错误] 未找到 Python,请先安装 Python 3.11+ & pause & exit /b 1)

echo [1/3] 安装依赖...
pip install --quiet tkinterdnd2 pyinstaller

echo [2/3] 打包中(onedir 免解压,启动快)...
pyinstaller --noconfirm --onedir --windowed --name "视频指纹修改器" ^
  --collect-all tkinterdnd2 ^
  --exclude-module unittest --exclude-module pydoc --exclude-module doctest ^
  --exclude-module test --exclude-module xmlrpc --exclude-module pygments ^
  "视频指纹修改器.pyw"
if errorlevel 1 (echo [错误] 打包失败 & pause & exit /b 1)

echo [3/3] 清理中间产物...
if exist build rmdir /s /q build
del /q *.spec 2>nul

echo.
echo 完成!程序位于 dist\视频指纹修改器\视频指纹修改器.exe
pause
