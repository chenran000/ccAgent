"""工作区智能体循环(ZCode 式:LLM 自主决定调用工具直至给出结论)

- OpenAI function calling 协议;每次工具执行向前端推一条 step 事件(复用现有渲染)
- 历史上下文:该会话最近 10 轮对话 + 工作区信息注入系统提示
- 上下文压缩:消息总长超过阈值时,把最早的工具结果替换为占位(防止上下文爆炸)
- 写文件需人工确认:yield confirm_request 事件展示 diff,等待 /agent/confirm 裁决
"""
import difflib
import json
import logging
import os
import threading
from typing import AsyncGenerator, Awaitable, Callable, Dict, List, Optional

import asyncio

from app.agent_tools import TOOLS_SPEC, execute_tool
from app.llm import build_plain_client

logger = logging.getLogger(__name__)

MAX_TURNS = 25
MAX_TOOL_RESULTS_IN_CONTEXT = 12  # 上下文中保留的最近工具结果条数
CONFIRM_TIMEOUT_SECONDS = 300     # 等待用户裁决写文件的最长时间
MAX_DIFF_LINES = 160              # 推给前端的 diff 最大行数
HISTORY_COMPACT_CHARS = 24000     # 历史对话超过该字符数时触发 LLM 摘要压缩
HISTORY_KEEP_RECENT = 4           # 摘要压缩时保留的最近对话轮数
HISTORY_WINDOW = 10               # 进上下文的历史轮数窗口
# 单轮 LLM 请求超时(秒);网络挂起时由客户端超时兜底,而不是无限阻塞 SSE 流
LLM_CALL_TIMEOUT = float(os.getenv("TESTASSISTANT_LLM_TIMEOUT", "300"))
# 单轮输出上限( tokens );write_file 语义是"完整给出修改后的文件内容",
# 过低的上限会让长文件被静默截断后直接覆盖原文件,必须显式给足
AGENT_MAX_TOKENS = int(os.getenv("TESTASSISTANT_AGENT_MAX_TOKENS", "8192"))

SYSTEM_PROMPT = """你是 TestAssistant AI,一个运行在用户本机的桌面编程智能体,当前打开了用户的项目工作区。

当前工作区路径: {workspace}

你的能力:通过工具查看项目结构、读文件、搜索代码、修改文件、执行命令、读写项目记忆、检索用户上传的编码规范。

【项目记忆(跨会话持久的项目事实)】
{memory}

你的专长:代码分析、Bug 定位与修复、测试用例设计、代码规范检查(硬编码密钥/危险函数/坏味道等)。

工作守则:
1. 先观察再行动:回答项目相关问题前,先用 list_tree/search_code/read_file 收集事实,不要凭空猜测
2. 修改代码前先读目标文件;每次修改说明改了什么、为什么
3. 结论必须基于工具返回的真实内容,引用文件路径和行号作为证据
4. 检查类任务要系统性覆盖:先看结构,再按目录/文件逐一检查,汇总成分级清单
5. 涉及规范的问题先 search_standards 检索用户的规范库;重要事实(技术栈/约定/用户偏好)用 save_project_memory 记住
6. 用简洁中文回答;任务完成后给出总结
7. 回答排版用简洁 Markdown:要点用短列表,代码引用用代码块并标注文件路径;
   不要把文件内容整段粘贴进回答,只引用说明结论所需的关键片段
"""


def _build_messages(history: List[dict], user_message: str, workspace: str) -> List[dict]:
    from app.memory import read_memory

    messages: List[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(
            workspace=workspace, memory=read_memory(workspace) or "(暂无,可通过 save_project_memory 记录)")}
    ]
    for conv in history[-HISTORY_WINDOW:]:
        messages.append({"role": "user", "content": conv["user"]})
        if conv.get("assistant"):
            messages.append({"role": "assistant", "content": conv["assistant"]})
    messages.append({"role": "user", "content": user_message})
    return messages


