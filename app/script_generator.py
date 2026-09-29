"""测试轨迹 → 可回放 Playwright 脚本生成器

测试 Agent 执行完成(closed/取消)后,把步骤轨迹转译为独立的
Playwright Python 脚本沉淀到被测项目目录,回归时直接回放,
不再消耗 LLM token。选择器采用录制时采集的稳定定位
(data-testid > id > name > placeholder > aria-label > text)。
"""
import re
from typing import Dict, List, Optional

RECORDINGS_DIR_NAME = "test_recordings"


def stable_selector_from_descriptor(desc: Optional[dict]) -> str:
    """从元素描述中挑选最稳定的定位表达式;无可用属性时返回空串"""
    if not desc:
        return ""
    if desc.get("testid"):
        return f"[data-testid='{desc['testid']}']"
    if desc.get("id"):
        return f"#{desc['id']}"
    if desc.get("name"):
        return f"[name='{desc['name']}']"
    if desc.get("placeholder"):
        return f"[placeholder='{desc['placeholder']}']"
    if desc.get("aria_label"):
        return f"[aria-label='{desc['aria_label']}']"
    if desc.get("text"):
        return f"text={desc['text'][:30]}"
    if desc.get("tag"):
        return desc["tag"]
    return ""


def _safe_var_name(name: str) -> str:
    cleaned = re.sub(r"\W", "_", name or "").strip("_")
    return cleaned or "value"


def _esc(text) -> str:
    """Markdown 表格转义"""
    return str(text).replace("|", "\\|").replace("\r", "").replace("\n", " ")


def build_test_report(
    task_id: str,
    target_url: str,
    test_goals: List[str],
    steps: List[dict],
    status: str,
    message: str,
    code_issues: List[dict],
    extracted: Optional[dict],
    started_at: str,
    duration_seconds: float,
    script_path: str,
    use_vision: bool = False,
) -> str:
    """生成结构化测试报告(Markdown)"""
    total = len(steps)
    passed = sum(1 for s in steps if s.get("success"))
    assert_steps = [s for s in steps if str(s.get("action", "")).startswith("assert")]
    assert_passed = sum(1 for s in assert_steps if s.get("success"))

    lines = [
        f"# 测试报告 — 任务 {task_id}",
        "",
        "## 概览",
        "",
        f"- **测试目标**: {_esc('; '.join(test_goals)) if test_goals else '-'}",
        f"- **被测地址**: {target_url}",
        f"- **执行结果**: {status}({_esc(message)})",
        f"- **开始时间**: {started_at or '-'} / **耗时**: {duration_seconds:.1f}s",
        f"- **感知模式**: {'视觉增强' if use_vision else 'DOM 文本感知'}",
        f"- **步骤统计**: 共 {total} 步,通过 {passed},失败 {total - passed};"
        f"确定性断言 {len(assert_steps)} 项,通过 {assert_passed} 项",
        "",
        "## 执行步骤",
        "",
        "| # | 动作 | 目标 | 结果 | 通过 |",
        "|---|---|---|---|---|",
    ]
    for step in steps:
        if "已跳过执行" in str(step.get("result", "")):
            continue
        target_text = _esc(step.get("target", ""))
        selector = step.get("selector", "")
        if selector:
            target_text += f" `{_esc(selector)}`"
        mark = "✅" if step.get("success") else "❌"
        lines.append(
            f"| {step.get('step', '')} | {_esc(step.get('action', ''))} | {target_text} "
            f"| {_esc(step.get('result', ''))} | {mark} |"
        )

    lines += ["", f"## 代码问题({len(code_issues)})", ""]
    if code_issues:
        for i, issue in enumerate(code_issues, 1):
            lines.append(
                f"{i}. `{_esc(issue.get('file_path', ''))}:{issue.get('line_number', 0)}` — "
                f"{_esc(issue.get('issue_description', ''))}"
            )
    else:
        lines.append("未发现需要定位的代码问题。")

    lines += ["", "## 提取变量", ""]
    if extracted:
        for key, value in extracted.items():
            lines.append(f"- {key} = {_esc(value)}")
    else:
        lines.append("无。")

    lines += [
        "",
        "## 产物",
        "",
        f"- 回放脚本: {script_path or '未生成'}",
        f"- 截图目录: {f'{RECORDINGS_DIR_NAME}/screenshots_{task_id}/' if use_vision else '未启用视觉模式'}",
        "",
    ]
    return "\n".join(lines)


def build_playwright_script(
    task_id: str,
    target_url: str,
    steps: List[dict],
    status: str,
    message: str,
    test_goals: List[str],
) -> str:
    """把步骤轨迹转译为独立可运行的 Playwright Python 脚本文本"""
    goals_text = "; ".join(test_goals) if test_goals else "-"
    lines = [
        '"""',
        f"由 TestAssistant AI 自动生成 — 任务 {task_id}",
        f"测试目标: {goals_text}",
        f"执行结果: {status} ({message})",
        "",
        "回放方式: pip install playwright && playwright install chromium && python 本文件",
        "注意: 选择器为录制时的最佳稳定定位,页面结构变化后可能需要手工调整。",
        '"""',
        "from playwright.sync_api import sync_playwright",
        "",
        f"TARGET_URL = {target_url!r}",
        "",
        "",
        "def run():",
        "    with sync_playwright() as p:",
        "        browser = p.chromium.launch(headless=False)",
        "        page = browser.new_page()",
        "        page.goto(TARGET_URL)",
    ]

    for step in steps:
        if "已跳过执行" in str(step.get("result", "")):
            continue  # 重复防护跳过的步骤不进入回放脚本
        action = step.get("action", "")
        selector = step.get("selector", "")
        num = step.get("step", "?")
        lines.append(f"        # 步骤{num}: {action} {step.get('target', '')} -> {str(step.get('result', ''))[:60]}")

        if action == "navigate":
            url = step.get("url") or step.get("target") or target_url
            lines.append(f"        page.goto({url!r})")
        elif action == "click" and selector:
            lines.append(f"        page.click({selector!r})")
        elif action in ("fill", "type") and selector:
            lines.append(f"        page.fill({selector!r}, {step.get('text', '')!r})")
        elif action == "press":
            lines.append(f"        page.keyboard.press({step.get('key', 'Enter')!r})")
        elif action == "wait":
            lines.append(f"        page.wait_for_timeout({int(step.get('wait_time') or 1000)})")
        elif action == "scroll":
            lines.append("        page.mouse.wheel(0, 500)")
        elif action == "assert_text":
            expected = step.get("text", "")
            if selector:
                lines.append(
                    f"        assert {expected!r} in page.inner_text({selector!r}), "
                    f'"步骤{num} 文本断言失败"'
                )
            else:
                lines.append(
                    f"        assert {expected!r} in page.inner_text('body'), "
                    f'"步骤{num} 文本断言失败"'
                )
        elif action == "assert_url":
            lines.append(
                f"        assert {step.get('url', '')!r} in page.url, "
                f'"步骤{num} URL断言失败"'
            )
        elif action == "extract_value" and selector:
            var = _safe_var_name(step.get("name", ""))
            lines.append(f"        {var} = page.inner_text({selector!r})")
        elif action in ("done", "complete"):
            lines.append(f"        # {step.get('result', '')}")
        else:
            lines.append(f"        # 未转换的动作: {action}")
        lines.append("        page.wait_for_timeout(500)")

    lines += [
        "        browser.close()",
        "",
        "",
        'if __name__ == "__main__":',
        "    run()",
        "",
    ]
    return "\n".join(lines)
