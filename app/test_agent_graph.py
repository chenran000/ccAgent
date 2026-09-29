"""Web 测试 Agent 的 LangGraph 状态机实现

用 LangGraph 重写原 test_engine.run_test_task 的核心循环:
- 节点粒度 = 单个测试步骤,每步一次 SQLite checkpoint 持久化
  (替代原内存 dict running_test_tasks,服务重启后任务记录不丢、可恢复)
- interrupt() 实现代码修复的人工确认(替代直接读写内存任务状态)
- 执行过程通过 astream(stream_mode="updates") 流式暴露,替代原 Queue 回调拼接

浏览器(Playwright)是不可序列化的运行时资源,不进入 checkpoint:
- 运行中/等待确认时,浏览器会话保存在进程内注册表
- 进程重启后恢复任务会新开浏览器并重新导航(任务状态不丢,页面会话重建)

注意: ai_config(含 api_key)会随 checkpoint 明文落盘到 data/checkpoints.db,
与 model_configs 表的明文存储策略一致。
"""
import asyncio
import base64
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, TypedDict

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.analysis_service import retrieve_knowledge
from app.browser_capture import BrowserCapture
from app.code_analyzer import analyze_and_fix_code
from app.config import CHECKPOINT_DB_PATH, DATA_DIR
from app.script_generator import (
    RECORDINGS_DIR_NAME,
    build_playwright_script,
    build_test_report,
    stable_selector_from_descriptor,
)
from app.test_engine import _call_ai_for_code_analysis, _call_ai_for_test_step

# ========== 运行时注册表(仅进程内,不持久化) ==========

# task_id → 浏览器会话
_browser_sessions: Dict[str, BrowserCapture] = {}
# 正在本进程执行的任务
active_runs: set = set()
# 收到停止信号、等待在下一个步骤边界生效的任务
stop_requested: set = set()


class TestTaskState(TypedDict, total=False):
    """测试任务状态(全部字段随 checkpoint 持久化)"""
    # 任务元信息
    task_id: str
    user_id: int
    target_url: str
    project_path: str
    test_goals: List[str]
    ai_config: Dict[str, str]
    max_steps: int
    use_vision: bool
    # 登录态档案名(提供时自动保存/复用登录态)
    storage_state: str
    # extract_value 提取的变量(供后续步骤比较)
    extracted: Dict[str, str]
    # 生成的回放脚本相对路径(相对被测项目目录)
    script_path: str
    # 结构化测试报告相对路径
    report_path: str
    # 任务开始时间(UTC ISO)
    started_at: str
    # 执行进度
    goal_index: int
    goal_steps: int
    steps: List[dict]
    code_issues: List[dict]
    fix_cursor: int
    fix_results: List[dict]
    total_errors: int
    total_screenshots: int
    # 运行状态: running / awaiting_fix / cancelled / completed / failed
    status: str
    message: str
    # 上一步决策摘要(供路由与错误分析使用)
    last_step: dict


def new_task_state(
    task_id: str,
    user_id: int,
    target_url: str,
    project_path: str,
    test_goals: List[str],
    ai_config: dict,
    max_steps: int,
    use_vision: bool = False,
    storage_state: str = "",
) -> TestTaskState:
    """创建任务初始状态"""
    return TestTaskState(
        task_id=task_id,
        user_id=user_id,
        target_url=target_url,
        project_path=project_path,
        test_goals=test_goals,
        ai_config=ai_config,
        max_steps=max_steps,
        use_vision=use_vision,
        storage_state=storage_state,
        status="running",
    )


def _storage_state_path(user_id: int, profile: str) -> str:
    """把登录态档案名解析为用户隔离的存储路径;空/非法名返回空串(防目录遍历)"""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "", profile or "")
    if not safe:
        return ""
    return str(DATA_DIR / "storage_states" / str(user_id) / f"{safe}.json")