SUMMARY_PROMPT = """把以下多轮对话压缩成一份要点摘要,供智能体在后续对话中延续上下文。保留:
用户的目标与约束、已确认的事实(文件路径/结论/决定)、未完成的事项。不保留寒暄与重复内容,直接输出摘要正文。"""


def _history_chars(history: List[dict]) -> int:
    return sum(len(c.get("user") or "") + len(c.get("assistant") or "") for c in history)


def _summarize_history_sync(client, model: str, history: List[dict]) -> List[dict]:
    """把较早的轮次交给 LLM 压缩成一条摘要消息,保留最近 HISTORY_KEEP_RECENT 轮原文"""
    old, recent = history[:-HISTORY_KEEP_RECENT], history[-HISTORY_KEEP_RECENT:]
    transcript = "\n\n".join(
        f"用户: {c.get('user') or ''}\n助手: {(c.get('assistant') or '')[:800]}" for c in old)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": transcript[:16000]},
        ],
        temperature=0.2, max_tokens=800,
    )
    summary = (resp.choices[0].message.content or "").strip()
    if not summary:
        raise ValueError("空摘要")
    return [{"user": f"[早前对话摘要(系统自动压缩)]\n{summary}", "assistant": ""}] + recent


async def _compact_history(client, model: str, history: List[dict]) -> List[dict]:
    """长会话历史压缩:超出阈值用 LLM 摘要,失败则退化为只保留最近几轮"""
    if _history_chars(history) <= HISTORY_COMPACT_CHARS:
        return history
    try:
        return await asyncio.to_thread(_summarize_history_sync, client, model, history)
    except Exception as e:
        logger.warning("历史摘要压缩失败,退化为截断: %s", e)
        return history[-HISTORY_KEEP_RECENT:]


def _compact(messages: List[dict]) -> List[dict]:
    """上下文压缩:保留 system/首条用户/最近 MAX_TOOL_RESULTS_IN_CONTEXT 条工具结果,
    其余工具结果替换为占位符(对齐 ZCode compact 思路的轻量版)"""
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if len(tool_indices) <= MAX_TOOL_RESULTS_IN_CONTEXT:
        return messages
    keep = set(tool_indices[-MAX_TOOL_RESULTS_IN_CONTEXT:])
    out = []
    for i, m in enumerate(messages):
        if m.get("role") == "tool" and i not in keep:
            m = dict(m, content="(早期工具结果已省略)")
        out.append(m)
    return out


def _summarize_args(args: dict) -> str:
    for key in ("path", "command", "query"):
        if args.get(key):
            return str(args[key])[:80]
    return json.dumps(args, ensure_ascii=False)[:80]


def _build_write_diff(workspace: str, path: str, new_content: str) -> str:
    """计算 write_file 将产生的统一 diff(路径围栏外返回提示文本)"""
    from app.agent_tools import _resolve

    try:
        abs_path = _resolve(path)
    except Exception:
        return "(路径无效)"
    rel = os.path.relpath(abs_path, workspace) if abs_path.startswith(workspace) else path
    old_content = ""
    is_new = not os.path.exists(abs_path)
    if not is_new:
        try:
            old_content = open(abs_path, encoding="utf-8", errors="replace").read()
        except Exception:
            old_content = ""
    diff = difflib.unified_diff(
        old_content.splitlines(), new_content.splitlines(),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="",
    )
    lines = list(diff)
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"...(diff 截断,共 {len(lines)} 行变更)"]
    header = f"新建文件 {rel}" if is_new else f"修改 {rel}"
    return header + "\n" + "\n".join(lines)


