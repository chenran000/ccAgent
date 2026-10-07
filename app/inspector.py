"""项目规范检查管线

两层检查(对齐之前定的护城河设计):
1. 规则引擎(确定性,零 token):硬编码密钥/危险函数/调试残留/TODO——零误报秒扫
2. AI 语义审查:分文件调用大模型(带行号上下文),规范文件(知识库 standards 分类)作为评审标准注入

产出: 分级问题清单 + 健康分,持久化到 DATA_DIR/reports/,支持 SSE 实时进度。
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

REPORTS_DIR = DATA_DIR / "reports"

# 参与检查的代码文件后缀(按语言分桶优先级)
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".java", ".go", ".cs",
    ".c", ".cpp", ".h", ".php", ".rb", ".rs", ".sql", ".yaml", ".yml",
    ".json", ".toml", ".ini", ".cfg", ".env", ".md",
}
MAX_FILE_BYTES = 300_000          # 单文件参与检查上限
MAX_AI_FILES = 20                 # AI 语义审查的文件数上限
MAX_AI_FILE_CHARS = 12_000        # 单文件送审的最大字符数
MAX_STANDARDS_CHARS = 3_000       # 注入提示词的规范文本上限

# ========== 规则引擎 ==========

RULES: List[Dict[str, Any]] = [
    {"id": "SECRET_SK_KEY", "severity": "critical", "pattern": r"['\"]sk-[A-Za-z0-9]{16,}['\"]",
     "message": "疑似硬编码的 API 密钥(sk- 前缀)"},
    {"id": "SECRET_AKIA", "severity": "critical", "pattern": r"AKIA[0-9A-Z]{16}",
     "message": "疑似硬编码的 AWS Access Key"},
    {"id": "SECRET_GHP", "severity": "critical", "pattern": r"ghp_[A-Za-z0-9]{30,}",
     "message": "疑似硬编码的 GitHub Token"},
    {"id": "SECRET_PASSWORD", "severity": "high",
     "pattern": r"(?i)(password|passwd|pwd|secret|api_key|apikey)\s*[=:]\s*['\"][^'\"\s]{6,}['\"]",
     "message": "疑似硬编码的口令/密钥赋值"},
    {"id": "PRIVATE_KEY_BLOCK", "severity": "critical", "pattern": r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
     "message": "仓库中包含私钥文件内容"},
    {"id": "DANGEROUS_EVAL", "severity": "high", "pattern": r"(?<![.\w])eval\(", "code_only": True,
     "message": "使用了 eval(),存在代码注入风险"},
    {"id": "DANGEROUS_EXEC", "severity": "high", "pattern": r"(?<![.\w])(os\.system|popen)\(", "code_only": True,
     "message": "使用了 os.system/popen,建议改为 subprocess 并禁用 shell"},
    {"id": "DANGEROUS_PICKLE", "severity": "medium", "pattern": r"pickle\.loads?\(", "code_only": True,
     "message": "pickle 反序列化存在任意代码执行风险"},
    {"id": "SHELL_TRUE", "severity": "medium", "pattern": r"shell\s*=\s*True", "code_only": True,
     "message": "subprocess 使用 shell=True,注意命令注入"},
    {"id": "SQL_FORMAT", "severity": "medium",
     "pattern": r"(?i)(execute|executemany)\(\s*f?['\"][^'\"]*(SELECT|INSERT|UPDATE|DELETE)\s", "code_only": True,
     "message": "疑似 SQL 字符串拼接,存在注入风险,建议参数化查询"},
    {"id": "DEBUG_PRINT", "severity": "low", "pattern": r"(?<![.\w])(print|console\.log)\(", "code_only": True,
     "message": "调试输出残留(print/console.log)"},
    {"id": "TODO_FIXME", "severity": "low", "pattern": r"(TODO|FIXME|HACK|XXX)[:\s]", "code_only": True,
     "message": "未完成的待办标记"},
]

# 生产代码里的误报豁免:测试文件/文档里出现密钥样式的容忍度更高
RULE_SEVERITY_DEMOTE_IN = {"test", "spec", "mock", "example", "docs"}

# code_only 规则只作用于源码文件(文档/配置里出现 TODO/print 属正常)
CODE_ONLY_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".java", ".go",
                  ".c", ".cpp", ".h", ".php", ".rb", ".rs"}

# ========== 自定义规则(用户可在前端增删,持久化到 DATA_DIR/rules.json) ==========

CUSTOM_RULES_PATH = DATA_DIR / "rules.json"
VALID_SEVERITIES = ("critical", "high", "medium", "low")
MAX_CUSTOM_RULES = 50


def load_custom_rules() -> List[dict]:
    """读取自定义规则;单条不合法(缺字段/正则编译失败)直接跳过,不让坏规则拖垮检查"""
    try:
        data = json.loads(CUSTOM_RULES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw = data.get("rules", []) if isinstance(data, dict) else []
    out: List[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "").strip()
        pattern = str(r.get("pattern") or "")
        if not rid or not pattern:
            continue
        try:
            re.compile(pattern)
        except re.error:
            continue
        severity = str(r.get("severity") or "medium").lower()
        out.append({
            "id": rid,
            "severity": severity if severity in VALID_SEVERITIES else "medium",
            "pattern": pattern,
            "message": str(r.get("message") or "").strip() or f"自定义规则 {rid}",
            "code_only": bool(r.get("code_only", False)),
            "custom": True,
        })
    return out


def save_custom_rules(rules: List[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_RULES_PATH.write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")


def get_all_rules() -> List[Dict[str, Any]]:
    """内置规则 + 自定义规则(rule_scan 实际执行的规则集)"""
    return RULES + load_custom_rules()


def rule_scan(workspace: str, only_files: Optional[set] = None) -> List[dict]:
    """对工作区代码文件跑规则引擎,返回问题清单

    only_files: 相对路径集合(增量模式),提供时只扫这些文件
    """
    issues: List[dict] = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _skip_dirs() and not d.startswith(".")]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in CODE_EXTENSIONS:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, workspace).replace(os.sep, "/")
            if only_files is not None and rel not in only_files:
                continue
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                text = Path(full).read_text(encoding="utf-8")
            except Exception:
                continue
            lowered_path = rel.lower()
            src_lines = text.splitlines()
            for rule in get_all_rules():
                if rule.get("code_only") and ext not in CODE_ONLY_EXTS:
                    continue
                for m in re.finditer(rule["pattern"], text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    line_text = src_lines[line_no - 1].strip() if line_no <= len(src_lines) else ""
                    # 注释行豁免(配置/文档里的示例不报)
                    if line_text.startswith(("#", "//", "*", "<!--", "\"")):
                        continue
                    severity = rule["severity"]
                    if any(tag in lowered_path for tag in RULE_SEVERITY_DEMOTE_IN) and severity in ("critical", "high"):
                        severity = "medium"  # 测试/示例/文档里降级
                    issues.append({
                        "rule_id": rule["id"],
                        "severity": severity,
                        "source": "rule",
                        "file": rel,
                        "line": line_no,
                        "message": rule["message"],
                        "evidence": line_text[:200],
                        "suggestion": "",
                    })
    return issues


def _skip_dirs() -> set:
    from app.workspace import IGNORE_DIRS
    return IGNORE_DIRS | {"browsers", "_internal", "node_modules"}


def collect_code_files(workspace: str, only_files: Optional[set] = None) -> List[dict]:
    """收集参与 AI 审查的代码文件(按规则命中数与体积排序,限量)

    only_files: 相对路径集合(增量模式),提供时只收集这些文件
    """
    scored: List[dict] = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _skip_dirs() and not d.startswith(".")]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in {".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".java", ".go"}:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, workspace).replace(os.sep, "/")
            if only_files is not None and rel not in only_files:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            scored.append({"path": full, "rel": rel, "size": size})
    # 优先中等体积的源码文件(过小的工具脚本价值低,过大的先截断)
    scored.sort(key=lambda f: (f["size"] < 500, f["size"]))
    return scored[:MAX_AI_FILES]


# ========== git 增量支持 ==========

def git_changed_files(workspace: str) -> Optional[List[str]]:
    """git 变更文件(相对路径,含未跟踪);非 git 仓库或执行失败返回 None"""
    import subprocess

    try:
        r = subprocess.run(
            ["git", "-C", workspace, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, errors="replace",
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    files = []
    for line in (r.stdout or "").splitlines():
        if len(line) < 4:
            continue
        p = line[3:].strip().strip('"')
        if " -> " in p:
            p = p.split(" -> ", 1)[1]  # 重命名取新路径
        if p:
            files.append(p.replace("\\", "/"))
    return files


def is_git_repo(workspace: str) -> bool:
    return git_changed_files(workspace) is not None


# ========== AI 审查缓存(内容哈希键控,改动即失效) ==========

REVIEW_CACHE_DIR = DATA_DIR / "cache"


def _review_cache_path(workspace: str) -> Path:
    tag = hashlib.md5(workspace.encode()).hexdigest()[:8]
    REVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return REVIEW_CACHE_DIR / f"review_{tag}.json"


def _load_review_cache(workspace: str) -> Dict[str, Any]:
    try:
        return json.loads(_review_cache_path(workspace).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_review_cache(workspace: str, cache: Dict[str, Any]) -> None:
    try:
        _review_cache_path(workspace).write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("审查缓存写入失败(忽略): %s", e)


def ai_review_file_cached(ai_config: dict, workspace: str, rel: str, code: str,
                          standards: str, cache: Dict[str, Any]) -> tuple:
    """带缓存的 AI 审查。键 = 文件内容哈希 + 规范文本哈希 + 模型名;返回 (issues, from_cache)"""
    key = hashlib.sha1(
        f"{hashlib.sha1(code.encode('utf-8', 'ignore')).hexdigest()}"
        f"|{hashlib.sha1(standards.encode('utf-8', 'ignore')).hexdigest()}"
        f"|{(ai_config or {}).get('chat_model', '')}".encode()
    ).hexdigest()
    entry = cache.get(rel)
    if entry and entry.get("key") == key:
        return list(entry.get("issues", [])), True
    issues = ai_review_file(ai_config, rel, code, standards)
    cache[rel] = {"key": key, "issues": issues}
    return issues, False


def load_standards_text(user_id: int) -> str:
    """从知识库取规范文件全文(standards 分类),拼为评审标准上下文"""
    try:
        from app.vector_db import vector_db
        if not vector_db.enabled:
            return ""
        collection = vector_db._get_collection(user_id)
        if collection.count() == 0:
            return ""
        results = collection.get(where={"category": "standards"}, limit=20)
        docs = (results.get("documents") or []) if results else []
        text = "\n\n".join(d for d in docs if d)
        return text[:MAX_STANDARDS_CHARS]
    except Exception as e:
        logger.warning("规范文本加载失败(跳过): %s", e)
        return ""


# ========== AI 语义审查 ==========

REVIEW_SYSTEM_PROMPT = """你是资深代码审查专家。对提供的代码文件做语义级检查,聚焦规则无法覆盖的问题:
逻辑缺陷、边界条件、错误处理缺失、并发隐患、性能问题、安全问题(SQL注入/XSS/反序列化)、坏味道。