async def _get_browser(state: TestTaskState) -> BrowserCapture:
    """获取任务的浏览器会话;不存在则新开并导航(覆盖进程重启后恢复的场景)"""
    task_id = state["task_id"]
    browser = _browser_sessions.get(task_id)
    if browser is None:
        browser = BrowserCapture(headless=False)  # 非 headless 以便观察
        storage_path = _storage_state_path(
            state.get("user_id", 0), state.get("storage_state", "")
        )
        await browser.start(storage_state_path=storage_path)
        await browser.navigate(state["target_url"])
        _browser_sessions[task_id] = browser
    return browser


async def _close_browser(task_id: str):
    browser = _browser_sessions.pop(task_id, None)
    if browser:
        try:
            await browser.close()
        except Exception:
            pass


# ========== 节点 ==========

async def init_node(state: TestTaskState) -> dict:
    """任务初始化:校验配置,检索业务知识增强测试目标,初始化进度字段"""
    if not (state.get("ai_config") or {}).get("api_key"):
        return {"status": "failed", "message": "未配置AI模型"}
    if not os.path.isdir(state["project_path"]):
        return {"status": "failed", "message": f"项目路径不存在: {state['project_path']}"}

    goals = list(state.get("test_goals") or [])

    # RAG 增强:检索与测试目标相关的业务知识(超时规则/预期文案等),
    # 拼进每个测试目标,供决策 LLM 作为断言依据;检索失败不阻断任务
    if goals and state.get("user_id"):
        try:
            knowledge_context, _ = await asyncio.to_thread(
                retrieve_knowledge, " ".join(goals), state["user_id"], 3
            )
        except Exception:
            knowledge_context = ""
        if knowledge_context:
            suffix = "\n\n【项目业务知识参考】(断言与预期值优先以下列知识为准)\n" + knowledge_context
            goals = [goal + suffix for goal in goals]

    return {
        "status": "running",
        "message": "",
        "test_goals": goals,
        "goal_index": 0,
        "goal_steps": 0,
        "steps": [],
        "code_issues": [],
        "fix_cursor": 0,
        "fix_results": [],
        "extracted": {},
        "script_path": "",
        "report_path": "",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_errors": 0,
        "total_screenshots": 0,
    }