async def stream_agent(
    workspace: str,
    user_message: str,
    history: List[dict],
    ai_config: dict,
    session_id: str,
    confirm_hook: Optional[Callable[[str], Awaitable[bool]]] = None,
) -> AsyncGenerator[dict, None]:
    """运行智能体循环,yield SSE 事件字典(meta/step/confirm_request/chunk/done/error)

    confirm_hook(change_id) -> bool:write_file 前等待用户裁决;未提供时视为直接放行。
    """
    yield {"type": "meta", "intent": "agent", "session_id": session_id}

    if not (ai_config or {}).get("api_key"):
        yield {"type": "error", "message": "未配置AI模型,请先到模型管理配置"}
        return

    client = build_plain_client(ai_config, timeout=LLM_CALL_TIMEOUT)
    model = ai_config["chat_model"]
    history = await _compact_history(client, model, history)
    messages = _build_messages(history, user_message, workspace)
    written_files: List[str] = []  # 本轮成功写入的文件(相对路径),供修复后自动复查

    try:
        for turn in range(1, MAX_TURNS + 1):
            # 轮次心跳:前端对未知事件类型安全忽略;保证工具/LLM 长耗时期间连接上有事件流动
            yield {"type": "turn", "step": turn, "max_turns": MAX_TURNS}
            messages = _compact(messages)

            # 真流式:子线程执行 stream 请求,增量经线程安全队列桥接回事件循环;
            # 内容增量即时推 chunk(用户实时看到输出),工具调用增量按 index 拼装
            aq: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _run_stream():
                try:
                    stream = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=TOOLS_SPEC,
                        temperature=0.3,
                        max_tokens=AGENT_MAX_TOKENS,
                        stream=True,
                    )
                    for event in stream:
                        loop.call_soon_threadsafe(aq.put_nowait, ("delta", event))
                    loop.call_soon_threadsafe(aq.put_nowait, ("end", None))
                except Exception as e:  # noqa: BLE001 - 异常经队列交回事件循环统一处理
                    loop.call_soon_threadsafe(aq.put_nowait, ("error", e))

            threading.Thread(target=_run_stream, daemon=True).start()

            content_parts: List[str] = []
            tool_acc: Dict[int, dict] = {}
            stream_error: Optional[Exception] = None
            got_delta = False
            finish_reason = ""
            while True:
                kind, payload = await aq.get()
                if kind == "delta":
                    got_delta = True
                    choice = payload.choices[0] if payload.choices else None
                    if choice is None:
                        continue
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta
                    if delta and delta.content:
                        content_parts.append(delta.content)
                        yield {"type": "chunk", "content": delta.content}
                    for tc in (delta.tool_calls or []) if delta else []:
                        idx = tc.index if tc.index is not None else len(tool_acc)
                        acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            acc["id"] = tc.id
                        if tc.function and tc.function.name:
                            acc["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            acc["arguments"] += tc.function.arguments
                elif kind == "error":
                    stream_error = payload
                    break
                else:
                    break

            if stream_error is not None and not got_delta:
                # 流式请求本身失败(端点不支持 stream+tools 等):回退非流式,保持可用性
                logger.warning("流式请求失败,回退非流式: %s", stream_error)
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model,
                    messages=messages,
                    tools=TOOLS_SPEC,
                    temperature=0.3,
                    max_tokens=AGENT_MAX_TOKENS,
                )
                message = response.choices[0].message
                answer = (message.content or "").strip()
                tool_calls_list = [
                    {"id": t.id, "type": "function",
                     "function": {"name": t.function.name, "arguments": t.function.arguments}}
                    for t in (getattr(message, "tool_calls", None) or [])
                ]
            else:
                if stream_error is not None:
                    raise stream_error
                if finish_reason == "length":
                    logger.warning("第 %d 轮输出触及 max_tokens 上限,长内容可能被截断", turn)
                answer = "".join(content_parts)
                tool_calls_list = [
                    {
                        "id": tool_acc[idx]["id"] or f"call_{turn}_{idx}",
                        "type": "function",
                        "function": {
                            "name": tool_acc[idx]["name"],
                            "arguments": tool_acc[idx]["arguments"] or "{}",
                        },
                    }
                    for idx in sorted(tool_acc)
                ]

            if not tool_calls_list:
                # 最终回答已在流式中按增量推送,这里只发终态事件,由路由层统一补发 done 并落库
                yield {"type": "answer", "data": {"answer": answer.strip(), "agent": True, "turns": turn,
                                                  "written_files": written_files}}
                return

            # 追加助手消息(含工具调用意图)
            messages.append({"role": "assistant", "content": answer, "tool_calls": tool_calls_list})

            for tc in tool_calls_list:
                tc_id = tc["id"]
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    # 参数非法(常见于输出被截断):不执行,回传错误让模型重新给全参数,
                    # 防止 write_file 以空 content 覆盖真实文件
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
                        "content": "工具参数不是合法 JSON(可能被截断),请重新调用该工具并给全参数。",
                    })
                    yield {"type": "step", "step": turn, "action": f"{name}(参数无效)",
                           "target": str(raw_args)[:80], "result": "参数不是合法 JSON,已跳过执行",
                           "success": False, "console_errors": [], "network_errors": []}
                    continue

                # 写文件/执行命令需用户确认:展示 diff 或命令,等待 /agent/confirm 裁决
                if name == "write_file" and confirm_hook is not None:
                    change_id = f"chg-{turn}-{tc_id[-6:]}"
                    diff = _build_write_diff(workspace, args.get("path", ""), args.get("content", ""))
                    yield {"type": "confirm_request", "change_id": change_id, "kind": "write",
                           "path": args.get("path", ""), "diff": diff}
                    approved = await confirm_hook(change_id)
                    if not approved:
                        messages.append({
                            "role": "tool", "tool_call_id": tc_id,
                            "content": "用户拒绝了这次修改。请勿再次提交相同修改,继续其他工作或调整方案。",
                        })
                        yield {"type": "step", "step": turn, "action": "write_file(已拒绝)",
                               "target": _summarize_args(args), "result": "用户拒绝了该修改",
                               "success": False, "console_errors": [], "network_errors": []}
                        continue
                elif name == "run_command" and confirm_hook is not None:
                    change_id = f"cmd-{turn}-{tc_id[-6:]}"
                    cmd_timeout = int(args.get("timeout", 60) or 60)
                    yield {"type": "confirm_request", "change_id": change_id, "kind": "command",
                           "path": args.get("command", ""),
                           "diff": f"工作目录: {workspace}\n超时: {cmd_timeout}s"}
                    approved = await confirm_hook(change_id)
                    if not approved:
                        messages.append({
                            "role": "tool", "tool_call_id": tc_id,
                            "content": "用户拒绝执行该命令。请勿再次提交相同命令,改用其他方案。",
                        })
                        yield {"type": "step", "step": turn, "action": "run_command(已拒绝)",
                               "target": _summarize_args(args), "result": "用户拒绝了该命令",
                               "success": False, "console_errors": [], "network_errors": []}
                        continue

                result = await asyncio.to_thread(execute_tool, name, args)

                if name == "write_file" and result.get("success"):
                    try:
                        from app.agent_tools import _resolve
                        abs_p = _resolve(args.get("path", ""))
                        written_files.append(os.path.relpath(abs_p, workspace).replace(os.sep, "/"))
                    except Exception:
                        pass
                preview = result["output"][:300]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result["output"],
                })
                yield {
                    "type": "step",
                    "step": turn,
                    "action": name,
                    "target": _summarize_args(args),
                    "result": preview,
                    "success": result["success"],
                    "console_errors": [],
                    "network_errors": [],
                }

        yield {"type": "error", "message": f"智能体达到最大轮次({MAX_TURNS}),已停止"}
    except Exception as e:
        logger.exception("智能体循环异常")
        yield {"type": "error", "message": f"智能体执行失败: {e}"}
