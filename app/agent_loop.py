"""工作区智能体循环(ZCode 式:LLM 自主决定调用工具直至给出结论)

- OpenAI function calling 协议;每次工具执行向前端推一条 step 事件(复用现有渲染)
- 历史上下文:该会话最近 10 轮对话 + 工作区信息注入系统提示
- 上下文压缩:消息总长超过阈值时,把最早的工具结果替换为占位(防止上下文爆炸)
"""
import json
import logging
import os
from typing import AsyncGenerator, Dict, List

import asyncio

from app.agent_tools import TOOLS_SPEC, execute_tool
from app.llm import build_plain_client

logger = logging.getLogger(__name__)

MAX_TURNS = 25
MAX_TOOL_RESULTS_IN_CONTEXT = 12  # 上下文中保留的最近工具结果条数

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
"""


def _build_messages(history: List[dict], user_message: str, workspace: str) -> List[dict]:
    from app.memory import read_memory

    messages: List[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(
            workspace=workspace, memory=read_memory(workspace) or "(暂无,可通过 save_project_memory 记录)")}
    ]
    for conv in history[-10:]:
        messages.append({"role": "user", "content": conv["user"]})
        if conv.get("assistant"):
            messages.append({"role": "assistant", "content": conv["assistant"]})
    messages.append({"role": "user", "content": user_message})
    return messages


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


async def stream_agent(
    workspace: str,
    user_message: str,
    history: List[dict],
    ai_config: dict,
    session_id: str,
) -> AsyncGenerator[dict, None]:
    """运行智能体循环,yield SSE 事件字典(meta/step/chunk/done/error)"""
    yield {"type": "meta", "intent": "agent", "session_id": session_id}

    if not (ai_config or {}).get("api_key"):
        yield {"type": "error", "message": "未配置AI模型,请先到模型管理配置"}
        return

    client = build_plain_client(ai_config)
    model = ai_config["chat_model"]
    messages = _build_messages(history, user_message, workspace)

    try:
        for turn in range(1, MAX_TURNS + 1):
            messages = _compact(messages)
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                messages=messages,
                tools=TOOLS_SPEC,
                temperature=0.3,
            )
            choice = response.choices[0]
            message = choice.message

            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                answer = (message.content or "").strip()
                # 分段推送,前端按 chunk 渐进渲染
                for i in range(0, len(answer), 200):
                    yield {"type": "chunk", "content": answer[i:i + 200]}
                # 终态用内部 answer 事件,由路由层统一补发 done 并落库
                yield {"type": "answer", "data": {"answer": answer, "agent": True, "turns": turn}}
                return

            # 追加助手消息(含工具调用意图)
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await asyncio.to_thread(execute_tool, tc.function.name, args)
                preview = result["output"][:300]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result["output"],
                })
                yield {
                    "type": "step",
                    "step": turn,
                    "action": tc.function.name,
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