async def test_step_node(state: TestTaskState) -> dict:
    """单个测试步骤:截图 → AI 决策 → 执行操作 → 收集错误"""
    task_id = state["task_id"]

    # 停止信号在步骤边界生效
    if task_id in stop_requested:
        return {
            "status": "cancelled",
            "message": "测试已停止",
            "steps": state.get("steps", []),
            "code_issues": state.get("code_issues", []),
        }

    try:
        browser = await _get_browser(state)

        last = state.get("last_step") or {}
        goal_index = state.get("goal_index", 0)
        goal_steps = state.get("goal_steps", 0)

        # 上一步宣告目标完成或单目标步数用尽 → 推进到下一个测试目标
        if last.get("action") in ("done", "complete") or goal_steps >= state["max_steps"]:
            goal_index += 1
            goal_steps = 0
            if goal_index >= len(state["test_goals"]):
                await _close_browser(task_id)
                return {
                    "status": "completed",
                    "message": f"测试完成，共 {state.get('total_errors', 0)} 个错误",
                    "steps": state.get("steps", []),
                    "code_issues": state.get("code_issues", []),
                }
            # 进入新目标前重新加载页面
            await browser.navigate(state["target_url"])

        use_vision = bool(state.get("use_vision"))
        # 视觉关闭时不截图,页面认知由结构摘要 + 元素列表承担
        screenshot = await browser.screenshot() if use_vision else None
        current_url = await browser.get_url()
        errors_before = browser.get_errors()
        interactive_elements = await browser.get_interactive_elements()
        page_digest = await browser.get_page_digest()

        decision = await asyncio.to_thread(
            _call_ai_for_test_step,
            test_goal=state["test_goals"][goal_index],
            current_url=current_url,
            console_errors=errors_before["console"],
            network_errors=errors_before["network"],
            history=state.get("steps", [])[-10:],
            ai_config=state["ai_config"],
            interactive_elements=interactive_elements,
            page_digest=page_digest,
            use_vision=use_vision,
            screenshot_base64=screenshot or "",
            extracted=state.get("extracted") or {},
        )

        action = decision.action
        target = decision.target
        reason = decision.reason

        # 重复动作防护:与上一步完全相同且已成功的操作直接跳过,避免原地空转消耗步数
        if (
            last.get("success") is True
            and last.get("action") == action
            and action in ("click", "fill", "type", "navigate", "scroll", "press")
            and last.get("target") == (target or reason)
            and (action not in ("fill", "type") or last.get("text") == decision.text)
            and (action != "navigate" or last.get("url") == (decision.url or target))
        ):
            step_record = {
                "step": len(state.get("steps", [])) + 1,
                "action": action,
                "target": target or reason,
                "result": "与上一步完全相同,已跳过执行",
                "success": True,
                "selector": "",
                "screenshot_path": "",
                "console_errors": [],
                "network_errors": [],
            }
            return {
                "steps": state.get("steps", []) + [step_record],
                "goal_index": goal_index,
                "goal_steps": goal_steps + 1,
                "last_step": dict(last),
            }

        success = True
        result = ""
        extracted_var = None  # (变量名, 值) — extract_value 动作时记录
        try:
            if action == "click":
                await browser.click(target)
                result = f"已点击: {target}"
            elif action in ("fill", "type"):
                text = decision.text
                await browser.fill(target, text)
                result = f"已输入文本到 {target}: {text}"
            elif action == "navigate":
                url = decision.url or target
                await browser.navigate(url)
                result = f"已导航到: {url}"
            elif action == "wait":
                wait_time = decision.wait_time
                await browser.wait(wait_time)
                result = f"等待 {wait_time}ms"
            elif action == "press":
                key = decision.key
                await browser.press_key(key)
                result = f"已按键: {key}"
            elif action == "assert":
                is_visible = await browser.is_visible(target)
                success = is_visible
                result = f"断言元素 {target} {'可见' if is_visible else '不可见'}"
            elif action == "assert_text":
                expected = decision.text
                actual = await browser.get_text(target) if target else await browser.get_text("body")
                success = bool(expected) and expected in actual
                shown = "元素" if target else "页面"
                result = (
                    f"断言{shown}文本包含 '{expected[:40]}': 通过"
                    if success
                    else f"断言{shown}文本包含 '{expected[:40]}': 失败(实际「{actual[:60]}」)"
                )
            elif action == "assert_url":
                fragment = decision.url or target
                actual_url = await browser.get_url()
                success = bool(fragment) and fragment in actual_url
                result = (
                    f"断言URL包含 '{fragment}': 通过"
                    if success
                    else f"断言URL包含 '{fragment}': 实际 {actual_url}"
                )
            elif action == "extract_value":
                actual = await browser.get_text(target)
                var_name = decision.name or "value"
                extracted_var = (var_name, actual)
                result = f"已提取 {target or '页面'} 文本到变量 {var_name}: 「{actual[:40]}」"
            elif action == "scroll":
                await browser.execute_script("window.scrollBy(0, 500)")
                result = "已向下滚动"
            elif action in ("done", "complete"):
                result = decision.message or "测试完成"
                success = decision.success
            else:
                result = f"未知操作: {action}"
        except Exception as e:
            success = False
            result = f"操作失败: {str(e)}"

        # 采集稳定定位描述,供脚本沉淀使用
        selector_hint = ""
        if action in ("click", "fill", "type") and success and target:
            descriptor = await browser.describe_element(target)
            selector_hint = stable_selector_from_descriptor(descriptor)

        # 视觉模式下截图落盘归档,供报告与事后审查
        screenshot_rel_path = ""
        if screenshot:
            try:
                shots_dir = os.path.join(
                    state["project_path"], RECORDINGS_DIR_NAME, f"screenshots_{task_id}"
                )
                os.makedirs(shots_dir, exist_ok=True)
                image_bytes = base64.b64decode(screenshot.split(",", 1)[1])
                image_name = f"step_{len(state.get('steps', [])) + 1}.jpg"
                with open(os.path.join(shots_dir, image_name), "wb") as f:
                    f.write(image_bytes)
                screenshot_rel_path = f"{RECORDINGS_DIR_NAME}/screenshots_{task_id}/{image_name}"
            except Exception:
                screenshot_rel_path = ""

        step_errors = browser.get_errors()
        has_errors = bool(step_errors["console"] or step_errors["network"])

        step_record = {
            "step": len(state.get("steps", [])) + 1,
            "action": action,
            "target": target or reason,
            "result": result,
            "success": success,
            "selector": selector_hint,
            "screenshot_path": screenshot_rel_path,
            "text": decision.text,
            "url": decision.url,
            "key": decision.key,
            "wait_time": decision.wait_time,
            "name": decision.name,
            "console_errors": step_errors["console"],
            "network_errors": step_errors["network"],
        }

        updates = {
            "steps": state.get("steps", []) + [step_record],
            "goal_index": goal_index,
            "goal_steps": goal_steps + 1,
            "total_errors": state.get("total_errors", 0) + (1 if (not success or has_errors) else 0),
            "total_screenshots": state.get("total_screenshots", 0) + (1 if screenshot else 0),
            "last_step": {
                "action": action,
                "target": target or reason,
                "text": decision.text,
                "url": decision.url,
                "success": success,
                "result": result,
                "has_errors": has_errors,
                # AI 要求分析代码,或步骤本身失败时,进入错误分析节点
                "should_analyze": bool(decision.analyze_code) or not success,
            },
        }
        if extracted_var:
            updates["extracted"] = {
                **(state.get("extracted") or {}),
                extracted_var[0]: extracted_var[1],
            }
        return updates

    except Exception as e:
        await _close_browser(task_id)
        return {
            "status": "failed",
            "message": f"测试执行失败: {str(e)}",
            "steps": state.get("steps", []),
            "code_issues": state.get("code_issues", []),
        }


