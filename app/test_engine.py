"""Web 测试 Agent 核心模块 - Playwright 测试引擎"""
import json
import re
import uuid
import asyncio
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import openai

from app.browser_capture import BrowserCapture
from app.prompts import TEST_AGENT_PROMPT, CODE_ANALYSIS_PROMPT

# 存储运行中的测试任务
running_test_tasks: Dict[str, dict] = {}


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
        return {"action": "done", "target": "", "success": True, "reason": "解析失败"}


def _call_ai_for_test_step(
    test_goal: str,
    current_url: str,
    screenshot_base64: str,
    console_errors: List[str],
    network_errors: List[str],
    history: List[dict],
    ai_config: dict
) -> dict:
    """调用AI决定下一步测试操作"""
    client = openai.OpenAI(
        api_key=ai_config["api_key"],
        base_url=ai_config["api_base_url"]
    )

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

    def _make_messages(include_image: bool) -> list:
        msgs = [{"role": "system", "content": TEST_AGENT_PROMPT}]
        user_text = f"""测试目标: {test_goal}
当前URL: {current_url}
历史操作:
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

    # 尝试使用图片,如果API不支持图片则回退到纯文本
    for include_image in [bool(screenshot_base64), False]:
        try:
            messages = _make_messages(include_image)
            response = client.chat.completions.create(
                model=ai_config["chat_model"],
                messages=messages,
                temperature=0.1,
                max_tokens=500,
            )
            result_text = response.choices[0].message.content.strip()
            result_text = _clean_json_output(result_text)
            return _parse_json_safely(result_text)
        except openai.BadRequestError as e:
            if include_image and "image_url" in str(e):
                continue  # 重试纯文本
            raise


def _call_ai_for_code_analysis(
    error_log: str,
    console_errors: List[str],
    network_errors: List[str],
    project_path: str,
    screenshot_desc: str,
    ai_config: dict
) -> dict:
    """调用AI分析错误并定位代码"""
    client = openai.OpenAI(
        api_key=ai_config["api_key"],
        base_url=ai_config["api_base_url"]
    )

    # 获取项目文件结构
    project_files = _get_project_file_tree(project_path)

    # 读取相关错误日志附近的代码
    relevant_code = _extract_error_context(error_log, console_errors, project_path)

    messages = [
        {"role": "system", "content": CODE_ANALYSIS_PROMPT}
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

    response = client.chat.completions.create(
        model=ai_config["chat_model"],
        messages=messages,
        temperature=0.1,
        max_tokens=2000,
    )

    result_text = response.choices[0].message.content.strip()
    result_text = _clean_json_output(result_text)
    return _parse_json_safely(result_text)


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


async def run_test_task(
    target_url: str,
    project_path: str,
    test_goals: List[str],
    ai_config: dict,
    max_steps: int = 30,
    on_step: Any = None,  # async callback(step_data) called after each step
    stop_event: Any = None,  # asyncio.Event to signal task cancellation
) -> dict:
    """
    执行Web测试任务

    Args:
        target_url: 目标测试网址
        project_path: 本地项目代码路径
        test_goals: 测试目标列表
        ai_config: AI配置
        max_steps: 最大测试步骤数

    Returns:
        测试结果
    """
    if not ai_config or not ai_config.get("api_key"):
        return {"error": "未配置AI模型"}

    if not os.path.isdir(project_path):
        return {"error": f"项目路径不存在: {project_path}"}

    task_id = uuid.uuid4().hex[:16]
    all_steps = []
    all_code_issues = []
    total_errors = 0
    total_screenshots = 0

    running_test_tasks[task_id] = {
        "task_id": task_id,
        "target_url": target_url,
        "status": "running",
        "steps": all_steps,
        "code_issues": all_code_issues,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_path": project_path,
        "stop_event": stop_event or asyncio.Event(),
    }

    browser = BrowserCapture(headless=False)  # 非headless以便观察
    try:
        await browser.start()
        await browser.navigate(target_url)

        # 对每个测试目标执行测试
        for goal_idx, test_goal in enumerate(test_goals):
            # 检查是否已停止
            if running_test_tasks[task_id]["stop_event"].is_set():
                break

            goal_steps = 0
            step_num = len(all_steps) + 1

            while goal_steps < max_steps and step_num <= max_steps:
                # 检查是否已停止
                if running_test_tasks[task_id]["stop_event"].is_set():
                    break

                # 1. 截图
                screenshot = await browser.screenshot()
                if screenshot:
                    total_screenshots += 1

                current_url = await browser.get_url()
                errors = browser.get_errors()

                # 2. 调用AI决定下一步操作
                decision = _call_ai_for_test_step(
                    test_goal=test_goal,
                    current_url=current_url,
                    screenshot_base64=screenshot or "",
                    console_errors=errors["console"],
                    network_errors=errors["network"],
                    history=all_steps[-10:],  # 只给最近10步历史
                    ai_config=ai_config,
                )

                action = decision.get("action", "done")
                target = decision.get("target", "")
                reason = decision.get("reason", "")

                # 3. 执行操作
                success = True
                result = ""
                try:
                    if action == "click":
                        await browser.click(target)
                        result = f"已点击: {target}"
                    elif action == "fill" or action == "type":
                        text = decision.get("text", "")
                        await browser.fill(target, text)
                        result = f"已输入文本到 {target}: {text}"
                    elif action == "navigate":
                        url = decision.get("url", target)
                        await browser.navigate(url)
                        result = f"已导航到: {url}"
                    elif action == "wait":
                        wait_time = decision.get("wait_time", 1000)
                        await browser.wait(wait_time)
                        result = f"等待 {wait_time}ms"
                    elif action == "press":
                        key = decision.get("key", "Enter")
                        await browser.press_key(key)
                        result = f"已按键: {key}"
                    elif action == "assert":
                        is_visible = await browser.is_visible(target)
                        success = is_visible
                        result = f"断言元素 {target} {'可见' if is_visible else '不可见'}"
                    elif action == "scroll":
                        await browser.execute_script("window.scrollBy(0, 500)")
                        result = "已向下滚动"
                    elif action == "done" or action == "complete":
                        result = decision.get("message", "测试完成")
                        success = decision.get("success", True)
                    else:
                        result = f"未知操作: {action}"

                except Exception as e:
                    success = False
                    result = f"操作失败: {str(e)}"

                # 4. 收集错误
                step_errors = browser.get_errors()

                step_record = {
                    "step": step_num,
                    "action": action,
                    "target": target or reason,
                    "result": result,
                    "success": success,
                    "console_errors": step_errors["console"],
                    "network_errors": step_errors["network"],
                }

                all_steps.append(step_record)

                # 实时回调 - 推送当前步骤给前端
                if on_step:
                    try:
                        await on_step({
                            "type": "step",
                            "step": step_num,
                            "action": action,
                            "target": target or reason,
                            "result": result,
                            "success": success,
                            "console_errors": step_errors["console"],
                            "network_errors": step_errors["network"],
                        })
                    except Exception:
                        pass

                step_num += 1
                goal_steps += 1

                # 如果AI判断完成,进入下一个测试目标
                if action in ["done", "complete"]:
                    break

                # 如果有错误,截图并分析代码
                if not success or (step_errors["console"] or step_errors["network"]):
                    total_errors += 1

                    # 如果AI判断任务完成或出错
                    if decision.get("analyze_code", False) or not success:
                        error_log = "\n".join(step_errors["console"] + step_errors["network"])
                        issue_analysis = _call_ai_for_code_analysis(
                            error_log=error_log,
                            console_errors=step_errors["console"],
                            network_errors=step_errors["network"],
                            project_path=project_path,
                            screenshot_desc=result,
                            ai_config=ai_config,
                        )

                        if issue_analysis.get("file_path"):
                            code_issue = {
                                "file_path": issue_analysis.get("file_path", ""),
                                "line_number": issue_analysis.get("line_number", 0),
                                "issue_description": issue_analysis.get("issue_description", ""),
                                "error_log": error_log,
                                "suggested_fix": issue_analysis.get("suggested_fix", ""),
                                "code_snippet": issue_analysis.get("code_snippet"),
                            }
                            all_code_issues.append(code_issue)

                    # 清空错误缓存,继续测试
                    browser.clear_errors()

            # 进入下一个测试目标前等待
            if goal_idx < len(test_goals) - 1:
                await browser.navigate(target_url)  # 重新加载页面

        # 检查是否被用户停止
        if running_test_tasks[task_id]["stop_event"].is_set():
            running_test_tasks[task_id]["status"] = "cancelled"
            running_test_tasks[task_id]["message"] = "测试已停止"
        else:
            running_test_tasks[task_id]["status"] = "completed"
            running_test_tasks[task_id]["message"] = f"测试完成，共 {total_errors} 个错误"

    except Exception as e:
        running_test_tasks[task_id]["status"] = "failed"
        running_test_tasks[task_id]["message"] = f"测试执行失败: {str(e)}"
    finally:
        await browser.close()

    return running_test_tasks[task_id]
