"""工作区智能体工具集(ZCode 式:LLM 自主决定调用,全部限定在工作区内)

工具执行结果统一为 {"success": bool, "output": str},output 截断防止上下文爆炸。
"""
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

from app import workspace as ws_mod

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 4000
MAX_SEARCH_MATCHES = 50

# 忽略目录(搜索/树共用)
_SKIP_DIRS = ws_mod.IGNORE_DIRS | {"browsers", "_internal"}


def _resolve(path: str) -> str:
    """把相对/绝对路径解析并围栏到工作区内"""
    ws = ws_mod.get_current_workspace()
    if not ws:
        raise ValueError("未打开工作区")
    if not path or path in (".", "/"):
        return ws
    candidate = os.path.abspath(os.path.join(ws, path)) if not os.path.isabs(path) else os.path.abspath(path)
    if not (candidate == ws or candidate.startswith(ws.rstrip(os.sep) + os.sep)):
        raise ValueError(f"路径越出工作区: {path}")
    return candidate


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + f"\n...(截断,共 {len(text)} 字符)"


# ========== 工具实现 ==========

def _tool_list_tree(args: Dict[str, Any]) -> Dict[str, Any]:
    ws = ws_mod.get_current_workspace()
    root = _resolve(args.get("path") or "")
    tree = ws_mod.build_file_tree(root, max_depth=4, max_entries=300)

    def render(nodes: list, depth: int = 0) -> list:
        lines = []
        for n in nodes:
            lines.append(("  " * depth) + (n["name"] + ("/" if n["type"] == "directory" else "")))
            if n["type"] == "directory" and depth < 3:
                lines.extend(render(n.get("children") or [], depth + 1))
        return lines

    return {"success": True, "output": _clip(f"{root}\n" + "\n".join(render(tree)))}


def _tool_read_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve(args.get("path", ""))
    if not os.path.isfile(path):
        return {"success": False, "output": f"文件不存在: {path}"}
    try:
        content = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"success": False, "output": "二进制文件,无法按文本读取"}
    lines = content.splitlines()
    offset = max(1, int(args.get("offset", 1) or 1))
    limit = min(600, max(1, int(args.get("limit", 400) or 400)))
    selected = lines[offset - 1: offset - 1 + limit]
    numbered = "\n".join(f"{offset + i:>5}| {line}" for i, line in enumerate(selected))
    more = "\n...(有更多行,可用 offset 续读)" if offset - 1 + limit < len(lines) else ""
    rel = os.path.relpath(path, ws_mod.get_current_workspace())
    return {"success": True, "output": _clip(f"{rel} (共 {len(lines)} 行):\n{numbered}{more}")}


def _tool_search_code(args: Dict[str, Any]) -> Dict[str, Any]:
    ws = ws_mod.get_current_workspace()
    query = args.get("query", "")
    if not query:
        return {"success": False, "output": "缺少搜索关键词"}
    glob = (args.get("glob") or "").lower()
    matches = []
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if glob and not Path(name).suffix.lower().lstrip(".").startswith(glob.lstrip(".")):
                continue
            full = os.path.join(root, name)
            try:
                if os.path.getsize(full) > 1_000_000:
                    continue
                text = Path(full).read_text(encoding="utf-8")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if query.lower() in line.lower():
                    rel = os.path.relpath(full, ws)
                    matches.append(f"{rel}:{i}: {line.strip()[:160]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        break
            if len(matches) >= MAX_SEARCH_MATCHES:
                break
        if len(matches) >= MAX_SEARCH_MATCHES:
            break
    if not matches:
        return {"success": True, "output": f"未找到包含 '{query}' 的代码"}
    return {"success": True, "output": _clip("\n".join(matches))}


def _tool_write_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve(args.get("path", ""))
    content = args.get("content", "")
    if not path or os.path.isdir(path):
        return {"success": False, "output": "无效的文件路径"}
    try:
        if os.path.exists(path):
            import shutil
            shutil.copy2(path, path + ".bak")
        Path(path).write_text(content, encoding="utf-8")
        rel = os.path.relpath(path, ws_mod.get_current_workspace())
        action = "更新" if os.path.exists(path + ".bak") else "创建"
        return {"success": True, "output": f"已{action} {rel}({len(content)} 字符;原文件备份为 .bak)"}
    except Exception as e:
        return {"success": False, "output": f"写入失败: {e}"}


def _tool_run_command(args: Dict[str, Any]) -> Dict[str, Any]:
    command = (args.get("command") or "").strip()
    if not command:
        return {"success": False, "output": "缺少命令"}
    ws = ws_mod.get_current_workspace()
    try:
        proc = subprocess.run(
            command, shell=True, cwd=ws, capture_output=True, text=True,
            timeout=int(args.get("timeout", 60) or 60), errors="replace",
        )
        out = (proc.stdout or "") + (("\n[stderr] " + proc.stderr) if proc.stderr else "")
        return {"success": proc.returncode == 0,
                "output": _clip(f"exit={proc.returncode}\n{out.strip() or '(无输出)'}")}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "命令超时"}
    except Exception as e:
        return {"success": False, "output": f"执行失败: {e}"}