async def analyze_issue_node(state: TestTaskState) -> dict:
    """错误分支:清理错误缓存;需要时调用 AI 定位代码问题"""
    last = state.get("last_step") or {}
    browser = _browser_sessions.get(state["task_id"])
    step_errors = browser.get_errors() if browser else {"console": [], "network": []}

    updates: dict = {"last_step": {**last, "analyzed": True, "has_errors": False}}

    if last.get("should_analyze"):
        error_log = "\n".join(step_errors["console"] + step_errors["network"])
        try:
            issue_analysis = await asyncio.to_thread(
                _call_ai_for_code_analysis,
                error_log=error_log,
                console_errors=step_errors["console"],
                network_errors=step_errors["network"],
                project_path=state["project_path"],
                screenshot_desc=last.get("result", ""),
                ai_config=state["ai_config"],
            )
        except Exception as e:
            await _close_browser(state["task_id"])
            return {
                "status": "failed",
                "message": f"测试执行失败: {str(e)}",
                "steps": state.get("steps", []),
                "code_issues": state.get("code_issues", []),
            }

        if issue_analysis.file_path:
            code_issue = {
                "file_path": issue_analysis.file_path,
                "line_number": issue_analysis.line_number,
                "issue_description": issue_analysis.issue_description,
                "error_log": error_log,
                "suggested_fix": issue_analysis.suggested_fix,
                "code_snippet": issue_analysis.code_snippet,
            }
            updates["code_issues"] = state.get("code_issues", []) + [code_issue]

    if browser:
        browser.clear_errors()
    return updates


