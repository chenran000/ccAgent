"""保单信息提取功能模块"""
import json
from typing import Optional
import openai
from app.prompts import SYSTEM_PROMPT, RAG_SYSTEM_PROMPT
from app.vector_db import vector_db


def extract_with_llm(
    content: str,
    use_rag: bool = False,
    user_id: int = None,
    ai_config: dict = None,
) -> dict:
    """
    从保险客服对话文本中提取投保人姓名和保单号

    Args:
        content: 保险客服对话文本
        use_rag: 是否启用 RAG 增强模式
        user_id: 用户 ID（RAG 模式下用于检索该用户的知识库）
        ai_config: 用户 AI 配置 {api_key, api_base_url, chat_model}
    """
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    client = openai.OpenAI(
        api_key=ai_config["api_key"],
        base_url=ai_config["api_base_url"]
    )

    # 准备提示词
    system_prompt = SYSTEM_PROMPT
    user_prompt = f"请从以下文本中提取投保人姓名和保单号：\n\n{content}"

    # 如果启用 RAG，先检索相关知识
    if use_rag and user_id:
        knowledge_context = _retrieve_knowledge(content, user_id, top_k=3)
        if knowledge_context:
            system_prompt = RAG_SYSTEM_PROMPT
            user_prompt = (
                f"请从以下文本中提取投保人姓名和保单号：\n\n"
                f"【保险知识库参考资料】\n{knowledge_context}\n\n"
                f"【待提取文本】\n{content}"
            )

    # 调用大模型进行信息提取
    response = client.chat.completions.create(
        model=ai_config["chat_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
    )

    # 获取并清理返回结果
    result_text = response.choices[0].message.content.strip()
    result_text = _clean_json_output(result_text)

    # 解析 JSON 结果（支持数组格式和单个对象格式）
    raw_result = json.loads(result_text)

    # 统一转换为数组格式
    if isinstance(raw_result, dict):
        raw_result = [raw_result]

    # 提取所有记录
    records = []
    for item in raw_result:
        record = {
            "policyholder_name": item.get("policyholder_name", item.get("投保人姓名", "")),
            "policy_number": item.get("policy_number", item.get("保单号", item.get("保单号码", "")))
        }
        # 过滤掉完全没有有效信息的记录
        if record["policyholder_name"] or record["policy_number"]:
            records.append(record)

    return {
        "records": records,
        "total": len(records)
    }


def _retrieve_knowledge(query: str, user_id: int, top_k: int = 3) -> str:
    """
    从指定用户的知识库中检索相关知识

    Args:
        query: 查询文本
        user_id: 用户 ID
        top_k: 返回最相关的 K 条知识

    Returns:
        拼接后的知识上下文字符串
    """
    results = vector_db.search(query, user_id, top_k)
    if not results:
        return ""

    context_parts = []
    for i, result in enumerate(results, 1):
        context_parts.append(
            f"[参考资料{i}] (相关度: {result['score']:.2f})\n{result['document']['content']}"
        )

    return "\n\n".join(context_parts)


def _clean_json_output(text: str) -> str:
    """清理 AI 返回结果中的代码块标记"""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
