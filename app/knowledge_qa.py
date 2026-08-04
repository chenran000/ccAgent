"""知识库问答功能模块 - 基于用户知识库的RAG问答"""
import openai
from app.prompts import KNOWLEDGE_QA_PROMPT
from app.vector_db import vector_db


def direct_chat(question: str, ai_config: dict) -> str:
    """
    直接调用大模型进行对话（不使用知识库）

    Args:
        question: 用户问题
        ai_config: 用户 AI 配置 {api_key, api_base_url, chat_model}
    """
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    system_prompt = "你是一个专业的软件测试助手。请回答用户的问题，使用你的通用知识。"

    client = openai.OpenAI(api_key=ai_config["api_key"], base_url=ai_config["api_base_url"])
    response = client.chat.completions.create(
        model=ai_config["chat_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()


def answer_with_knowledge(
    question: str,
    user_id: int,
    top_k: int = 3,
    ai_config: dict = None,
) -> dict:
    """
    基于用户知识库进行智能问答

    Args:
        question: 用户问题
        user_id: 用户ID
        top_k: 检索知识数量
        ai_config: 用户 AI 配置 {api_key, api_base_url, chat_model}
    """
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    # 1. 从用户知识库检索相关知识
    knowledge_context = _retrieve_knowledge(question, user_id, top_k)

    # 2. 构建提示词
    if knowledge_context:
        system_prompt = KNOWLEDGE_QA_PROMPT.format(
            knowledge_context=knowledge_context,
            question=question
        )
    else:
        system_prompt = (
            f"你是一个专业的软件测试助手。请回答用户的问题。"
            f"注意：当前知识库为空，请基于你的测试专业知识回答。\n\n"
            f"【用户问题】\n{question}"
        )

    # 3. 调用AI生成回答
    client = openai.OpenAI(api_key=ai_config["api_key"], base_url=ai_config["api_base_url"])
    response = client.chat.completions.create(
        model=ai_config["chat_model"],
        messages=[{"role": "user", "content": system_prompt}],
        temperature=0.3,
    )

    answer = response.choices[0].message.content.strip()

    # 4. 返回回答和引用的知识
    return {
        "answer": answer,
        "references": _get_references(knowledge_context) if knowledge_context else [],
        "has_knowledge": bool(knowledge_context)
    }


def _retrieve_knowledge(query: str, user_id: int, top_k: int = 3) -> str:
    """检索相关知识并拼接"""
    results = vector_db.search(query, user_id, top_k)
    if not results:
        return ""

    context_parts = []
    for i, result in enumerate(results, 1):
        context_parts.append(
            f"[参考资料{i}] (相关度: {result['score']:.2f})\n{result['document']['content']}"
        )

    return "\n\n".join(context_parts)


def _get_references(knowledge_context: str) -> list:
    """从知识上下文中提取引用信息"""
    references = []
    for line in knowledge_context.split("\n"):
        if line.startswith("[参考资料"):
            ref_parts = line.split(")")
            if ref_parts:
                references.append(ref_parts[0] + ")")
    return references
