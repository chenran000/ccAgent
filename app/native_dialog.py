"""原生目录选择对话框(tkinter 实现)

桌面壳的 pywebview 桥不可用时(直接浏览器访问/桥未注入)的兜底方案:
由后端进程弹 Windows 原生目录选择框,任何前端宿主都能触发。
tkinter 必须在独立线程运行(每个线程自己的 Tk 实例),用完即毁。
"""
import logging
import threading

logger = logging.getLogger(__name__)

_dialog_lock = threading.Lock()  # 同时只允许一个对话框


def ask_directory(timeout_seconds: int = 300) -> str | None:
    """弹出系统目录选择框,返回所选路径;取消/超时/不可用返回 None"""
    result: list[str] = []
    done = threading.Event()

    def _run():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                path = filedialog.askdirectory(title="选择项目文件夹", parent=root)
            finally:
                root.destroy()
            if path:
                result.append(path)
        except Exception as e:
            logger.warning("原生目录对话框不可用: %s", e)
        finally:
            done.set()

    if not _dialog_lock.acquire(blocking=False):
        return None  # 已有对话框在弹出
    try:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        done.wait(timeout_seconds)
        return result[0] if result else None
    finally:
        _dialog_lock.release()
