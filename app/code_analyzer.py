"""代码分析/定位/修改模块"""
import os
import re
import json
from typing import Optional

import openai

from app.prompts import CODE_FIX_PROMPT


def _clean_json_output(text: str) -> str:
    """清理AI返回结果中的代码块标记"""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _parse_json_safely(text: str) -> dict:
    """安全地解析JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except Exception:
                pass
        return {}


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


def write_file_content(file_path: str, content: str) -> bool:
    """写入文件内容"""
    try:
        # 备份原文件
        backup_path = file_path + ".bak"
        if os.path.isfile(file_path):
            import shutil
            shutil.copy2(file_path, backup_path)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"写入文件失败: {e}")
        return False


def analyze_and_fix_code(
    file_path: str,
    line_number: int,
    error_log: str,
    issue_description: str,
    suggested_fix: str,
    ai_config: dict,
    auto_fix: bool = False
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

    # 读取文件内容
    content = read_file_content(file_path)
    if content is None:
        return {"success": False, "message": f"无法读取文件: {file_path}"}

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

    client = openai.OpenAI(
        api_key=ai_config["api_key"],
        base_url=ai_config["api_base_url"]
    )

    messages = [
        {"role": "system", "content": CODE_FIX_PROMPT}
    ]

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

    messages.append({"role": "user", "content": user_content})

    try:
        response = client.chat.completions.create(
            model=ai_config["chat_model"],
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
        )

        result_text = response.choices[0].message.content.strip()

        # 解析AI返回的修复代码
        fix_result = _extract_fix_result(result_text)

        result = {
            "file_path": file_path,
            "line_number": line_number,
            "original_code": context,
            "fixed_code": fix_result.get("fixed_code", ""),
            "fix_description": fix_result.get("fix_description", result_text),
            "success": True,
            "message": "代码分析完成"
        }

        # 如果自动修复,直接应用
        if auto_fix and fix_result.get("fixed_code"):
            new_content = _apply_fix(content, line_number, context, fix_result["fixed_code"])
            if write_file_content(file_path, new_content):
                result["message"] = "代码已自动修复"
            else:
                result["message"] = "代码修复失败"

        return result

    except Exception as e:
        return {"success": False, "message": f"AI调用失败: {str(e)}"}


def _extract_fix_result(text: str) -> dict:
    """从AI返回结果中提取修复代码"""
    # 尝试提取代码块
    code_block = re.search(r'```(?:\w+)?\n([\s\S]*?)\n```', text)
    if code_block:
        return {
            "fixed_code": code_block.group(1),
            "fix_description": text[:code_block.start()].strip()
        }

    # 尝试JSON解析
    cleaned = _clean_json_output(text)
    try:
        data = json.loads(cleaned)
        return {
            "fixed_code": data.get("fixed_code", data.get("code", "")),
            "fix_description": data.get("fix_description", data.get("description", ""))
        }
    except Exception:
        pass

    # 默认:整个返回作为修复代码
    return {
        "fixed_code": text,
        "fix_description": ""
    }


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
