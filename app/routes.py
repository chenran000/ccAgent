"""API 路由定义模块 - TestAssistant AI"""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from fastapi import HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import User, Session as SessionModel, Conversation, ModelConfig, UserActiveModel, Document
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.schemas import (
    LoginRequest, RegisterRequest, AuthResponse, UserInfo,
    ConversationRecord, ConversationHistoryResponse,
    SessionInfo, SessionListResponse, CreateSessionRequest, UpdateSessionRequest,
    ChatRequest, ChatResponse,
    FileUploadResponse, FileReadResponse,
    SearchRequest, SearchResponse, KnowledgeStatsResponse,
    AddKnowledgeRequest,
    SupportedPlatform, ModelConfigInfo, ModelGroup,
    ModelListResponse, AddModelRequest, UpdateModelRequest, TestAIRequest,
    TestAIResponse, ActiveModelResponse,
    FileInfo,
    TestTaskRequest, TestTaskResponse, TestStep,
    CodeIssue, CodeModifyRequest,
    CodeAnalysisRequest, CodeAnalysisResponse,
    TestCaseRequest, TestCaseResponse,
)
from app.intent_classifier import classify_intent_local
from app.knowledge_qa import answer_with_knowledge, direct_chat
from app.vector_db import vector_db
from app.file_parser import parse_file
from app.file_storage import save_file, delete_file as delete_file_from_disk, get_user_upload_dir


