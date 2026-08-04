"""数据模型定义模块"""
from typing import List, Optional
from pydantic import BaseModel

# ========== 认证相关模型 ==========

class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class AuthResponse(BaseModel):
    token: str
    username: str
    message: str

class UserInfo(BaseModel):
    id: int
    username: str

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

# ========== 代码分析相关模型 ==========

class CodeAnalysisRequest(BaseModel):
    code: str
    session_id: Optional[str] = None

class CodeAnalysisResponse(BaseModel):
    intent: str
    confidence: float
    module: str
    data: dict
    message: str
    session_id: str = ""

# 测试用例生成相关模型
class TestCaseRequest(BaseModel):
    feature_description: str
    session_id: Optional[str] = None

class TestCaseResponse(BaseModel):
    intent: str
    confidence: float
    module: str
    data: dict
    message: str
    session_id: str = ""

# 文件管理相关模型
class FileInfo(BaseModel):
    """文件信息"""
    id: int
    original_filename: str
    file_type: str
    file_size: int
    created_at: str
    extracted_text_preview: str

class FileUploadResponse(BaseModel):
    """文件上传响应"""
    id: int
    original_filename: str
    file_type: str
    file_size: int
    message: str

class FileReadResponse(BaseModel):
    """文件读取响应"""
    id: int
    original_filename: str
    extracted_text: str

# 知识库相关模型
class KnowledgeDoc(BaseModel):
    id: str
    content: str
    metadata: dict = {}

class AddKnowledgeRequest(BaseModel):
    content: str
    metadata: dict = {}

class SearchRequest(BaseModel):
    query: str
    top_k: int = 3

class SearchResponse(BaseModel):
    results: List[dict]

class KnowledgeStatsResponse(BaseModel):
    total_docs: int
    index_ready: bool

# ========== 统一对话入口相关模型 ==========

class ChatRequest(BaseModel):
    content: str
    use_rag: bool = False
    session_id: Optional[str] = None
    file_id: Optional[int] = None
    browser_url: Optional[str] = None  # 浏览器面板当前打开的URL

class IntentResult(BaseModel):
    intent: str           # code / case / knowledge / chat
    confidence: float

class ChatResponse(BaseModel):
    intent: str           # 识别的意图
    confidence: float     # 意图识别置信度
    module: str           # 实际处理的模块 (code/case/knowledge/chat)
    data: dict            # 模块返回的结果数据
    message: str          # 用户友好的提示信息
    session_id: str = ""  # 会话ID

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

class ModelGroup(BaseModel):
    """模型分组"""
    label: str
    models: List[ModelConfigInfo]

class ModelListResponse(BaseModel):
    """模型列表响应"""
    builtin: List[ModelConfigInfo]
    custom: List[ModelConfigInfo]

class AddModelRequest(BaseModel):
    """添加模型配置请求"""
    platform: str
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

# ========== Web 测试 Agent 相关模型 ==========

class TestTaskRequest(BaseModel):
    """Web测试任务请求"""
    target_url: str  # 目标测试网址
    project_path: str  # 本地项目代码路径
    test_goals: List[str]  # 测试目标列表，如["测试登录功能", "测试搜索框"]
    max_steps: int = 30  # 最大测试步骤数

class TestRequest(BaseModel):
    """流式测试请求"""
    content: str  # 用户输入的测试描述，包含URL
    browser_url: Optional[str] = None  # 浏览器面板当前打开的URL

class TestStep(BaseModel):
    """测试步骤"""
    step: int
    action: str  # click/type/wait/navigate/assert 等
    target: str  # 操作目标描述
    result: str  # 执行结果
    success: bool  # 该步骤是否成功
    screenshot: Optional[str] = None  # 截图(base64)
    console_errors: List[str] = []  # Console错误
    network_errors: List[str] = []  # Network错误

class CodeIssue(BaseModel):
    """代码问题定位"""
    file_path: str  # 问题所在文件
    line_number: int  # 问题行号
    issue_description: str  # 问题描述
    error_log: str  # 相关错误日志
    suggested_fix: str  # 建议修复方案
    code_snippet: Optional[str] = None  # 原始代码片段

class TestTaskResponse(BaseModel):
    """测试任务响应"""
    task_id: str
    target_url: str
    status: str  # running/completed/failed/waiting_confirm
    steps: List[TestStep]
    errors_found: int  # 发现的错误数
    screenshots_saved: int  # 保存的截图数
    code_issues: List[CodeIssue] = []  # 代码问题定位
    message: str

class CodeModifyRequest(BaseModel):
    """代码修改确认请求"""
    task_id: str
    issue_index: int
    confirmed: bool  # True=同意修改, False=仅给建议

# ========== 项目文件夹相关模型 ==========

class ProjectFolderInfo(BaseModel):
    """项目文件夹信息"""
    id: int
    folder_name: str
    folder_path: str
    created_at: str
    updated_at: str

class ProjectFolderListResponse(BaseModel):
    folders: List[ProjectFolderInfo]
    total: int

class ProjectFolderCreateRequest(BaseModel):
    folder_name: str

class FileNode(BaseModel):
    """文件树节点"""
    name: str
    path: str
    type: str  # 'file' or 'directory'
    children: Optional[List['FileNode']] = None
    size: int = 0

class FileContentResponse(BaseModel):
    """文件内容响应"""
    name: str
    path: str
    content: str  # 文本内容（代码、文本等）
    content_type: str  # 'code' | 'text' | 'image' | 'json' | 'markdown' | 'binary'
    language: str = ""  # 代码语言（用于高亮）
    is_binary: bool = False
    image_url: str = ""  # 图片的 base64 data URL

FileNode.model_rebuild()
