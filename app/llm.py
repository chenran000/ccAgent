"""统一 LLM 客户端与结构化输出模块

所有大模型调用经由本模块创建客户端:
- build_plain_client: 普通 OpenAI 兼容客户端(流式输出、自由文本场景)
- create_structured: 结构化输出(Instructor),TOOLS → JSON mode → 纯文本三级回退,
  兼容 DeepSeek/通义/Kimi/智谱/自定义等平台对函数调用支持不一的情况
"""
import re
from typing import List, Type, TypeVar

import instructor
import openai
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


# ========== 结构化输出契约(调用方自带系统提示词) ==========

class CodeReviewIssue(BaseModel):
    """代码审查单项问题"""
    type: str = ""
    severity: str = ""
    description: str = ""
    line: str = ""
    suggestion: str = ""


class CodeReview(BaseModel):
    """代码审查结果"""
    analysis: str = ""
    issues: List[CodeReviewIssue] = []


# ========== 客户端构建 ==========

def build_plain_client(ai_config: dict, timeout: float = 300.0) -> openai.OpenAI:
    """构建普通 OpenAI 兼容客户端

    timeout 为单次请求的最长等待秒数,防止网络挂起时无限阻塞调用方(SSE 流/智能体循环)。
    """
    api_key = ai_config.get("api_key") or ""
    base_url = ai_config.get("api_base_url") or _DEFAULT_BASE_URL
    return openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


def create_structured(
    ai_config: dict,
    response_model: Type[T],
    messages: list,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    max_retries: int = 2,
) -> T:
    """调用 LLM 并解析为 response_model 实例

    回退顺序:TOOLS(函数调用) → JSON mode(response_format) → 纯文本正则提取,
    覆盖不支持函数调用 / JSON mode 的自定义端点;格式错误时由 Instructor 自动重试。
    仅 BadRequestError / 校验失败会触发模式回退,鉴权等错误直接抛出。
    """
    client = build_plain_client(ai_config)
    model_name = ai_config["chat_model"]

    for mode in (instructor.Mode.TOOLS, instructor.Mode.JSON):
        try:
            structured = instructor.from_openai(client, mode=mode)
            return structured.chat.completions.create(
                model=model_name,
                messages=messages,
                response_model=response_model,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=max_retries,
            )
        except (openai.BadRequestError, ValidationError, instructor.exceptions.InstructorRetryException):
            continue

    # 最后回退:纯文本 + 正则提取(兼容完全不支持结构化输出的端点)
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return _parse_text_to_model(response.choices[0].message.content or "", response_model)


def _parse_text_to_model(text: str, response_model: Type[T]) -> T:
    """纯文本回退解析:剥代码块标记 → 正则提取 JSON 对象 → Pydantic 校验"""
    candidates = [_strip_code_fence(text)]
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.append(match.group())

    for candidate in candidates:
        try:
            return response_model.model_validate_json(candidate)
        except ValidationError:
            continue

    raise ValueError(f"无法将模型输出解析为 {response_model.__name__}: {text[:200]}")


def _strip_code_fence(text: str) -> str:
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
