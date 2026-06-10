"""意图识别分类器 - 自动判断用户意图并路由到对应功能"""
import json
import re
import openai
from app.prompts import INTENT_CLASSIFICATION_PROMPT, INTENT_TYPES


def classify_intent(content: str, ai_config: dict = None) -> dict:
    """
    对用户输入进行意图分类，判断应该调用哪个功能模块

    Args:
        content: 用户输入文本
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
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": f"请对以下用户输入进行意图分类：\n\n{content}"}
        ],
        temperature=0.1,
    )

    result_text = response.choices[0].message.content.strip()
    result_text = _clean_json_output(result_text)
    result = _parse_json_safely(result_text)

    intent = _validate_intent(result.get("intent", "chat"))
    confidence = result.get("confidence", 0.0)

    return {
        "intent": intent,
        "confidence": confidence
    }


def classify_intent_local(content: str) -> dict:
    """
    基于规则的本地意图分类（快速判断，无需调用AI）

    Args:
        content: 用户输入文本

    Returns:
        包含意图类型和置信度的字典
    """
    content_lower = content.lower()

    # 投诉类关键词（扩大匹配范围，覆盖更多实际表达）
    complaint_keywords = [
        # 明确投诉意图
        "投诉", "举报", "不满", "抱怨", "生气", "差评", "维权",
        # 服务态度相关
        "态度差", "态度不好", "态度恶劣", "态度", "不耐烦", "爱理不理", "冷",
        # 等待/时效相关
        "排队", "等太", "等了", "等很久", "等半天", "一直等", "慢", "太久",
        # 沟通/服务问题
        "打不通", "没人接", "不解决", "没解决", "不管", "不理", "踢皮球",
        # 其他负面表达
        "骗", "忽悠", "隐瞒", "夸大", "拒绝", "不合理", "不公平", "太差",
        "差劲", "垃圾", "无语", "失望", "烦", "气死", "恶心",
    ]

    # 保单提取类关键词
    extract_keywords = [
        "保单", "保单号", "投保人", "保单号码", "提取", "查一下保单",
        "看看保单", "保单信息", "帮我查保单", "保单多少"
    ]

    # 知识库类关键词
    knowledge_keywords = [
        "知识库", "添加知识", "记住", "存档", "保存知识",
        "录入知识", "知识管理", "添加到知识库"
    ]

    # 计算各类型匹配得分
    complaint_score = sum(1 for kw in complaint_keywords if kw in content_lower)
    extract_score = sum(1 for kw in extract_keywords if kw in content_lower)
    knowledge_score = sum(1 for kw in knowledge_keywords if kw in content_lower)

    max_score = max(complaint_score, extract_score, knowledge_score, 1)

    if complaint_score == max_score and complaint_score > 0:
        return {"intent": "complaint", "confidence": min(complaint_score / 3, 1.0)}
    elif extract_score == max_score and extract_score > 0:
        return {"intent": "extract", "confidence": min(extract_score / 3, 1.0)}
    elif knowledge_score == max_score and knowledge_score > 0:
        return {"intent": "knowledge", "confidence": min(knowledge_score / 3, 1.0)}
    else:
        # 默认闲聊或无法判断
        return {"intent": "chat", "confidence": 0.5}


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
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except Exception:
                pass
        return {"intent": "chat", "confidence": 0.0}


def _validate_intent(intent: str) -> str:
    """校验意图类型是否在预定义枚举内"""
    if intent not in INTENT_TYPES:
        return "chat"
    return intent
