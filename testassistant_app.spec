# -*- mode: python ; coding: utf-8 -*-
"""TestAssistant 桌面壳打包配置(onefile,放进后端 onedir 同目录)

产物: dist/TestAssistantApp.exe(窗口壳,双击启动 → 拉起后端 → 独立窗口)
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
]

for pkg in ("webview", "pythonnet", "clr_loader"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        print(f"[spec] collect_all({pkg}): data={len(d)} bin={len(b)} hidden={len(h)}")
    except Exception as e:
        print(f"[spec] collect_all({pkg}) skipped: {e}")

a = Analysis(
    ["shell_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TestAssistantApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 窗口模式:无控制台黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
