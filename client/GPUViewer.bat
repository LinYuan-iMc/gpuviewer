@echo off
setlocal
rem GPUViewer 客户端启动器（无控制台窗口）。
rem 前置：仓库根已建 .venv 并安装 client/daemon 依赖（见 README「客户端启动」）。
rem 首次使用请在程序设置对话框中填服务地址与 Token。
chcp 65001 >nul
set ROOT=%~dp0..
set PYTHONPATH=%ROOT%\daemon;%ROOT%\client;%ROOT%\shared
if exist "%ROOT%\.venv\Scripts\pythonw.exe" (
    "%ROOT%\.venv\Scripts\pythonw.exe" -m gpuviewer_client
) else (
    "%ROOT%\.venv\Scripts\python.exe" -m gpuviewer_client
)