async def finalize_node(state: TestTaskState) -> dict:
    """收尾:保存登录态,关闭浏览器,沉淀脚本与报告,确定任务终态"""
    task_id = state["task_id"]
    status = state.get("status")
    message = state.get("message", "")

    if status == "cancelled":
        message = message or "测试已停止"
    elif status == "failed":
        pass  # 保留失败信息
    else:
        status = "completed"
        message = f"测试完成，共 {state.get('total_errors', 0)} 个错误"

    # 登录态沉淀:指定档案时保存 cookies/localStorage,下次测试免重复登录
    browser = _browser_sessions.get(task_id)
    if browser and state.get("storage_state"):
        try:
            await browser.save_storage_state()
        except Exception as e:
            print(f"[登录态] 保存失败: {e}")

    await _close_browser(task_id)
    stop_requested.discard(task_id)

    # 产物沉淀:回放脚本 + 结构化测试报告,写入被测项目 test_recordings/ 目录
    script_path = ""
    report_path = ""
    if state.get("steps") and status in ("completed", "cancelled"):
        recordings_dir = os.path.join(state["project_path"], RECORDINGS_DIR_NAME)
        try:
            os.makedirs(recordings_dir, exist_ok=True)
        except Exception:
            recordings_dir = ""
        if recordings_dir:
            try:
                script = build_playwright_script(
                    task_id=task_id,
                    target_url=state.get("target_url", ""),
                    steps=state.get("steps", []),
                    status=status,
                    message=message,
                    test_goals=state.get("test_goals", []),
                )
                script_file = os.path.join(recordings_dir, f"test_{task_id}.py")
                with open(script_file, "w", encoding="utf-8") as f:
                    f.write(script)
                script_path = f"{RECORDINGS_DIR_NAME}/test_{task_id}.py"
                message = f"{message}；回放脚本已保存至 {script_path}"
            except Exception as e:
                print(f"[脚本沉淀] 生成失败: {e}")
            try:
                duration_seconds = 0.0
                try:
                    started = datetime.fromisoformat(state.get("started_at") or "")
                    duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()
                except Exception:
                    pass
                report = build_test_report(
                    task_id=task_id,
                    target_url=state.get("target_url", ""),
                    test_goals=state.get("test_goals", []),
                    steps=state.get("steps", []),
                    status=status,
                    message=message,
                    code_issues=state.get("code_issues", []),
                    extracted=state.get("extracted") or {},
                    started_at=state.get("started_at", ""),
                    duration_seconds=duration_seconds,
                    script_path=script_path,
                    use_vision=bool(state.get("use_vision")),
                )
                report_file = os.path.join(recordings_dir, f"report_{task_id}.md")
                with open(report_file, "w", encoding="utf-8") as f:
                    f.write(report)
                report_path = f"{RECORDINGS_DIR_NAME}/report_{task_id}.md"
            except Exception as e:
                print(f"[测试报告] 生成失败: {e}")

    updates = {
        "status": status,
        "message": message,
        "script_path": script_path,
        "report_path": report_path,
        "steps": state.get("steps", []),
        "code_issues": state.get("code_issues", []),
    }
    # 测试正常结束且发现代码问题时,进入人工确认修复流程
    if status == "completed" and state.get("code_issues"):
        updates["status"] = "awaiting_fix"
        updates["fix_cursor"] = 0
    return updates


