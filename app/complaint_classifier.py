"""投诉工单分类功能模块"""
import json
import re
import openai
from app.prompts import COMPLAINT_CLASSIFICATION_PROMPT, BUSINESS_CATEGORIES, COMPLAINT_REASONS


def classify_complaint(content: str, ai_config: dict = None) -> dict:
    """
    对投诉内容进行进行分类，返回业务分类和投诉原因

    Args:
        content: 投诉文本内容
        ai_config: 用户 AI 配置 {api_key, api_base_url, chat_model}
    """
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    client = openai.OpenAI(
        api_key=ai_config["api_key"],
        base_url=ai_config["api_base_url"]
    )

    response = client.chat.completions.create(
        model=ai_config["chat_model"],
        messages=[
            {"role": "system", "content": COMPLAINT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": f"请对以下投诉内容进行分类：\n\n{content}"}
        ],
        temperature=0.1,
    )

    # 获取并清理返回结果
    result_text = response.choices[0].message.content.strip()
    result_text = _clean_json_output(result_text)

    # 解析 JSON 结果
    result = _parse_json_safely(result_text)

    # 校验分类结果是否在预定义枚举内
    category = _validate_category(result.get("category", "其他"))
    reason_primary = _validate_reason(result.get("reason_primary", "其他"), is_primary=True)
    reason_secondary = _validate_reason(result.get("reason_secondary", "无"), is_primary=False)

    return {
        "category": category,
        "category_confidence": result.get("category_confidence", 0.0),
        "reason_primary": reason_primary,
        "reason_primary_confidence": result.get("reason_primary_confidence", 0.0),
        "reason_secondary": reason_secondary,
        "reason_secondary_confidence": result.get("reason_secondary_confidence", 0.0)
    }


def _clean_json_output(text: str) -> str:
    """清理 AI 返回结果中的代码块标记"""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _parse_json_safely(text: str) -> dict:
    """安全地解析 JSON，支持容错处理"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试用正则提取 JSON 对象
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except Exception:
                pass

        # 解析失败返回默认值
        return {
            "category": "其他",
            "reason_primary": "其他",
            "reason_secondary": "无"
        }


def _validate_category(category: str) -> str:
    """校验业务分类是否在预定义枚举内"""
    if category not in BUSINESS_CATEGORIES:
        return "其他"
    return category


def _validate_reason(reason: str, is_primary: bool = True) -> str:
    """校验投诉原因是否在预定义枚举内"""
    valid_reasons = COMPLAINT_REASONS + ["无"]
    if reason not in valid_reasons:
        return "其他" if is_primary else "无"
    return reason
