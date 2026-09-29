"""Web 测试 Agent 的 AI 调用层

单步决策与错误定位的 LLM 调用逻辑；任务循环编排已迁移到
app/test_agent_graph.py（LangGraph 状态机 + SQLite 检查点持久化）。
"""
import json
import os
import re
from typing import List, Optional

import openai

from app.llm import CodeIssueAnalysis, TestStepDecision, create_structured
from app.prompts import TEST_AGENT_PROMPT, CODE_ANALYSIS_WEB_PROMPT


def _render_elements(interactive_elements: List[dict]) -> str:
    """把可交互元素列表渲染为提示词片段"""
    if not interactive_elements:
        return ""
    lines = []
    for el in interactive_elements:
        desc = f"[{el.get('index', '')}] <{el.get('tag', '')}"
        if el.get("type"):
            desc += f" type={el['type']}"
        label = el.get("text") or el.get("placeholder") or el.get("label") or ""
        if label:
            desc += f" {label}"
        desc += ">"
        lines.append(desc)
    return "可交互元素列表:\n" + "\n".join(lines) + "\n\n"


def _render_digest(page_digest: Optional[dict]) -> str:
    """把页面结构摘要渲染为提示词片段(纯文本感知模式替代截图)"""
    if not page_digest:
        return ""
    lines = []
    title = page_digest.get("title")
    if title:
        lines.append(f"页面标题: {title}")
    headings = page_digest.get("headings") or []
    if headings:
        lines.append("标题结构: " + " | ".join(str(h) for h in headings))
    forms = page_digest.get("forms") or []
    if forms:
        lines.append("表单概览: " + " ; ".join(str(f) for f in forms))
    if not lines:
        return ""
    return "页面结构:\n" + "\n".join(lines) + "\n\n"


def _render_extracted(extracted: Optional[dict]) -> str:
    """把已提取变量渲染为提示词片段,供后续步骤比较"""
    if not extracted:
        return ""
    items = [f"- {k} = '{str(v)[:60]}'" for k, v in list(extracted.items())[-8:]]
    return "已提取变量:\n" + "\n".join(items) + "\n\n"


def _call_ai_for_test_step(
    test_goal: str,
    current_url: str,
    console_errors: List[str],
    network_errors: List[str],
    history: List[dict],
    ai_config: dict,
    interactive_elements: Optional[List[dict]] = None,
    page_digest: Optional[dict] = None,
    use_vision: bool = False,
    screenshot_base64: str = "",
    extracted: Optional[dict] = None,
) -> TestStepDecision:
    """调用AI决定下一步测试操作(DOM 文本感知为主,视觉可选增强)"""
    history_text = ""
    for i, step in enumerate(history):
        status = "✅" if step["success"] else "❌"
        history_text += f"步骤{i+1} {status}: {step['action']} - {step['target']} -> {step['result']}\n"
        if step.get("console_errors"):
            for err in step["console_errors"][:3]:
                history_text += f"  Console: {err}\n"

    error_summary = ""
    if console_errors:
        error_summary += "Console 错误:\n" + "\n".join(console_errors[:5]) + "\n"
    if network_errors:
        error_summary += "Network 错误:\n" + "\n".join(network_errors[:5]) + "\n"

    digest_text = _render_digest(page_digest)
    elements_text = _render_elements(interactive_elements)
    extracted_text = _render_extracted(extracted)

    def _make_messages(include_image: bool) -> list:
        msgs = [{"role": "system", "content": TEST_AGENT_PROMPT}]
        user_text = f"""测试目标: {test_goal}
当前URL: {current_url}
{digest_text}{elements_text}{extracted_text}历史操作:
{history_text or "无"}

{error_summary}

请分析当前页面状态，决定下一步测试操作。"""
        if include_image and screenshot_base64:
            msgs.append({"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": screenshot_base64, "detail": "high"}}
            ]})
        else:
            msgs.append({"role": "user", "content": user_text})
        return msgs

    # 视觉关闭:直接纯文本决策,省掉截图开销与纯文本模型的无效回退往返
    if not use_vision or not screenshot_base64:
        return create_structured(
            ai_config,
            TestStepDecision,
            _make_messages(False),
            temperature=0.1,
            max_tokens=500,
        )

    # 视觉开启:先携带截图,API 不支持图片时回退纯文本
    try:
        return create_structured(
            ai_config,
            TestStepDecision,
            _make_messages(True),
            temperature=0.1,
            max_tokens=500,
        )
    except openai.BadRequestError as e:
        if "image" in str(e).lower():
            return create_structured(
                ai_config,
                TestStepDecision,
                _make_messages(False),
                temperature=0.1,
                max_tokens=500,
            )
        raise