def register_routes(app):
    """注册所有 API 路由"""

    # 初始化数据库
    init_db()

    # 前端静态文件路径
    frontend_dir = Path(__file__).parent.parent / "frontend"

    # ==================== 认证接口 ====================

    @app.post("/auth/register", response_model=AuthResponse)
    async def register(request: RegisterRequest, db: Session = Depends(get_db)):
        """用户注册"""
        existing = db.query(User).filter(User.username == request.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        user = User(username=request.username, password_hash=hash_password(request.password))
        db.add(user)
        db.commit()
        db.refresh(user)

        token = create_access_token(user.id, user.username)
        return AuthResponse(token=token, username=user.username, message="注册成功")

    @app.post("/auth/login", response_model=AuthResponse)
    async def login(request: LoginRequest, db: Session = Depends(get_db)):
        """用户登录"""
        user = db.query(User).filter(User.username == request.username).first()
        if not user or not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        token = create_access_token(user.id, user.username)
        return AuthResponse(token=token, username=user.username, message="登录成功")

    @app.get("/auth/me", response_model=UserInfo)
    async def get_me(current_user: User = Depends(get_current_user)):
        """获取当前用户信息"""
        return UserInfo(id=current_user.id, username=current_user.username)

    # ==================== 会话管理接口 ====================

    @app.get("/sessions", response_model=SessionListResponse)
    async def list_sessions(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """获取当前用户的所有会话列表"""
        sessions = db.query(SessionModel).filter(
            SessionModel.user_id == current_user.id
        ).order_by(SessionModel.updated_at.desc()).all()

        return SessionListResponse(
            sessions=[
                SessionInfo(
                    session_id=s.session_id,
                    name=s.name,
                    created_at=s.created_at.isoformat(),
                    updated_at=s.updated_at.isoformat(),
                )
                for s in sessions
            ],
            total=len(sessions),
        )

    @app.post("/sessions", response_model=SessionInfo)
    async def create_session(
        request: CreateSessionRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """创建新会话"""
        session_id = uuid.uuid4().hex[:16]

        session = SessionModel(
            user_id=current_user.id,
            session_id=session_id,
            name=request.name,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        return SessionInfo(
            session_id=session.session_id,
            name=session.name,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        )

    @app.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """删除指定会话及其所有对话记录"""
        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id,
            SessionModel.user_id == current_user.id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        db.delete(session)
        db.commit()
        return {"message": "会话已删除"}

    @app.put("/sessions/{session_id}", response_model=SessionInfo)
    async def update_session(
        session_id: str,
        request: UpdateSessionRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """更新会话名称"""
        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id,
            SessionModel.user_id == current_user.id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        session.name = request.name
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)

        return SessionInfo(
            session_id=session.session_id,
            name=session.name,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        )

    # ==================== AI 模型管理接口 ====================

    _PLATFORM_INFO = {
        "deepseek": {"name": "DeepSeek", "icon": "", "default_base_url": "https://api.deepseek.com/v1"},
        "openai": {"name": "OpenAI", "icon": "🟢", "default_base_url": "https://api.openai.com/v1"},
        "qwen": {"name": "通义千问", "icon": "💎", "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "kimi": {"name": "Kimi", "icon": "", "default_base_url": "https://api.moonshot.cn/v1"},
        "zhipu": {"name": "智谱 AI", "icon": "", "default_base_url": "https://open.bigmodel.cn/api/paas/v4"},
        "custom": {"name": "自定义", "icon": "⚙", "default_base_url": ""},
    }

    def _mask_api_key(key: str) -> str:
        """脱敏 API Key，只显示前 4 位和后 4 位"""
        if not key or len(key) <= 8:
            return "****"
        return key[:4] + "****" + key[-4:]

    def _get_user_ai_config(user_id: int, db: Session) -> dict:
        """获取用户当前使用的 AI 配置"""
        active = db.query(UserActiveModel).filter_by(user_id=user_id).first()

        if active and active.model_config_id:
            mc = db.query(ModelConfig).filter_by(id=active.model_config_id, is_active=1).first()
            if mc:
                return {
                    "api_key": mc.api_key,
                    "api_base_url": mc.api_base_url,
                    "chat_model": mc.model_name,
                }

        return {
            "api_key": "",
            "api_base_url": "",
            "chat_model": "",
        }

    @app.get("/settings/models", response_model=ModelListResponse)
    async def get_model_list(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """获取用户的所有模型配置（按平台分组展示）"""
        configs = db.query(ModelConfig).filter_by(user_id=current_user.id).all()

        builtin = []
        custom = []

        for mc in configs:
            info = ModelConfigInfo(
                id=mc.id,
                platform=mc.platform,
                platform_name=_PLATFORM_INFO.get(mc.platform, {}).get("name", mc.platform),
                api_key_masked=_mask_api_key(mc.api_key),
                api_base_url=mc.api_base_url,
                model_name=mc.model_name,
                is_active=bool(mc.is_active),
                created_at=mc.created_at.isoformat(),
            )
            if mc.platform == "custom":
                custom.append(info)
            else:
                builtin.append(info)

        return ModelListResponse(builtin=builtin, custom=custom)

    @app.get("/settings/platforms", response_model=List[SupportedPlatform])
    async def get_supported_platforms():
        """获取支持的平台列表"""
        platforms = []
        for key, info in _PLATFORM_INFO.items():
            platforms.append(SupportedPlatform(
                key=key,
                name=info["name"],
                icon=info["icon"],
                default_base_url=info["default_base_url"],
            ))
        return platforms

    @app.post("/settings/models")
    async def add_model(
        request: AddModelRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """添加模型配置"""
        mc = ModelConfig(
            user_id=current_user.id,
            platform="custom",
            api_key=request.api_key,
            api_base_url=request.api_base_url,
            model_name=request.model_name,
        )
        db.add(mc)
        db.commit()
        db.refresh(mc)

        active = db.query(UserActiveModel).filter_by(user_id=current_user.id).first()
        if not active:
            active = UserActiveModel(user_id=current_user.id, model_config_id=mc.id)
            db.add(active)
            db.commit()

        return {"message": "模型添加成功", "id": mc.id}

    @app.get("/settings/models/{config_id}")
    async def get_model(
        config_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """获取单个模型配置详情"""
        mc = db.query(ModelConfig).filter_by(id=config_id, user_id=current_user.id).first()
        if not mc:
            raise HTTPException(status_code=404, detail="模型配置不存在")

        return {
            "id": mc.id,
            "platform": mc.platform,
            "platform_name": _PLATFORM_INFO.get(mc.platform, {}).get("name", mc.platform),
            "api_key": mc.api_key,
            "api_base_url": mc.api_base_url,
            "model_name": mc.model_name,
            "is_active": bool(mc.is_active),
            "created_at": mc.created_at.isoformat(),
        }

    @app.put("/settings/models/{config_id}")
    async def update_model(
        config_id: int,
        request: UpdateModelRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """更新模型配置"""
        mc = db.query(ModelConfig).filter_by(id=config_id, user_id=current_user.id).first()
        if not mc:
            raise HTTPException(status_code=404, detail="模型配置不存在")

        if request.api_key is not None:
            mc.api_key = request.api_key
        if request.api_base_url is not None:
            mc.api_base_url = request.api_base_url
        if request.model_name is not None:
            mc.model_name = request.model_name
        if request.is_active is not None:
            mc.is_active = request.is_active
        mc.updated_at = datetime.now(timezone.utc)

        db.commit()
        return {"message": "模型配置已更新"}

    @app.delete("/settings/models/{config_id}")
    async def delete_model(
        config_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """删除模型配置"""
        mc = db.query(ModelConfig).filter_by(id=config_id, user_id=current_user.id).first()
        if not mc:
            raise HTTPException(status_code=404, detail="模型配置不存在")

        active = db.query(UserActiveModel).filter_by(user_id=current_user.id, model_config_id=config_id).first()
        if active:
            db.delete(active)

        db.delete(mc)
        db.commit()
        return {"message": "模型配置已删除"}

    @app.get("/settings/active", response_model=ActiveModelResponse)
    async def get_active_model(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """获取当前使用的模型"""
        active = db.query(UserActiveModel).filter_by(user_id=current_user.id).first()

        if not active or not active.model_config_id:
            return ActiveModelResponse(use_default=True)

        mc = db.query(ModelConfig).filter_by(id=active.model_config_id).first()
        if not mc:
            return ActiveModelResponse(use_default=True)

        return ActiveModelResponse(
            model_config_id=mc.id,
            model_name=mc.model_name,
            platform=mc.platform,
            use_default=False,
        )

    @app.post("/settings/active/{config_id}")
    async def set_active_model(
        config_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """设置当前使用的模型"""
        mc = db.query(ModelConfig).filter_by(id=config_id, user_id=current_user.id).first()
        if not mc:
            raise HTTPException(status_code=404, detail="模型配置不存在")

        active = db.query(UserActiveModel).filter_by(user_id=current_user.id).first()
        if active:
            active.model_config_id = config_id
            active.updated_at = datetime.now(timezone.utc)
        else:
            active = UserActiveModel(user_id=current_user.id, model_config_id=config_id)
            db.add(active)

        db.commit()
        return {"message": "已切换到 " + mc.model_name}

    @app.delete("/settings/active")
    async def reset_active_model(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """取消选择模型"""
        active = db.query(UserActiveModel).filter_by(user_id=current_user.id).first()
        if active:
            active.model_config_id = None
            active.updated_at = datetime.now(timezone.utc)
            db.commit()

        return {"message": "已取消选择模型"}

    @app.post("/settings/ai/test", response_model=TestAIResponse)
    async def test_ai_connection(request: TestAIRequest):
        """测试 AI 连接是否正常"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=request.api_key, base_url=request.api_base_url)
            client.chat.completions.create(
                model=request.chat_model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=10,
                timeout=10,
            )
            return TestAIResponse(success=True, message="连接成功")
        except Exception as e:
            return TestAIResponse(success=False, message=f"连接失败: {str(e)}")

    # ==================== 对话历史接口 ====================

    @app.get("/conversations", response_model=ConversationHistoryResponse)
    async def get_conversations(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
        limit: int = 50,
        offset: int = 0,
        session_id: str = None,
    ):
        """获取当前用户的对话历史，可按会话筛选"""
        query = db.query(Conversation).filter(Conversation.user_id == current_user.id)
        if session_id:
            query = query.filter(Conversation.session_id == session_id)

        total = query.count()
        conversations = query.order_by(Conversation.created_at.asc()).offset(offset).limit(limit).all()

        return ConversationHistoryResponse(
            conversations=[
                ConversationRecord(
                    id=c.id,
                    session_id=c.session_id or "",
                    module=c.module,
                    input_text=c.input_text,
                    output_data=c.output_data,
                    created_at=c.created_at.isoformat()
                )
                for c in conversations
            ],
            total=total,
        )

    @app.delete("/conversations/{conv_id}")
    async def delete_conversation(
        conv_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """删除指定对话记录"""
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="对话记录不存在")

        db.delete(conv)
        db.commit()
        return {"message": "对话记录已删除"}

    # ==================== 文件管理接口 ====================

    @app.post("/files/upload", summary="上传文件")
    async def upload_file(
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """上传文件到服务器，解析文本内容后保存"""
        try:
            if not file.filename:
                raise HTTPException(status_code=400, detail="文件名不能为空")

            file_bytes = await file.read()
            if not file_bytes:
                raise HTTPException(status_code=400, detail="文件不能为空")

            file_info = save_file(file_bytes, file.filename, current_user.id)

            doc = Document(
                user_id=current_user.id,
                original_filename=file_info["original_filename"],
                stored_filename=file_info["stored_filename"],
                file_path=file_info["file_path"],
                file_type=file_info["file_type"],
                file_size=file_info["file_size"],
                extracted_text=file_info["extracted_text"],
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            return {
                "id": doc.id,
                "original_filename": doc.original_filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "message": "文件上传成功",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

    @app.get("/files", summary="获取文件列表")
    async def list_files(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """获取当前用户上传的所有文件"""
        try:
            docs = db.query(Document).filter(
                Document.user_id == current_user.id
            ).order_by(Document.created_at.desc()).all()

            files = []
            for doc in docs:
                preview = ""
                if doc.extracted_text:
                    preview = doc.extracted_text[:200]
                files.append({
                    "id": doc.id,
                    "original_filename": doc.original_filename,
                    "file_type": doc.file_type,
                    "file_size": doc.file_size,
                    "created_at": doc.created_at.isoformat(),
                    "extracted_text_preview": preview,
                })

            return {"files": files, "total": len(files)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")

    @app.get("/files/{file_id}", summary="读取文件内容")
    async def read_file(
        file_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """读取指定文件的内容"""
        try:
            doc = db.query(Document).filter(
                Document.id == file_id,
                Document.user_id == current_user.id
            ).first()

            if not doc:
                raise HTTPException(status_code=404, detail="文件不存在")

            return {
                "id": doc.id,
                "original_filename": doc.original_filename,
                "extracted_text": doc.extracted_text or "",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")

    @app.delete("/files/{file_id}", summary="删除文件")
    async def delete_file(
        file_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """删除指定文件（包括磁盘文件）"""
        try:
            doc = db.query(Document).filter(
                Document.id == file_id,
                Document.user_id == current_user.id
            ).first()

            if not doc:
                raise HTTPException(status_code=404, detail="文件不存在")

            delete_file_from_disk(doc.file_path)

            db.delete(doc)
            db.commit()

            return {"message": "文件删除成功"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"文件删除失败: {str(e)}")

    # ==================== 代码分析接口 ====================

    @app.post("/code/analyze", response_model=CodeAnalysisResponse, summary="代码分析")
    async def analyze_code(
        request: CodeAnalysisRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """对提交的代码进行智能分析，发现潜在问题"""
        try:
            ai_config = _get_user_ai_config(current_user.id, db)
            from openai import OpenAI

            client = OpenAI(api_key=ai_config["api_key"], base_url=ai_config.get("api_base_url", "https://api.openai.com/v1"))
            from app.prompts import CODE_ANALYSIS_PROMPT

            response = client.chat.completions.create(
                model=ai_config["chat_model"],
                messages=[
                    {"role": "system", "content": CODE_ANALYSIS_PROMPT},
                    {"role": "user", "content": request.code}
                ],
                temperature=0.3,
                max_tokens=2000,
            )

            result_text = response.choices[0].message.content
            result = {"analysis": result_text}

            # 保存对话记录
            conversation = Conversation(
                user_id=current_user.id,
                session_id=request.session_id,
                module="code",
                input_text=request.code[:500],
                output_data=json.dumps(result, ensure_ascii=False),
            )
            db.add(conversation)
            _update_session_name(db, request.session_id, f"代码分析: {request.code[:20]}")
            db.commit()

            return CodeAnalysisResponse(
                intent="code",
                confidence=0.9,
                module="code",
                data=result,
                message="代码分析完成",
                session_id=request.session_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"代码分析失败: {str(e)}")

    # ==================== 测试用例生成接口 ====================

    @app.post("/case/generate", response_model=TestCaseResponse, summary="测试用例生成")
    async def generate_test_case(
        request: TestCaseRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """根据功能描述生成完整的测试用例"""
        try:
            ai_config = _get_user_ai_config(current_user.id, db)
            from openai import OpenAI

            client = OpenAI(api_key=ai_config["api_key"], base_url=ai_config.get("api_base_url", "https://api.openai.com/v1"))
            from app.prompts import TEST_CASE_PROMPT

            response = client.chat.completions.create(
                model=ai_config["chat_model"],
                messages=[
                    {"role": "system", "content": TEST_CASE_PROMPT},
                    {"role": "user", "content": request.feature_description}
                ],
                temperature=0.5,
                max_tokens=4000,
            )

            result_text = response.choices[0].message.content
            result = {"cases": result_text, "total": 1}

            # 保存对话记录
            conversation = Conversation(
                user_id=current_user.id,
                session_id=request.session_id,
                module="case",
                input_text=request.feature_description,
                output_data=json.dumps(result, ensure_ascii=False),
            )
            db.add(conversation)
            _update_session_name(db, request.session_id, f"用例生成: {request.feature_description[:20]}")
            db.commit()

            return TestCaseResponse(
                intent="case",
                confidence=0.9,
                module="case",
                data=result,
                message="测试用例生成完成",
                session_id=request.session_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"测试用例生成失败: {str(e)}")

    # ==================== 测试文档库接口 ====================

    @app.post("/knowledge/add", summary="添加测试文档")
    async def add_knowledge(
        request: AddKnowledgeRequest,
        current_user: User = Depends(get_current_user),
    ):
        try:
            doc_id = vector_db.add_document(request.content, current_user.id, request.metadata)
            return {"message": "测试文档添加成功", "doc_id": doc_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"添加测试文档失败: {str(e)}")

    @app.post("/knowledge/search", response_model=SearchResponse, summary="搜索测试文档")
    async def search_knowledge(
        request: SearchRequest,
        current_user: User = Depends(get_current_user),
    ):
        try:
            results = vector_db.search(request.query, current_user.id, request.top_k)
            return SearchResponse(results=[
                {
                    "score": r["score"],
                    "content": r["document"]["content"],
                    "metadata": r["document"]["metadata"]
                }
                for r in results
            ])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"搜索测试文档失败: {str(e)}")

    @app.get("/knowledge/stats", response_model=KnowledgeStatsResponse, summary="测试文档统计")
    async def knowledge_stats(current_user: User = Depends(get_current_user)):
        return vector_db.get_stats(current_user.id)

    @app.delete("/knowledge/{doc_id}", summary="删除测试文档")
    async def delete_knowledge(
        doc_id: str,
        current_user: User = Depends(get_current_user),
    ):
        success = vector_db.delete_document(doc_id, current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
        return {"message": f"文档 {doc_id} 已删除"}

    @app.delete("/knowledge/clear", summary="清空测试文档库")
    async def clear_knowledge(current_user: User = Depends(get_current_user)):
        vector_db.clear_all(current_user.id)
        return {"message": "测试文档库已清空"}

    @app.get("/knowledge/list", summary="获取测试文档列表")
    async def list_knowledge(
        current_user: User = Depends(get_current_user),
    ):
        try:
            collection = vector_db._get_collection(current_user.id)
            all_docs = collection.get()

            knowledge_list = []
            for doc_id, doc_content, metadata in zip(
                all_docs["ids"],
                all_docs["documents"],
                all_docs["metadatas"]
            ):
                knowledge_list.append({
                    "doc_id": doc_id,
                    "content": doc_content,
                    "metadata": metadata or {},
                })

            return {"knowledge": knowledge_list, "total": len(knowledge_list)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取测试文档列表失败: {str(e)}")

    @app.put("/knowledge/{doc_id}", summary="编辑测试文档")
    async def update_knowledge(
        doc_id: str,
        request: AddKnowledgeRequest,
        current_user: User = Depends(get_current_user),
    ):
        try:
            collection = vector_db._get_collection(current_user.id)
            existing = collection.get(ids=[doc_id])
            if not existing["ids"]:
                raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")

            collection.delete(ids=[doc_id])
            collection.add(
                documents=[request.content],
                ids=[doc_id],
                metadatas=[request.metadata if request.metadata else {"updated": "true"}]
            )
            return {"message": "测试文档更新成功", "doc_id": doc_id}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"更新测试文档失败: {str(e)}")

    # ==================== 统一对话入口 ====================

    @app.post("/chat", response_model=ChatResponse, summary="统一对话入口")
    async def chat(
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """
        统一对话接口：自动识别用户意图并路由到对应功能模块
        """
        session_id = request.session_id
        file_id = request.file_id

        # 如果没有提供 session_id，自动创建新会话
        if not session_id:
            session_id = uuid.uuid4().hex[:16]
            session = SessionModel(
                user_id=current_user.id,
                session_id=session_id,
                name="新会话",
            )
            db.add(session)
            db.commit()

        # 处理文件引用
        effective_content = request.content
        file_info = None
        if file_id:
            doc = db.query(Document).filter(
                Document.id == file_id,
                Document.user_id == current_user.id
            ).first()
            if not doc:
                raise HTTPException(status_code=404, detail="引用的文件不存在")
            if not doc.extracted_text:
                raise HTTPException(status_code=400, detail="该文件内容为空，无法读取")
            effective_content = f"【文件内容：{doc.original_filename}】\n{doc.extracted_text}\n\n{request.content}"
            file_info = {
                "id": doc.id,
                "filename": doc.original_filename,
                "file_type": doc.file_type,
            }

        # 1. 意图识别
        intent_result = classify_intent_local(effective_content)
        intent = intent_result["intent"]
        confidence = intent_result["confidence"]

        # 2. 路由
        if intent == "code":
            return await _handle_code_analysis(effective_content, request.content, current_user, db, intent, confidence, session_id, file_info)
        elif intent == "case":
            return await _handle_test_case(effective_content, request.content, current_user, db, intent, confidence, session_id, file_info)
        elif intent == "knowledge":
            return await _handle_knowledge(effective_content, request.content, current_user, db, intent, confidence, session_id, file_info)
        else:
            return await _handle_chat(effective_content, request.content, current_user, db, intent, confidence, session_id, request.use_rag, file_info)

    async def _handle_code_analysis(ai_content, original_content, current_user, db, intent, confidence, session_id, file_info=None):
        """处理代码分析意图"""
        try:
            ai_config = _get_user_ai_config(current_user.id, db)
            from openai import OpenAI

            client = OpenAI(api_key=ai_config["api_key"], base_url=ai_config.get("api_base_url", "https://api.openai.com/v1"))
            from app.prompts import CODE_ANALYSIS_PROMPT

            response = client.chat.completions.create(
                model=ai_config["chat_model"],
                messages=[
                    {"role": "system", "content": CODE_ANALYSIS_PROMPT},
                    {"role": "user", "content": ai_content}
                ],
                temperature=0.3,
                max_tokens=2000,
            )

            result = {"analysis": response.choices[0].message.content}

            input_text = f"[引用文件] {original_content}" if file_info else original_content
            conversation = Conversation(
                user_id=current_user.id,
                session_id=session_id,
                module="code",
                input_text=input_text,
                output_data=json.dumps(result, ensure_ascii=False),
            )
            db.add(conversation)
            _update_session_name(db, session_id, input_text)
            db.commit()

            return ChatResponse(
                intent=intent,
                confidence=confidence,
                module="code",
                data=result,
                message="代码分析完成",
                session_id=session_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"代码分析失败: {str(e)}")

    async def _handle_test_case(ai_content, original_content, current_user, db, intent, confidence, session_id, file_info=None):
        """处理测试用例生成意图"""
        try:
            ai_config = _get_user_ai_config(current_user.id, db)
            from openai import OpenAI

            client = OpenAI(api_key=ai_config["api_key"], base_url=ai_config.get("api_base_url", "https://api.openai.com/v1"))
            from app.prompts import TEST_CASE_PROMPT

            response = client.chat.completions.create(
                model=ai_config["chat_model"],
                messages=[
                    {"role": "system", "content": TEST_CASE_PROMPT},
                    {"role": "user", "content": ai_content}
                ],
                temperature=0.5,
                max_tokens=4000,
            )

            result = {"cases": response.choices[0].message.content, "total": 1}

            input_text = f"[引用文件] {original_content}" if file_info else original_content
            conversation = Conversation(
                user_id=current_user.id,
                session_id=session_id,
                module="case",
                input_text=input_text,
                output_data=json.dumps(result, ensure_ascii=False),
            )
            db.add(conversation)
            _update_session_name(db, session_id, input_text)
            db.commit()

            return ChatResponse(
                intent=intent,
                confidence=confidence,
                module="case",
                data=result,
                message="测试用例生成完成",
                session_id=session_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"测试用例生成失败: {str(e)}")

    async def _handle_knowledge(ai_content, original_content, current_user, db, intent, confidence, session_id, file_info=None):
        try:
            doc_id = vector_db.add_document(ai_content, current_user.id)
            response = ChatResponse(
                intent=intent,
                confidence=confidence,
                module="knowledge",
                data={"doc_id": doc_id},
                message="测试文档已添加",
                session_id=session_id,
            )

            input_text = f"[引用文件] {original_content}" if file_info else original_content
            conversation = Conversation(
                user_id=current_user.id,
                session_id=session_id,
                module="knowledge",
                input_text=input_text,
                output_data=json.dumps({"doc_id": doc_id}, ensure_ascii=False),
            )
            db.add(conversation)
            _update_session_name(db, session_id, input_text)
            db.commit()

            return response
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"添加测试文档失败: {str(e)}")

    async def _handle_chat(ai_content, original_content, current_user, db, intent, confidence, session_id, use_rag=False, file_info=None):
        """处理闲聊/通用对话意图"""
        try:
            ai_config = _get_user_ai_config(current_user.id, db)

            if use_rag:
                result = answer_with_knowledge(ai_content, current_user.id, top_k=3, ai_config=ai_config)
                chat_data = {
                    "answer": result["answer"],
                    "references": result["references"],
                    "has_knowledge": result["has_knowledge"]
                }
                message = "测试文档问答完成"
            else:
                result = direct_chat(ai_content, ai_config)
                chat_data = {
                    "answer": result,
                    "references": [],
                    "has_knowledge": False
                }
                message = "AI 回复完成"

            if file_info:
                chat_data["file_reference"] = file_info

            response = ChatResponse(
                intent=intent,
                confidence=confidence,
                module="chat",
                data=chat_data,
                message=message,
                session_id=session_id,
            )

            input_text = f"[引用文件] {original_content}" if file_info else original_content
            conversation = Conversation(
                user_id=current_user.id,
                session_id=session_id,
                module="chat",
                input_text=input_text,
                output_data=json.dumps(chat_data, ensure_ascii=False),
            )
            db.add(conversation)
            _update_session_name(db, session_id, input_text)
            db.commit()

            return response
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"对话失败: {str(e)}")

    def _update_session_name(db: Session, session_id: str, first_message: str):
        """自动用第一条消息作为会话名，并更新会话时间戳"""
        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id
        ).first()
        if session:
            if session.name == "新会话":
                session.name = first_message[:20] + ("..." if len(first_message) > 20 else "")
            session.updated_at = datetime.now(timezone.utc)

    # 前端首页（公开）
    @app.get("/")
    async def root():
        return FileResponse(frontend_dir / "index.html")

    # ========== Web 测试 Agent 相关路由 ==========

    @app.post("/test/run", summary="执行Web自动化测试任务")
    async def run_test_task(
        request: TestTaskRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """执行Web自动化测试任务"""
        user_ai_config = db.query(ModelConfig).filter(
            ModelConfig.user_id == current_user.id,
            ModelConfig.is_active == True
        ).first()

        if not user_ai_config:
            return {"error": "请先在AI模型配置页面添加并启用一个AI模型"}

        ai_config = {
            "api_key": user_ai_config.api_key,
            "api_base_url": user_ai_config.api_base_url or "https://api.openai.com/v1",
            "chat_model": user_ai_config.model_name,
        }

        import asyncio
        from app.test_engine import run_test_task as engine_run_task

        task_result = await engine_run_task(
            target_url=request.target_url,
            project_path=request.project_path,
            test_goals=request.test_goals,
            ai_config=ai_config,
            max_steps=request.max_steps,
        )

        if "error" in task_result:
            raise HTTPException(status_code=400, detail=task_result["error"])

        steps = []
        for s in task_result.get("steps", []):
            steps.append(TestStep(**s))

        code_issues = []
        for ci in task_result.get("code_issues", []):
            code_issues.append(CodeIssue(**ci))

        errors_count = sum(
            1 for s in task_result["steps"]
            if s.get("console_errors") or s.get("network_errors") or not s.get("success")
        )

        screenshots_count = sum(
            1 for s in task_result["steps"]
            if s.get("screenshot")
        )

        return TestTaskResponse(
            task_id=task_result["task_id"],
            target_url=task_result["target_url"],
            status=task_result["status"],
            steps=steps,
            errors_found=errors_count,
            screenshots_saved=screenshots_count,
            code_issues=code_issues,
            message=task_result.get("message", ""),
        )

    @app.post("/test/code/fix", summary="确认代码修复")
    async def confirm_code_fix(
        request: CodeModifyRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """用户确认是否修改代码"""
        from app.test_engine import running_test_tasks
        from app.code_analyzer import analyze_and_fix_code

        task_data = running_test_tasks.get(request.task_id)
        if not task_data:
            raise HTTPException(status_code=404, detail="测试任务不存在")

        user_ai_config = db.query(ModelConfig).filter(
            ModelConfig.user_id == current_user.id,
            ModelConfig.is_active == True
        ).first()

        if not user_ai_config:
            raise HTTPException(status_code=400, detail="未配置AI模型")

        ai_config = {
            "api_key": user_ai_config.api_key,
            "api_base_url": user_ai_config.api_base_url or "https://api.openai.com/v1",
            "chat_model": user_ai_config.model_name,
        }

        issues = task_data.get("code_issues", [])
        if request.issue_index >= len(issues):
            raise HTTPException(status_code=404, detail="问题索引不存在")

        issue = issues[request.issue_index]

        fix_result = analyze_and_fix_code(
            file_path=issue["file_path"],
            line_number=issue.get("line_number", 0),
            error_log=issue.get("error_log", ""),
            issue_description=issue.get("issue_description", ""),
            suggested_fix=issue.get("suggested_fix", ""),
            ai_config=ai_config,
            auto_fix=request.confirmed,
        )

        return {
            "task_id": request.task_id,
            "issue_index": request.issue_index,
            "confirmed": request.confirmed,
            "fix_result": fix_result,
        }

    @app.get("/test/tasks/{task_id}", summary="查询测试任务状态")
    async def get_test_task(
        task_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """查询测试任务当前状态"""
        from app.test_engine import running_test_tasks

        task_data = running_test_tasks.get(task_id)
        if not task_data:
            raise HTTPException(status_code=404, detail="测试任务不存在")

        steps = []
        for s in task_data.get("steps", []):
            steps.append(TestStep(**s))

        code_issues = []
        for ci in task_data.get("code_issues", []):
            code_issues.append(CodeIssue(**ci))

        return TestTaskResponse(
            task_id=task_data["task_id"],
            target_url=task_data.get("target_url", ""),
            status=task_data["status"],
            steps=steps,
            errors_found=sum(
                1 for s in task_data["steps"]
                if s.get("console_errors") or s.get("network_errors") or not s.get("success")
            ),
            screenshots_saved=sum(1 for s in task_data["steps"] if s.get("screenshot")),
            code_issues=code_issues,
            message=task_data.get("message", ""),
        )

    @app.post("/test/project/files", summary="获取项目文件列表")
    async def get_project_files(
        project_path: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """获取指定项目的文件列表"""
        import os

        if not os.path.isdir(project_path):
            raise HTTPException(status_code=400, detail="项目路径不存在")

        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith(('.', '__pycache__', 'node_modules', '.git'))]
            for f in filenames:
                full_path = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()
                if ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.html', '.css', '.json', '.yaml', '.yml']:
                    files.append({
                        "path": full_path,
                        "name": f,
                        "size": os.path.getsize(full_path),
                    })

        return {"project_path": project_path, "files": files[:500]}
