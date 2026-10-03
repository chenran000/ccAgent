"""数据库模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now())

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    """会话表"""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), default="新会话")
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now())

    user = relationship("User", back_populates="sessions")
    conversations = relationship("Conversation", back_populates="session", cascade="all, delete-orphan")


class ModelConfig(Base):
    """用户模型配置表（支持多平台多模型）"""
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False)  # deepseek, openai, qwen, kimi, zhipu, custom
    api_key = Column(String(255), nullable=False)
    api_base_url = Column(String(255), nullable=False)
    model_name = Column(String(100), nullable=False)
    is_active = Column(Integer, default=1)  # 是否启用
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now())

    user = relationship("User", backref="model_configs")


class UserActiveModel(Base):
    """用户当前使用的模型"""
    __tablename__ = "user_active_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    model_config_id = Column(Integer, ForeignKey("model_configs.id"), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now())

    user = relationship("User", backref="active_model")


class Conversation(Base):
    """对话记录表"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(100), ForeignKey("sessions.session_id"), nullable=True, index=True)
    module = Column(String(50), nullable=False)  # code / case / knowledge / chat
    input_text = Column(Text, nullable=False)
    output_data = Column(Text, nullable=False)  # JSON 字符串
    created_at = Column(DateTime, default=lambda: datetime.now(), index=True)

    session = relationship("Session", back_populates="conversations")


class Document(Base):
    """用户上传的文件表"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)  # 原始文件名
    stored_filename = Column(String(255), nullable=False)  # 存储文件名（UUID）
    file_path = Column(String(500), nullable=False)  # 文件存储路径
    file_type = Column(String(50), nullable=False)  # pdf / txt / ...
    file_size = Column(Integer, nullable=False)  # 文件大小（字节）
    extracted_text = Column(Text, nullable=True)  # 提取的文本内容（用于对话引用）
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now())

    user = relationship("User", backref="documents")
