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

# 数据库配置（SQLite 存储用户和对话记录）
DATABASE_URL = f"sqlite:///{project_root / 'data' / 'app.db'}"

# JWT 认证配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
