# -*- mode: python ; coding: utf-8 -*-
# GPUViewer Windows 单文件构建（v2.0.0）
# 用法：pip install pyinstaller && pyinstaller scripts/release.spec --noconfirm
# 产物：dist/GPUViewer.exe（双击即用，无需 Python；内置 daemon/shared 源码，
#       部署向导在冻结态经 sys._MEIPASS 取得上传载荷）
import sys
from pathlib import Path

REPO = Path(SPECPATH).resolve().parent          # SPECPATH=scripts/，其上级即仓库根

block_cipher = None

a = Analysis(
    [str(REPO / "client" / "gpuviewer_client" / "__main__.py")],
    pathex=[str(REPO / "client"), str(REPO / "daemon"), str(REPO / "shared")],
    binaries=[],
    datas=[
        # 部署载荷：daemon/shared 源码树 + 客户端图标
        (str(REPO / "daemon" / "gpuviewer_daemon"), "gpuviewer_daemon"),
        (str(REPO / "shared" / "gpuviewer_shared"), "gpuviewer_shared"),
        (str(REPO / "client" / "GPUViewer.ico"), "."),
    ],
    hiddenimports=["gpuviewer_client.deploy.payload"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc_data"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GPUViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                              # GUI：无控制台宿主
    icon=str(REPO / "client" / "GPUViewer.ico"),
)