def _call_ai_for_code_analysis(
    error_log: str,
    console_errors: List[str],
    network_errors: List[str],
    project_path: str,
    screenshot_desc: str,
    ai_config: dict
) -> CodeIssueAnalysis:
    """调用AI分析错误并定位代码"""
    # 获取项目文件结构
    project_files = _get_project_file_tree(project_path)

    # 读取相关错误日志附近的代码
    relevant_code = _extract_error_context(error_log, console_errors, project_path)

    messages = [
        {"role": "system", "content": CODE_ANALYSIS_WEB_PROMPT}
    ]

    user_content = f"""项目路径: {project_path}
项目文件结构:
{project_files}

错误日志:
{error_log}

Console 错误:
{json.dumps(console_errors, ensure_ascii=False)}

Network 错误:
{json.dumps(network_errors, ensure_ascii=False)}

错误截图描述: {screenshot_desc}

相关代码上下文:
{relevant_code}

请分析错误原因，定位到具体的文件和行号，并给出修复方案。"""

    messages.append({"role": "user", "content": user_content})

    return create_structured(
        ai_config,
        CodeIssueAnalysis,
        messages,
        temperature=0.1,
        max_tokens=2000,
    )


def _get_project_file_tree(path: str, max_depth: int = 3) -> str:
    """获取项目文件结构树"""
    tree_lines = []

    def _walk(dir_path: str, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            items = sorted(os.listdir(dir_path))
            for item in items[:50]:  # 限制每层最多50个
                if item.startswith((".", "__pycache__", "node_modules", ".git")):
                    continue
                full_path = os.path.join(dir_path, item)
                if os.path.isdir(full_path):
                    tree_lines.append(f"{prefix}{item}/")
                    _walk(full_path, prefix + "  ", depth + 1)
                else:
                    ext = os.path.splitext(item)[1].lower()
                    if ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.html', '.css', '.json', '.yaml', '.yml']:
                        tree_lines.append(f"{prefix}{item}")
        except PermissionError:
            pass

    _walk(path, "", 0)
    return "\n".join(tree_lines[:200])  # 限制输出


def _extract_error_context(error_log: str, console_errors: List[str], project_path: str, max_files: int = 5) -> str:
    """根据错误日志尝试提取相关代码上下文"""
    context_parts = []

    # 尝试从错误信息中提取文件名
    all_errors = error_log + "\n" + "\n".join(console_errors)

    # 常见错误模式匹配文件名
    file_patterns = [
        r'[/\\]([^/\\]+\.(?:py|js|ts|tsx|jsx|vue))',
        r'at\s+(?:Object\.)?([^:\s(]+)\.(\w+)',
    ]

    found_files = set()
    for pattern in file_patterns:
        matches = re.findall(pattern, all_errors)
        for m in matches:
            if isinstance(m, tuple):
                found_files.add(m[0])
            else:
                found_files.add(m)

    # 读取找到的文件内容
    for filename in list(found_files)[:max_files]:
        for root, dirs, files in os.walk(project_path):
            if filename in files:
                full_path = os.path.join(root, filename)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    context_parts.append(f"=== 文件: {full_path} ===\n{content[:3000]}")
                    if len(context_parts) >= max_files:
                        break
                except Exception:
                    pass

    if not context_parts:
        # 如果没有找到文件，读取项目前几个关键文件
        key_files = ['main.py', 'index.js', 'App.tsx', 'App.js', 'routes.py', 'index.tsx']
        for key_file in key_files:
            for root, dirs, files in os.walk(project_path):
                if key_file in files:
                    full_path = os.path.join(root, key_file)
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        context_parts.append(f"=== 文件: {full_path} ===\n{content[:2000]}")
                        if len(context_parts) >= max_files:
                            break
                    except Exception:
                        pass

    return "\n\n".join(context_parts) if context_parts else "无法提取相关代码上下文"
