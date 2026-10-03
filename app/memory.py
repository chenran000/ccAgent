"""工作区记忆(对齐 ZCode 的 memory 思路)

每个工作区一份持久记忆文件(Markdown),智能体可读写,跨会话生效。
存放于 DATA_DIR/memory/{工作区标签}.md,内容注入系统提示,使智能体
"记得"该项目的事实(技术栈/约定/已完成的工作/用户的偏好)。
"""
import hashlib
import logging
import os
import re
from pathlib import Path

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

MEMORY_MAX_CHARS = 6000


def _memory_path(workspace: str) -> Path:
    tag = hashlib.md5(workspace.encode()).hexdigest()[:8]
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", os.path.basename(workspace))[:30] or "workspace"
    d = DATA_DIR / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}_{tag}.md"


def read_memory(workspace: str) -> str:
    """读取工作区记忆;不存在返回空串"""
    try:
        return _memory_path(workspace).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.warning("记忆读取失败: %s", e)
        return ""


def write_memory(workspace: str, content: str) -> str:
    """覆盖写入记忆(自动截断超长);返回实际保存的内容"""
    content = (content or "").strip()[:MEMORY_MAX_CHARS]
    _memory_path(workspace).write_text(content + ("\n" if content else ""), encoding="utf-8")
    return content


def append_memory(workspace: str, entry: str) -> str:
    """追加一条记忆(自动加日期);去重(相同条目不重复追加)"""
    entry = (entry or "").strip().lstrip("- ")
    if not entry:
        return read_memory(workspace)
    from datetime import datetime
    line = f"- [{datetime.now().strftime('%Y-%m-%d')}] {entry[:500]}"
    existing = read_memory(workspace)
    if line.split("] ", 1)[-1] in existing:
        return existing  # 去重
    new = (existing + "\n" + line).strip()[:MEMORY_MAX_CHARS]
    _memory_path(workspace).write_text(new + "\n", encoding="utf-8")
    return new
