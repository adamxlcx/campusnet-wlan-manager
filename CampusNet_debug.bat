@echo off
rem ===================================================================
rem  CampusNet 调试启动器（保留控制台窗口，便于查看异常与日志）
rem  用法：双击本文件；或 CampusNet_debug.bat --no-service / --dry-run
rem ===================================================================
setlocal
cd /d "%~dp0"

set "PY=python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\python.exe"  set "PY=%~dp0venv\Scripts\python.exe"

"%PY%" "%~dp0app.py" %*
set "RC=%ERRORLEVEL%"
echo.
echo [CampusNet] 进程已退出，返回码 %RC%
pause
exit /b %RC%