async def await_fix_node(state: TestTaskState) -> dict:
    """人工确认修复:interrupt 暂停,恢复后按用户决定应用或跳过当前问题"""
    issues = state.get("code_issues", [])
    idx = state.get("fix_cursor", 0)
    if idx >= len(issues):
        return {"status": "completed", "message": "测试完成"}

    # 暂停并持久化,等待 /test/code/fix 携带确认结果恢复
    decision = interrupt({
        "type": "fix_confirmation",
        "issue_index": idx,
        "issue": issues[idx],
    })

    confirmed = bool(isinstance(decision, dict) and decision.get("confirmed"))
    fix_record = {"issue_index": idx, "confirmed": confirmed, "success": False, "message": ""}

    if confirmed:
        issue = issues[idx]
        result = await asyncio.to_thread(
            analyze_and_fix_code,
            file_path=issue.get("file_path", ""),
            line_number=issue.get("line_number", 0),
            error_log=issue.get("error_log", ""),
            issue_description=issue.get("issue_description", ""),
            suggested_fix=issue.get("suggested_fix", ""),
            ai_config=state["ai_config"],
            auto_fix=True,
            allowed_root=state.get("project_path", ""),
        )
        fix_record.update(result)
    else:
        fix_record["message"] = "已跳过该问题"

    updates = {
        "fix_cursor": idx + 1,
        "fix_results": state.get("fix_results", []) + [fix_record],
    }
    if idx + 1 >= len(issues):
        all_results = state.get("fix_results", []) + [fix_record]
        applied = sum(1 for r in all_results if r.get("confirmed") and r.get("success"))
        updates["status"] = "completed"
        updates["message"] = f"测试完成，共 {len(issues)} 个代码问题，已应用 {applied} 个修复"
    return updates


# ========== 路由 ==========

def route_after_init(state: TestTaskState) -> str:
    return END if state.get("status") == "failed" else "test_step"


def route_after_step(state: TestTaskState) -> str:
    if state.get("status") in ("cancelled", "failed"):
        return "finalize"

    last = state.get("last_step") or {}
    action = last.get("action", "")
    # 全局步数用尽直接收尾(对应原 step_num 全局上限)
    if len(state.get("steps", [])) >= state["max_steps"]:
        return "finalize"
    # 单目标完成或单目标步数用尽 → 推进目标(在 test_step 内完成)或收尾
    if action in ("done", "complete") or state.get("goal_steps", 0) >= state["max_steps"]:
        if state.get("goal_index", 0) + 1 < len(state["test_goals"]):
            return "test_step"
        return "finalize"
    # 错误分支(只进入一次,analyze_issue 会标记 analyzed)
    if (last.get("has_errors") or last.get("success") is False) and not last.get("analyzed"):
        return "analyze_issue"
    return "test_step"


def route_after_finalize(state: TestTaskState) -> str:
    return "await_fix" if state.get("status") == "awaiting_fix" else END


def route_after_fix(state: TestTaskState) -> str:
    if state.get("fix_cursor", 0) < len(state.get("code_issues", [])):
        return "await_fix"
    return END


# ========== 组图与入口 ==========

def build_test_graph():
    builder = StateGraph(TestTaskState)
    builder.add_node("init", init_node)
    builder.add_node("test_step", test_step_node)
    builder.add_node("analyze_issue", analyze_issue_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("await_fix", await_fix_node)

    builder.set_entry_point("init")
    builder.add_conditional_edges("init", route_after_init, ["test_step", END])
    builder.add_conditional_edges("test_step", route_after_step, ["test_step", "analyze_issue", "finalize"])
    builder.add_edge("analyze_issue", "test_step")
    builder.add_conditional_edges("finalize", route_after_finalize, ["await_fix", END])
    builder.add_conditional_edges("await_fix", route_after_fix, ["await_fix", END])
    return builder


class TestAgentManager:
    """LangGraph 单例管理器:懒加载编译图,AsyncSqliteSaver 持有长连接"""

    def __init__(self):
        self._graph = None
        self._lock = asyncio.Lock()

    async def get_graph(self):
        if self._graph is None:
            async with self._lock:
                if self._graph is None:
                    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    conn = await aiosqlite.connect(str(CHECKPOINT_DB_PATH))
                    saver = AsyncSqliteSaver(conn)
                    await saver.setup()
                    self._graph = build_test_graph().compile(checkpointer=saver)
        return self._graph


test_agent_manager = TestAgentManager()


def make_config(task_id: str) -> dict:
    """task_id 即 LangGraph thread_id,任务状态按其隔离与恢复"""
    return {"configurable": {"thread_id": task_id}}
