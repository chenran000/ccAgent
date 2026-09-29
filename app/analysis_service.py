"""智能分析功能模块 - Bug 枚举分析 / 测试用例生成 / 代码审查

统一走 app.llm.create_structured 结构化输出;枚举字段做软校验,
模型返回超出枚举的值时回落到默认枚举值,避免脏数据入库。
"""
from app.llm import BugAnalysis, CodeReview, TestCaseSet, create_structured
from app.prompts import (
    BUG_ANALYSIS_PROMPT,
    BUG_TYPES,
    CODE_ANALYSIS_PROMPT,
    SCOPE_LEVELS,
    SEVERITY_LEVELS,
    TEST_CASE_PROMPT,
)

_DEFAULT_BUG_TYPE = "逻辑错误"
_DEFAULT_SEVERITY = "一般"
_DEFAULT_SCOPE = "函数级"


def _clamp_enum(value: str, allowed: list, default: str) -> str:
    return value if value in allowed else default


def retrieve_knowledge(query: str, user_id: int, top_k: int = 3) -> tuple[str, list[str]]:
    """从用户知识库检索业务知识;未提供用户/检索失败时优雅返回空

    Returns:
        (知识上下文文本, 引用标记列表)
    """
    if not user_id or user_id <= 0:
        return "", []
    try:
        from app.vector_db import vector_db  # 延迟导入,向量库不可用时优雅降级
        results = vector_db.search(query, user_id, top_k)
    except Exception as e:
        print(f"[RAG] 知识检索失败,跳过增强: {e}")
        return "", []
    if not results:
        return "", []
    parts = []
    references = []
    for i, r in enumerate(results, 1):
        content = (r.get("document") or {}).get("content", "")
        parts.append(f"[知识{i}] (相关度 {r.get('score', 0.0):.2f})\n{content}")
        references.append(f"[知识{i}]")
    return "\n\n".join(parts), references


def analyze_bug(description: str, ai_config: dict) -> dict:
    """Bug 分析:Bug类型/严重程度/影响范围 三维度枚举 + 修复建议"""
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    result = create_structured(
        ai_config,
        BugAnalysis,
        [
            {"role": "system", "content": BUG_ANALYSIS_PROMPT},
            {"role": "user", "content": f"请对以下代码或问题描述进行分析：\n\n{description}"},
        ],
        temperature=0.1,
        max_tokens=1000,
    )
    return {
        "bug_type": _clamp_enum(result.bug_type, BUG_TYPES, _DEFAULT_BUG_TYPE),
        "bug_type_confidence": result.bug_type_confidence,
        "severity": _clamp_enum(result.severity, SEVERITY_LEVELS, _DEFAULT_SEVERITY),
        "severity_confidence": result.severity_confidence,
        "scope": _clamp_enum(result.scope, SCOPE_LEVELS, _DEFAULT_SCOPE),
        "scope_confidence": result.scope_confidence,
        "description": result.description,
        "suggestion": result.suggestion,
    }


def generate_test_cases(feature_description: str, ai_config: dict, user_id: int = 0, top_k: int = 3) -> dict:
    """测试用例生成:覆盖正常/异常/边界/安全四类场景,结合用户知识库的业务知识"""
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    # RAG 增强:检索项目业务知识(超时规则/返回约定等),让用例贴合项目实际
    knowledge_context, references = retrieve_knowledge(feature_description, user_id, top_k)

    user_content = f"请为以下功能生成测试用例：\n\n{feature_description}"
    if knowledge_context:
        user_content += (
            "\n\n【项目业务知识参考】\n"
            f"{knowledge_context}\n"
            "生成用例时,预期结果与业务规则优先遵循上述知识;"
            "如知识与通用常识冲突,以知识为准,并在用例步骤或预期结果中体现。"
        )

    result = create_structured(
        ai_config,
        TestCaseSet,
        [
            {"role": "system", "content": TEST_CASE_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    return {
        "cases": result.cases,
        "total": result.total,
        "used_knowledge": bool(knowledge_context),
        "references": references,
    }


def review_code(code: str, ai_config: dict) -> dict:
    """代码审查:功能/安全/性能/质量 四维度问题清单"""
    if not ai_config or not ai_config.get("api_key"):
        raise ValueError("请在模型管理中配置 AI 模型")

    result = create_structured(
        ai_config,
        CodeReview,
        [
            {"role": "system", "content": CODE_ANALYSIS_PROMPT},
            {"role": "user", "content": f"请审查以下代码：\n\n{code}"},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return {
        "analysis": result.analysis,
        "issues": [issue.model_dump() for issue in result.issues],
    }
