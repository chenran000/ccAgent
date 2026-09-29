"""配置管理模块"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

# 服务配置
HOST = "0.0.0.0"
PORT = 2222
LOG_LEVEL = "info"
RELOAD = False

# 知识库配置（ChromaDB 持久化目录）
KNOWLEDGE_DIR = project_root / "knowledge_base"

# 数据目录（检查点/登录态等运行时数据）
DATA_DIR = project_root / "data"

# 数据库配置（SQLite 存储用户和对话记录）
DATABASE_URL = f"sqlite:///{project_root / 'data' / 'app.db'}"

# 测试 Agent 检查点数据库（LangGraph 任务状态持久化，服务重启后任务可查询/恢复）
CHECKPOINT_DB_PATH = project_root / "data" / "checkpoints.db"

# JWT 认证配置（留空或占位符时，首次启动自动生成随机密钥并保存到 data/.jwt_secret）
def _load_or_create_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if secret and secret != "your-secret-key-change-in-production":
        return secret
    secret_file = project_root / "data" / ".jwt_secret"
    try:
        if secret_file.exists():
            saved = secret_file.read_text(encoding="utf-8").strip()
            if saved:
                return saved
        import secrets
        generated = secrets.token_urlsafe(48)
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(generated, encoding="utf-8")
        return generated
    except Exception:
        # 文件系统异常时退化为进程级随机密钥（重启后已签发 Token 失效）
        import secrets
        return secrets.token_urlsafe(48)


JWT_SECRET_KEY = _load_or_create_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# CORS 允许的前端来源（逗号分隔，"*" 表示不限制；生产环境应收敛到实际前端地址）
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()] or ["*"]

# Embedding 模型配置（bge-small-zh-v1.5 对中文语义检索支持更好；更换模型后需清空知识库重建）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

# Langfuse 可观测性（三项都配置才启用 LLM 调用追踪）
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "")

# RAG 管线配置（分块 → 阈值过滤 → 重排）
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "500"))            # 分块目标长度（字符）
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))      # 超长句硬切时的重叠
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.3"))  # 检索相关度阈值（cosine 相似度）
RAG_RERANK_ENABLED = os.getenv("RAG_RERANK_ENABLED", "true").lower() in ("1", "true", "yes")
RAG_RERANK_MODEL = os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-base")  # 本地无该模型时自动跳过重排

# Web 测试 Agent 感知配置（默认 DOM 文本感知：结构摘要 + 元素列表，成本约为视觉模式 1/3~1/5，
# 且兼容 DeepSeek 等纯文本模型；开启后每步携带页面截图，可发现布局错乱等视觉类问题）
TEST_AGENT_VISION = os.getenv("TEST_AGENT_VISION", "false").lower() in ("1", "true", "yes")
