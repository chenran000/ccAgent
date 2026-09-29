"""意图识别分类器 - 自动判断用户意图并路由到对应功能"""
import re


def classify_intent_local(content: str) -> dict:
    """
    基于规则的本地意图分类（快速判断，无需调用AI）

    Args:
        content: 用户输入文本

    Returns:
        包含意图类型和置信度的字典
    """
    content_lower = content.lower()

    # 代码分析类关键词
    code_keywords = [
        "代码", "bug", "错误", "异常", "分析代码", "审查代码",
        "查找bug", "定位问题", "修复", "代码问题", "代码分析",
    ]

    # 测试用例类关键词
    case_keywords = [
        "测试用例", "用例", "测试场景", "测试方案", "边界",
        "测试计划", "回归测试", "生成用例",
    ]

    # 知识库类关键词
    knowledge_keywords = [
        "知识库", "添加知识", "记住", "存档", "保存知识",
        "录入知识", "知识管理", "添加到知识库"
    ]

    # Web 自动化测试类关键词
    web_test_keywords = [
        "测试这个", "测试该", "打开网站", "打开这个", "自动化测试",
        "浏览器测试", "测试页面", "测试系统", "访问", "测试登录",
        "测试注册", "测试功能", "帮我测试", "实际测试",
    ]

    # URL pattern detection
    has_url = bool(re.search(r'https?://', content))

    # 计算各类型匹配得分
    code_score = sum(1 for kw in code_keywords if kw in content_lower)
    case_score = sum(1 for kw in case_keywords if kw in content_lower)
    knowledge_score = sum(1 for kw in knowledge_keywords if kw in content_lower)
    web_test_score = sum(1 for kw in web_test_keywords if kw in content_lower)

    # URL 出现时大幅增加 web_test 权重
    if has_url:
        web_test_score += 3

    max_score = max(code_score, case_score, knowledge_score, web_test_score, 1)

    if web_test_score == max_score and web_test_score > 0:
        return {"intent": "web_test", "confidence": min(web_test_score / 3, 1.0)}
    elif code_score == max_score and code_score > 0:
        return {"intent": "code", "confidence": min(code_score / 3, 1.0)}
    elif case_score == max_score and case_score > 0:
        return {"intent": "case", "confidence": min(case_score / 3, 1.0)}
    elif knowledge_score == max_score and knowledge_score > 0:
        return {"intent": "knowledge", "confidence": min(knowledge_score / 3, 1.0)}
    else:
        # 默认闲聊或无法判断
        return {"intent": "chat", "confidence": 0.5}
