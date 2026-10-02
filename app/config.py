"""配置管理模块"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ===== 基目录解析(对齐 ZCode 的"代码与数据分离"模型) =====
# 源码运行: 基目录 = 仓库根,数据随项目目录
# PyInstaller 打包(frozen): 代码在 _internal/,用户数据固定到 ~/.testassistant
# (可用 TESTASSISTANT_STORAGE_DIR 覆盖),升级替换 exe 不影响用户数据
if getattr(sys, "frozen", False):
    base_dir = Path(sys.executable).parent
    storage_root = Path(
        os.getenv("TESTASSISTANT_STORAGE_DIR", "").strip() or Path.home() / ".testassistant"
    )
else:
    base_dir = Path(__file__).parent.parent
    storage_root = base_dir

# 加载 .env(源码模式在仓库根;打包模式在 exe 旁边,可选)
load_dotenv(base_dir / ".env")

# 服务配置(单用户本地版默认只绑回环;容器内通过 HOST=0.0.0.0 覆盖)
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "2222"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
RELOAD = False

# ===== 存储目录(全部位于 storage_root,启动时确保存在) =====
KNOWLEDGE_DIR = storage_root / "knowledge_base"
DATA_DIR = storage_root / "data"
UPLOAD_DIR = storage_root / "uploads"
PROJECT_FOLDERS_DIR = storage_root / "project_uploads"
TEST_PROJECT_DIR = storage_root / "test_project"

for _dir in (KNOWLEDGE_DIR, DATA_DIR, UPLOAD_DIR, PROJECT_FOLDERS_DIR, TEST_PROJECT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# 数据库配置（SQLite 存储用户和对话记录）
DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"

# 测试 Agent 检查点数据库（LangGraph 任务状态持久化，服务重启后任务可查询/恢复）
CHECKPOINT_DB_PATH = DATA_DIR / "checkpoints.db"

# CORS 允许的前端来源（逗号分隔，"*" 表示不限制；生产环境应收敛到实际前端地址）
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()] or ["*"]

# Embedding 配置(OpenAI 兼容 /v1/embeddings 接口;三项齐备启用知识库向量能力)
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "https://api.openai.com/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Langfuse 可观测性已随依赖瘦身移除(如需追踪,LLM 网关层实现更合适)

# RAG 管线配置（分块 → 阈值过滤;CrossEncoder 重排已随本地模型依赖移除）
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "500"))            # 分块目标长度（字符）
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))      # 超长句硬切时的重叠
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.3"))  # 检索相关度阈值（cosine 相似度）

# Web 测试 Agent 感知配置（默认 DOM 文本感知：结构摘要 + 元素列表，成本约为视觉模式 1/3~1/5，
# 且兼容 DeepSeek 等纯文本模型；开启后每步携带页面截图，可发现布局错乱等视觉类问题）
TEST_AGENT_VISION = os.getenv("TEST_AGENT_VISION", "false").lower() in ("1", "true", "yes")

# 浏览器是否无头运行:打包 exe/服务器环境默认 true;本机开发想观察浏览器过程设为 false
TEST_AGENT_HEADLESS = os.getenv("TEST_AGENT_HEADLESS", "true").lower() in ("1", "true", "yes")
