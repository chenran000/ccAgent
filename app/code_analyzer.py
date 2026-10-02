"""代码分析/定位/修改模块"""
import logging
import os
from typing import Optional

from app.llm import CodeFixResult, create_structured
from app.prompts import CODE_FIX_PROMPT

logger = logging.getLogger(__name__)


def _resolve_within_root(file_path: str, allowed_root: str):
    """把 file_path 解析为 allowed_root 内的绝对路径；越界或未提供根目录时返回 None

    防两类绕过：../ 上跳（abspath 归一化处理）与同级目录前缀混淆（用分隔符后缀比对）。
    相对路径按项目根目录拼接（LLM 常返回相对路径）。
    """
    if not allowed_root:
        return None
    root = os.path.abspath(allowed_root)
    candidate = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    candidate = os.path.abspath(candidate)
    root_prefix = root.rstrip(os.sep) + os.sep
    if candidate != root and not candidate.startswith(root_prefix):
        return None
    return candidate


def read_file_content(file_path: str, max_lines: int = 500) -> Optional[str]:
    """读取文件内容"""
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content[:max_lines * 100]  # 限制读取长度
    except Exception:
        return None


def write_file_content(file_path: str, content: str, allowed_root: str = "") -> bool:
    """写入文件内容（提供 allowed_root 时强制路径围栏）"""
    target = _resolve_within_root(file_path, allowed_root)
    if not target:
        logger.warning("写入文件被拒绝(路径越界): %s", file_path)
        return False
    try:
        # 备份原文件
        backup_path = target + ".bak"
        if os.path.isfile(target):
            import shutil
            shutil.copy2(target, backup_path)

        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error("写入文件失败: %s", e)
        return False


def analyze_and_fix_code(
    file_path: str,
    line_number: int,
    error_log: str,
    issue_description: str,
    suggested_fix: str,
    ai_config: dict,
    auto_fix: bool = False,
    allowed_root: str = ""
) -> dict:
    """
    分析代码问题并生成修复方案

    Args:
        file_path: 问题文件路径
        line_number: 问题行号
        error_log: 错误日志
        issue_description: 问题描述
        suggested_fix: 建议修复方案
        ai_config: AI配置
        auto_fix: 是否自动修复

    Returns:
        {
            "file_path": str,
            "line_number": int,
            "original_code": str,
            "fixed_code": str,
            "fix_description": str,
            "success": bool,
            "message": str
        }
    """
    if not ai_config or not ai_config.get("api_key"):
        return {"success": False, "message": "未配置AI模型"}

    # 路径围栏：AI 给出的 file_path 只允许落在项目目录内
    resolved_path = _resolve_within_root(file_path, allowed_root)
    if not resolved_path:
        return {"success": False, "message": f"文件路径越界，已拒绝访问: {file_path}"}

    # 读取文件内容
    content = read_file_content(resolved_path)
    if content is None:
        return {"success": False, "message": f"无法读取文件: {resolved_path}"}

    # 获取问题行附近的代码上下文
    lines = content.split('\n')
    context_start = max(0, line_number - 20)
    context_end = min(len(lines), line_number + 20)
    context_lines = lines[context_start:context_end]
    context = '\n'.join(context_lines)

    # 标记问题行
    marked_context = ""
    for i, line in enumerate(context_lines, start=context_start + 1):
        marker = ">>>" if i == line_number else "   "
        marked_context += f"{marker} {i:4d}: {line}\n"

    user_content = f"""文件路径: {file_path}
问题行号: {line_number}
错误日志: {error_log}
问题描述: {issue_description}
建议修复方案: {suggested_fix}

代码上下文(>>>标记为问题行):
{marked_context}

请:
1. 分析问题原因
2. 生成修复后的代码
3. 只返回需要修改的代码行及其上下文
"""

    messages = [
        {"role": "system", "content": CODE_FIX_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        fix_result = create_structured(
            ai_config,
            CodeFixResult,
            messages,
            temperature=0.1,
            max_tokens=2000,
        )

        result = {
            "file_path": resolved_path,
            "line_number": line_number,
            "original_code": context,
            "fixed_code": fix_result.fixed_code,
            "fix_description": fix_result.fix_description,
            "success": True,
            "message": "代码分析完成"
        }

        # 如果自动修复,直接应用
        if auto_fix and fix_result.fixed_code:
            new_content = _apply_fix(content, line_number, context, fix_result.fixed_code)
            if write_file_content(resolved_path, new_content, allowed_root):
                result["message"] = "代码已自动修复"
            else:
                result["message"] = "代码修复失败"

        return result

    except Exception as e:
        return {"success": False, "message": f"AI调用失败: {str(e)}"}


def _apply_fix(
    original_content: str,
    line_number: int,
    old_context: str,
    new_code: str
) -> str:
    """
    将修复代码应用到原文件中

    策略: 用新代码替换旧上下文中的相关部分
    """
    lines = original_content.split('\n')
    context_lines = old_context.split('\n')
    new_code_lines = new_code.split('\n')

    # 计算上下文在原文件中的位置
    context_start = max(0, line_number - len(context_lines) // 2)

    # 查找旧上下文在原文件中的精确位置
    for start_idx in range(context_start - 5, context_start + 5):
        if start_idx < 0:
            continue
        window = lines[start_idx:start_idx + len(context_lines)]
        window_text = '\n'.join(window)

        # 简单匹配: 如果上下文有50%以上匹配
        old_lines = set(context_lines)
        window_set = set(window)
        match_ratio = len(old_lines & window_set) / max(len(old_lines), 1)

        if match_ratio > 0.5:
            # 找到匹配位置,应用修复
            new_lines = lines[:start_idx] + new_code_lines + lines[start_idx + len(context_lines):]
            return '\n'.join(new_lines)

    # 如果无法精确匹配,在问题行位置替换
    # 保守策略: 只替换问题行附近几行
    fix_start = max(0, line_number - len(new_code_lines) // 2)
    fix_end = min(len(lines), line_number + len(new_code_lines) // 2)

    new_lines = lines[:fix_start] + new_code_lines + lines[fix_end:]
    return '\n'.join(new_lines)
