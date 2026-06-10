"""数据库模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    """会话表"""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), default="新会话")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", backref="model_configs")


class UserActiveModel(Base):
    """用户当前使用的模型"""
    __tablename__ = "user_active_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    model_config_id = Column(Integer, ForeignKey("model_configs.id"), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", backref="active_model")


class Conversation(Base):
    """对话记录表"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(100), ForeignKey("sessions.session_id"), nullable=True, index=True)
    module = Column(String(50), nullable=False)  # extract / complaint / knowledge / chat
    input_text = Column(Text, nullable=False)
    output_data = Column(Text, nullable=False)  # JSON 字符串
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    session = relationship("Session", back_populates="conversations")