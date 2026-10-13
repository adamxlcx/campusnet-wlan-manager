@echo off
rem ===================================================================
rem  CampusNet 启动器（批处理版，不保留控制台窗口）
rem  用法：双击本文件，或命令行 CampusNet.bat --minimized
rem  说明：真正的“零窗口”推荐使用同目录的 CampusNet.vbs
rem ===================================================================
setlocal
cd /d "%~dp0"

set "PYW=pythonw.exe"
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if exist "%~dp0venv\Scripts\pythonw.exe"  set "PYW=%~dp0venv\Scripts\pythonw.exe"
if not exist "%~dp0app.py" (
    echo [CampusNet] 未找到 app.py，请确认本脚本与 app.py 位于同一目录。
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0app.py" %*
exit /b 0
