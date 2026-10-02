"""TestAssistant AI 桌面壳(pywebview + WebView2)

职责:拉起后端子进程(TestAssistant.exe) → 等服务就绪 → 独立窗口加载 UI →
关窗退出时结束后端。后端本身仍是原 onedir exe,壳只做窗口与生命周期。
"""
import os
import subprocess
import sys
import time
import urllib.request

import webview

BACKEND_EXE = "TestAssistant.exe"
BACKEND_URL = "http://127.0.0.1:2222"
APP_TITLE = "TestAssistant AI"
WINDOW_SIZE = (1440, 900)


def setup_browser_env():
    """安装目录自带 browsers/ 时,让 Playwright 优先使用(用户机器无需装 Python/Chromium)"""
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(app_dir, "browsers")
    if os.path.isdir(bundled):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled


def backend_path() -> str:
    """后端 exe 与壳在同目录(同一 dist 文件夹)"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), BACKEND_EXE)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), BACKEND_EXE)


def wait_backend(timeout_seconds: int = 60) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BACKEND_URL}/docs", timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    setup_browser_env()
    backend = subprocess.Popen(
        [backend_path()],
        cwd=os.path.dirname(backend_path()),
        # 继承壳的环境变量(含 PLAYWRIGHT_BROWSERS_PATH),隐藏后端控制台窗口
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        if not wait_backend():
            webview.create_window(
                APP_TITLE,
                html="<h3 style='font-family:sans-serif'>后端服务启动失败,请直接运行同目录 TestAssistant.exe 查看日志</h3>",
                width=520,
                height=160,
                resizable=False,
            )
            webview.start()
            return

        webview.create_window(
            APP_TITLE,
            BACKEND_URL,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=(1024, 640),
        )
        webview.start()  # 阻塞直到窗口关闭
    finally:
        if backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=10)
            except subprocess.TimeoutExpired:
                backend.kill()


if __name__ == "__main__":
    main()
