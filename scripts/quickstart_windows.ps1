# GPUViewer Windows 一键安装：建 venv → 安装客户端 → 桌面快捷方式
# 用法：在仓库根打开 PowerShell 执行
#   powershell -ExecutionPolicy Bypass -File scripts\quickstart_windows.ps1
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Write-Host "== GPUViewer 一键安装 ==" -ForegroundColor Cyan

# 1) 定位 Python >= 3.10
$pyExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyExe) {
    Write-Host "未找到 python。请先安装 Python 3.10+ 并勾选 Add to PATH：" -ForegroundColor Red
    Write-Host "  https://www.python.org/downloads/"
    exit 1
}
$verOut = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$verOut -lt [version]"3.10") {
    Write-Host "需要 Python 3.10+，当前 $verOut" -ForegroundColor Red
    exit 1
}
Write-Host "Python $verOut ✓"

# 2) 虚拟环境（已存在则复用）
if (-not (Test-Path "$Repo\.venv\Scripts\python.exe")) {
    Write-Host "创建虚拟环境 .venv ..."
    & python -m venv "$Repo\.venv"
}
$Vpy = "$Repo\.venv\Scripts\python.exe"

# 3) 安装客户端（PySide6 等约 100MB，视网速几分钟）
Write-Host "安装客户端依赖（首次约 100MB）..."
& $Vpy -m pip install --quiet --upgrade pip
& $Vpy -m pip install --quiet "$Repo[client]"
if ($LASTEXITCODE -ne 0) { Write-Host "安装失败，请检查网络" -ForegroundColor Red; exit 1 }
Write-Host "依赖安装 ✓"

# 4) 桌面快捷方式（gui-script 启动器，无控制台窗口）
$lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "GPUViewer.lnk"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = "$Repo\.venv\Scripts\gpuviewer.exe"
$lnk.WorkingDirectory = $Repo
$icon = Join-Path $Repo "client\GPUViewer.ico"
if (Test-Path $icon) { $lnk.IconLocation = $icon }
$lnk.Save()
Write-Host "桌面快捷方式 ✓  $lnkPath"

Write-Host ""
Write-Host "安装完成！双击桌面 GPUViewer 启动——首次使用会自动弹出初始化向导：" -ForegroundColor Green
Write-Host "  录入 GPU 服务器（SSH 地址/账号/密码）→ 选一台当总服务端 → 自动部署 → 开始监控"