{standards_block}

只返回 JSON 数组(可为空),每个元素:
{{"severity": "critical|high|medium|low",
  "line": 行号整数,
  "message": "问题描述(一句话)",
  "evidence": "问题代码原文(从代码中摘录)",
  "suggestion": "修复建议(一句话)"}}
注意:只报告有把握的问题,宁缺毋滥;不要报告纯风格问题。"""


def ai_review_file(ai_config: dict, rel: str, code: str, standards: str) -> List[dict]:
    """单文件 AI 审查,返回问题清单(失败返回空)"""
    from app.llm import create_structured, CodeReview  # 复用现有契约: analysis/issues
    standards_block = f"\n【团队编码规范(评审标准)】\n{standards}\n" if standards else ""
    prompt = f"审查以下文件: {rel}\n```\n{code[:MAX_AI_FILE_CHARS]}\n```"
    try:
        result = create_structured(
            ai_config,
            CodeReview,
            [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT.format(standards_block=standards_block)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
        issues = []
        for item in result.issues or []:
            issues.append({
                "rule_id": "AI_REVIEW",
                "severity": (item.severity or "medium").lower(),
                "source": "ai",
                "file": rel,
                "line": _parse_line(item.line),
                "message": item.description or "",
                "evidence": (item.line or "").strip()[:200],
                "suggestion": item.suggestion or "",
            })
        return issues
    except Exception as e:
        logger.warning("AI 审查 %s 失败: %s", rel, e)
        return []


def _parse_line(raw: Any) -> int:
    m = re.search(r"\d+", str(raw or ""))
    return int(m.group()) if m else 0


# ========== 汇总与持久化 ==========

SEVERITY_DEDUCTIONS = {"critical": 10, "high": 6, "medium": 3, "low": 1}


def health_score(issues: List[dict]) -> int:
    score = 100
    for issue in issues:
        score -= SEVERITY_DEDUCTIONS.get(issue.get("severity", "low"), 1)
    return max(score, 0)


def workspace_report_dir(workspace: str) -> Path:
    tag = hashlib.md5(workspace.encode()).hexdigest()[:8]
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", os.path.basename(workspace))[:30] or "workspace"
    d = REPORTS_DIR / f"{safe}_{tag}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_report(workspace: str, report: dict) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = workspace_report_dir(workspace) / f"report_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def list_reports(workspace: str) -> List[dict]:
    d = workspace_report_dir(workspace)
    reports = []
    for p in sorted(d.glob("report_*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            reports.append({
                "name": p.name,
                "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "score": data.get("score"),
                "total": data.get("total"),
                "by_severity": data.get("by_severity"),
                "ai_files": data.get("ai_files"),
            })
        except Exception:
            continue
    return reports


def load_report(workspace: str, name: str) -> Optional[dict]:
    if not re.fullmatch(r"report_\d{8}_\d{6}\.json", name):
        return None
    path = workspace_report_dir(workspace) / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
