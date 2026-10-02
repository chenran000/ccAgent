"""工作区模型(对齐 ZCode 的 workspace 概念)

用户选择本地项目文件夹作为当前工作区,一切代码相关操作(文件树/检查/修复)
以它为根。工作区路径持久化到 DATA_DIR/workspace.json,重启后自动恢复。
workspace 身份 = 规范化路径(与 ZCode workspaceIdentity 语义一致)。
"""
import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

WORKSPACE_FILE = DATA_DIR / "workspace.json"

# 文件树忽略规则(与 ZCode 默认视图一致)
IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".idea", ".vscode", ".next",
    "dist", "build", "coverage", ".nyc_output", ".cache", "venv", "env",
    ".tox", ".pytest_cache", "target", "output", "out", ".testassistant",
}
IGNORE_FILES = {".DS_Store", "Thumbs.db"}


def _load() -> dict:
    try:
        return json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_workspace(path: str) -> str:
    """规范化为绝对路径(工作区身份);不存在时抛 ValueError"""
    candidate = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.isdir(candidate):
        raise ValueError(f"目录不存在: {candidate}")
    return os.path.normpath(candidate)


def get_current_workspace() -> Optional[str]:
    """当前工作区路径;已失效(被删/移动)时返回 None 并清理记录"""
    data = _load()
    path = data.get("path")
    if path and os.path.isdir(path):
        return path
    if path:
        logger.warning("工作区目录已失效,自动清除: %s", path)
        _save({})
    return None


def set_current_workspace(path: str) -> str:
    normalized = normalize_workspace(path)
    _save({"path": normalized})
    return normalized


def clear_workspace() -> None:
    _save({})


def is_within_workspace(file_path: str) -> bool:
    """路径围栏:文件必须位于当前工作区内"""
    ws = get_current_workspace()
    if not ws:
        return False
    candidate = os.path.abspath(file_path)
    return candidate == ws or candidate.startswith(ws.rstrip(os.sep) + os.sep)


def build_file_tree(workspace: str, max_depth: int = 8, max_entries: int = 2000) -> List[dict]:
    """构建工作区文件树(忽略构建产物/依赖目录,限深度与总量防大仓库卡死)"""
    nodes: List[dict] = []
    count = 0

    def walk(dir_path: str, prefix_path: str, depth: int) -> List[dict]:
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return []
        children: List[dict] = []
        try:
            entries = sorted(os.listdir(dir_path), key=lambda e: (not os.path.isdir(os.path.join(dir_path, e)), e.lower()))
        except PermissionError:
            return []
        for entry in entries:
            if count >= max_entries:
                break
            if entry in IGNORE_DIRS or entry in IGNORE_FILES or entry.startswith("."):
                continue
            full = os.path.join(dir_path, entry)
            rel = os.path.relpath(full, prefix_path).replace(os.sep, "/")
            if os.path.isdir(full):
                count += 1
                sub = walk(full, prefix_path, depth + 1)
                children.append({"name": entry, "path": rel, "type": "directory", "children": sub})
            else:
                count += 1
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                children.append({"name": entry, "path": rel, "type": "file", "size": size})
        return children

    return walk(workspace, workspace, 0)