def _tool_read_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    from app.memory import read_memory
    ws = ws_mod.get_current_workspace()
    content = read_memory(ws)
    return {"success": True, "output": content or "(项目记忆为空)"}


def _tool_save_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    from app.memory import append_memory
    ws = ws_mod.get_current_workspace()
    entry = (args.get("entry") or "").strip()
    if not entry:
        return {"success": False, "output": "缺少记忆内容"}
    append_memory(ws, entry)
    return {"success": True, "output": f"已记住: {entry[:100]}"}


def _tool_search_standards(args: Dict[str, Any]) -> Dict[str, Any]:
    """搜索用户上传的编码规范(知识库 standards 分类)"""
    query = (args.get("query") or "").strip()
    if not query:
        return {"success": False, "output": "缺少检索关键词"}
    try:
        from app.vector_db import vector_db
        if not vector_db.enabled:
            return {"success": False, "output": "知识库向量能力未启用,请配置 EMBEDDING_API_KEY"}
        collection = vector_db._get_collection(_current_user_id())
        results = collection.query(query_texts=[query], n_results=6,
                                   where={"category": "standards"})
        docs = (results.get("documents") or [[]])[0]
        if not docs:
            return {"success": True, "output": "规范库中没有匹配的内容"}
        return {"success": True, "output": _clip("\n\n".join(docs))}
    except Exception as e:
        return {"success": False, "output": f"规范检索失败: {e}"}


def _current_user_id() -> int:
    """单用户版:取本地用户 id"""
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        user = db.query(User).order_by(User.id.asc()).first()
        return user.id if user else 0
    finally:
        db.close()


# ========== 工具注册表(OpenAI function calling 格式) ==========

TOOL_IMPLEMENTATIONS = {
    "list_tree": _tool_list_tree,
    "read_file": _tool_read_file,
    "search_code": _tool_search_code,
    "write_file": _tool_write_file,
    "run_command": _tool_run_command,
    "read_project_memory": _tool_read_memory,
    "save_project_memory": _tool_save_memory,
    "search_standards": _tool_search_standards,
}

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "list_tree",
            "description": "列出工作区(或其子目录)的文件树结构",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的子目录路径,缺省为工作区根"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取工作区内某个文本文件的内容(带行号)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                    "offset": {"type": "integer", "description": "起始行(从 1 开始),缺省 1"},
                    "limit": {"type": "integer", "description": "读取行数,缺省 400,最大 600"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在整个工作区中按关键词搜索代码,返回 文件:行号:内容 匹配列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词(大小写不敏感)"},
                    "glob": {"type": "string", "description": "可选的文件后缀过滤,如 py、ts"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或更新工作区内的文件(原文件自动备份为 .bak)。修改代码时优先完整给出修改后的文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在工作区目录执行命令行命令(如 git status、pytest、npm test),超时默认 60 秒",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "integer", "description": "超时秒数,缺省 60"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_project_memory",
            "description": "读取项目记忆(跨会话持久的项目事实:技术栈/约定/历史工作/用户偏好)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_project_memory",
            "description": "把重要事实存入项目记忆(跨会话持久),如:项目技术栈、编码约定、用户的偏好、已完成的工作。系统提示已注入全部记忆,重复内容不必重复保存",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry": {"type": "string", "description": "要记住的一条事实(一句话)"}
                },
                "required": ["entry"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_standards",
            "description": "在用户上传的编码规范库中检索相关规定(命名约定/安全红线/架构约定等),检查或写码前可先查规范",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词,如 命名 / 安全 / 日志"}
                },
                "required": ["query"],
            },
        },
    },
]


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    impl = TOOL_IMPLEMENTATIONS.get(name)
    if not impl:
        return {"success": False, "output": f"未知工具: {name}"}
    try:
        return impl(args or {})
    except Exception as e:
        logger.warning("工具 %s 执行异常: %s", name, e)
        return {"success": False, "output": f"执行异常: {e}"}
