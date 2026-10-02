# -*- mode: python ; coding: utf-8 -*-
"""TestAssistant AI 单机版打包配置(PyInstaller onedir)

布局: dist/testassistant/
├── TestAssistant.exe          # 主程序(绑 127.0.0.1:2222,数据写 ~/.testassistant)
├── frontend/                  # React 构建产物(由后端同源托管)
└── _internal/                 # Python 运行时与依赖
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = [("frontend", "frontend")]
binaries = []
hiddenimports = [
    # uvicorn 按需动态加载的子模块
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "aiosqlite",
]

# chromadb:含 rust 原生绑定与大量运行时导入,整体收集最稳妥
for pkg in ("chromadb", "playwright", "langgraph", "langgraph_checkpoint", "langchain_core"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        print(f"[spec] collect_all({pkg}): data={len(d)} bin={len(b)} hidden={len(h)}")
    except Exception as e:
        print(f"[spec] collect_all({pkg}) skipped: {e}")

# pdfplumber/pdfminer 的字符映射数据
datas += collect_data_files("pdfplumber")
datas += collect_data_files("pdfminer")
hiddenimports += collect_submodules("pdfminer")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "sentence_transformers",
        "langfuse",
        "tkinter",
        "matplotlib",
        "PyQt5",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TestAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 控制台模式:日志可见,便于排障
    icon="app_icon.ico",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="testassistant",
)
