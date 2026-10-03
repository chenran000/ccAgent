"""数据模型定义模块"""
from typing import List, Optional
from pydantic import BaseModel

# ========== 对话历史相关模型 ==========

class ConversationRecord(BaseModel):
    id: int
    session_id: str
    module: str
    input_text: str
    output_data: str
    created_at: str

class ConversationHistoryResponse(BaseModel):
    conversations: List[ConversationRecord]
    total: int

# ========== 会话管理相关模型 ==========

class SessionInfo(BaseModel):
    session_id: str
    name: str
    created_at: str
    updated_at: str

class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]
    total: int

class CreateSessionRequest(BaseModel):
    name: str = "新会话"

class UpdateSessionRequest(BaseModel):
    name: str

# ========== 文件管理相关模型 ==========

class FileInfo(BaseModel):
    """文件信息"""
    id: int
    original_filename: str
    file_type: str
    file_size: int
    created_at: str
    extracted_text_preview: str

# 知识库相关模型
class KnowledgeDoc(BaseModel):
    id: str
    content: str
    metadata: dict = {}

class AddKnowledgeRequest(BaseModel):
    content: str
    metadata: dict = {}

# ========== 统一对话入口相关模型 ==========

class ChatRequest(BaseModel):
    content: str
    use_rag: bool = False
    session_id: Optional[str] = None
    file_id: Optional[int] = None

# ========== AI 模型管理相关模型 ==========

class SupportedPlatform(BaseModel):
    """支持的平台"""
    key: str
    name: str
    icon: str
    default_base_url: str

class ModelConfigInfo(BaseModel):
    """单个模型配置信息"""
    id: int
    platform: str
    platform_name: str
    api_key_masked: str  # 脱敏后的 key
    api_base_url: str
    model_name: str
    is_active: bool
    created_at: str

class ModelListResponse(BaseModel):
    """模型列表响应"""
    builtin: List[ModelConfigInfo]
    custom: List[ModelConfigInfo]

class AddModelRequest(BaseModel):
    """添加模型配置请求"""
    # 前端保存时不传 platform;后端统一按"自定义"处理,故提供默认值
    platform: str = "custom"
    api_key: str
    api_base_url: str
    model_name: str

class UpdateModelRequest(BaseModel):
    """更新模型配置请求"""
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    model_name: Optional[str] = None
    is_active: Optional[int] = None

class TestAIRequest(BaseModel):
    """测试 AI 连接请求"""
    api_key: str
    api_base_url: str
    chat_model: str

class TestAIResponse(BaseModel):
    """测试 AI 连接响应"""
    success: bool
    message: str

class ActiveModelResponse(BaseModel):
    """当前活跃模型响应"""
    model_config_id: Optional[int] = None
    model_name: Optional[str] = None
    platform: Optional[str] = None
    use_default: bool
