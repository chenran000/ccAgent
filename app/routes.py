"""API 路由定义模块 - TestAssistant AI"""
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import List
from fastapi import HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import User, Session as SessionModel, Conversation, ModelConfig, UserActiveModel, Document, ProjectFolder
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.schemas import (
    LoginRequest, RegisterRequest, AuthResponse, UserInfo,
    ConversationRecord, ConversationHistoryResponse,
    SessionInfo, SessionListResponse, CreateSessionRequest, UpdateSessionRequest,
    ChatRequest,
    SupportedPlatform, ModelConfigInfo,
    ModelListResponse, AddModelRequest, UpdateModelRequest, TestAIRequest,
    TestAIResponse, ActiveModelResponse,
    TestTaskRequest, TestTaskResponse, TestStep, TestRequest,
    CodeIssue, CodeModifyRequest,
    ProjectFolderInfo, ProjectFolderListResponse, ProjectFolderCreateRequest,
    FileNode, FileContentResponse,
    AddKnowledgeRequest,
)
from app.intent_classifier import classify_intent_local
from app.vector_db import vector_db
from app.file_parser import parse_file
from app.file_storage import save_file, delete_file as delete_file_from_disk, get_user_upload_dir
from app.file_viewer import read_file_content


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
        session.updated_at = datetime.now()
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
        mc.updated_at = datetime.now()

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
            active.updated_at = datetime.now()
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
            active.updated_at = datetime.now()
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
        """上传文件到服务器，解析文本内容后保存，并同步到知识库向量数据库"""
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

            # 同步到知识库向量数据库
            if file_info["extracted_text"].strip():
                try:
                    vector_db.add_document(
                        content=file_info["extracted_text"],
                        user_id=current_user.id,
                        metadata={"source": file_info["original_filename"], "doc_id": str(doc.id)}
                    )
                except Exception as e:
                    print(f"[知识库同步警告] {e}")

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

    # ==================== 项目文件夹接口 ====================

    PROJECT_FOLDERS_DIR = Path(__file__).parent.parent / "project_uploads"
    PROJECT_FOLDERS_DIR.mkdir(exist_ok=True)

    @app.get("/projects", response_model=ProjectFolderListResponse, summary="获取项目文件夹列表")
    async def list_project_folders(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """获取当前用户上传的所有项目文件夹"""
        try:
            folders = db.query(ProjectFolder).filter(
                ProjectFolder.user_id == current_user.id
            ).order_by(ProjectFolder.updated_at.desc()).all()

            return ProjectFolderListResponse(
                folders=[
                    ProjectFolderInfo(
                        id=f.id,
                        folder_name=f.folder_name,
                        folder_path=f.folder_path,
                        created_at=f.created_at.isoformat(),
                        updated_at=f.updated_at.isoformat(),
                    )
                    for f in folders
                ],
                total=len(folders),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取项目列表失败: {str(e)}")

    @app.post("/projects", response_model=ProjectFolderInfo, summary="上传项目文件夹")
    async def create_project_folder(
        request: ProjectFolderCreateRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """创建空项目文件夹"""
        try:
            user_project_dir = PROJECT_FOLDERS_DIR / str(current_user.id)
            user_project_dir.mkdir(exist_ok=True)

            folder_name = request.folder_name.strip() or "未命名项目"
            folder_path = user_project_dir / f"{folder_name}_{uuid.uuid4().hex[:8]}"
            folder_path.mkdir(exist_ok=True)

            pf = ProjectFolder(
                user_id=current_user.id,
                folder_name=folder_name,
                folder_path=str(folder_path),
            )
            db.add(pf)
            db.commit()
            db.refresh(pf)

            return ProjectFolderInfo(
                id=pf.id,
                folder_name=pf.folder_name,
                folder_path=pf.folder_path,
                created_at=pf.created_at.isoformat(),
                updated_at=pf.updated_at.isoformat(),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"创建项目文件夹失败: {str(e)}")

    @app.post("/projects/upload", summary="上传项目文件夹（ZIP）")
    async def upload_project_zip(
        folder_name: str = Form(...),
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """上传 ZIP 格式的项目文件夹"""
        import zipfile
        import shutil

        try:
            if not file.filename or not file.filename.lower().endswith('.zip'):
                raise HTTPException(status_code=400, detail="仅支持 ZIP 格式的项目文件")

            user_project_dir = PROJECT_FOLDERS_DIR / str(current_user.id)
            user_project_dir.mkdir(exist_ok=True)

            folder_name = folder_name.strip() or "导入项目"
            folder_path = user_project_dir / f"{folder_name}_{uuid.uuid4().hex[:8]}"
            folder_path.mkdir(exist_ok=True)

            # 保存临时 ZIP 文件
            temp_zip = folder_path.parent / f"temp_{uuid.uuid4().hex}.zip"
            zip_content = await file.read()
            with open(temp_zip, "wb") as f:
                f.write(zip_content)

            # 解压
            with zipfile.ZipFile(temp_zip, 'r') as zf:
                zf.extractall(folder_path)

            # 删除临时文件
            temp_zip.unlink()

            pf = ProjectFolder(
                user_id=current_user.id,
                folder_name=folder_name,
                folder_path=str(folder_path),
            )
            db.add(pf)
            db.commit()
            db.refresh(pf)

            return {"message": "项目上传成功", "id": pf.id}
        except HTTPException:
            raise
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="无效的 ZIP 文件")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"项目上传失败: {str(e)}")

    @app.delete("/projects/{project_id}", summary="删除项目文件夹")
    async def delete_project_folder(
        project_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """删除项目文件夹（包括磁盘文件）"""
        try:
            pf = db.query(ProjectFolder).filter(
                ProjectFolder.id == project_id,
                ProjectFolder.user_id == current_user.id
            ).first()

            if not pf:
                raise HTTPException(status_code=404, detail="项目不存在")

            # 删除磁盘文件夹
            if os.path.isdir(pf.folder_path):
                shutil.rmtree(pf.folder_path, ignore_errors=True)

            db.delete(pf)
            db.commit()

            return {"message": "项目删除成功"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"项目删除失败: {str(e)}")

    @app.get("/projects/{project_id}/files", summary="获取项目文件树")
    async def get_project_file_tree(
        project_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """获取项目文件树结构"""
        import os
        from app.schemas import FileNode

        pf = db.query(ProjectFolder).filter(
            ProjectFolder.id == project_id,
            ProjectFolder.user_id == current_user.id
        ).first()

        if not pf:
            raise HTTPException(status_code=404, detail="项目不存在")

        if not os.path.isdir(pf.folder_path):
            raise HTTPException(status_code=400, detail="项目文件夹不存在")

        # 忽略的目录
        ignore_dirs = {'.git', '__pycache__', 'node_modules', '.idea', '.vscode', '.next', 'dist', 'build', 'coverage', '.nyc_output', '.cache', 'venv', 'env', '.tox', '.pytest_cache', 'target', 'output', 'out'}
        # 忽略的文件
        ignore_files = {'.DS_Store', 'Thumbs.db'}

        def build_tree(dir_path: str) -> List[dict]:
            nodes = []
            try:
                entries = sorted(os.listdir(dir_path))
            except PermissionError:
                return nodes

            for entry in entries:
                if entry in ignore_dirs or entry in ignore_files:
                    continue
                if entry.startswith('.'):
                    continue

                full_path = os.path.join(dir_path, entry)
                rel_path = os.path.relpath(full_path, pf.folder_path)

                if os.path.isdir(full_path):
                    children = build_tree(full_path)
                    if children:  # 只添加非空目录
                        nodes.append({
                            "name": entry,
                            "path": rel_path,
                            "type": "directory",
                            "children": children,
                        })
                else:
                    ext = os.path.splitext(entry)[1].lower()
                    size = os.path.getsize(full_path)
                    nodes.append({
                        "name": entry,
                        "path": rel_path,
                        "type": "file",
                        "size": size,
                    })

            return nodes

        tree = build_tree(pf.folder_path)
        return {"project_id": pf.id, "folder_name": pf.folder_name, "tree": tree}

    @app.get("/projects/{project_id}/file/{file_path:path}", summary="查看文件内容")
    async def get_project_file_content(
        project_id: int,
        file_path: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """查看项目中的文件内容"""
        import urllib.parse

        pf = db.query(ProjectFolder).filter(
            ProjectFolder.id == project_id,
            ProjectFolder.user_id == current_user.id
        ).first()

        if not pf:
            raise HTTPException(status_code=404, detail="项目不存在")

        # URL 解码文件路径
        file_path = urllib.parse.unquote(file_path)

        full_path = os.path.join(pf.folder_path, file_path)
        full_path = os.path.normpath(full_path)

        # 安全检查：确保文件路径在项目目录内
        if not full_path.startswith(os.path.normpath(pf.folder_path)):
            raise HTTPException(status_code=403, detail="非法路径")

        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        if os.path.isdir(full_path):
            raise HTTPException(status_code=400, detail="不能查看目录")

        content_info = read_file_content(full_path)

        return {
            "name": os.path.basename(full_path),
            "path": file_path,
            "content": content_info["content"],
            "content_type": content_info["content_type"],
            "language": content_info["language"],
            "is_binary": content_info["is_binary"],
            "image_url": content_info["image_url"],
            "size": content_info["size"],
            "error": content_info["error"],
        }

    # ==================== 知识库管理接口（基于 ChromaDB 向量库） ====================

    @app.get("/knowledge/stats", summary="获取知识库统计")
    async def get_knowledge_stats(
        current_user: User = Depends(get_current_user),
    ):
        """获取当前用户的知识库统计信息"""
        stats = vector_db.get_stats(current_user.id)
        return stats

    @app.get("/knowledge/list", summary="获取知识库文档列表")
    async def get_knowledge_list(
        current_user: User = Depends(get_current_user),
    ):
        """获取当前用户的所有知识文档"""
        from app.vector_db import vector_db
        collection = vector_db._get_collection(current_user.id)
        count = collection.count()
        if count == 0:
            return {"knowledge": [], "total": 0}

        # 获取所有文档
        results = collection.get()
        knowledge = []
        for i, doc_id in enumerate(results["ids"]):
            knowledge.append({
                "doc_id": doc_id,
                "content": results["documents"][i],
                "metadata": results["metadatas"][i] if results["metadatas"] else {},
                "created_at": datetime.now().isoformat(),
            })
        return {"knowledge": knowledge, "total": len(knowledge)}

    @app.post("/knowledge/add", summary="添加知识文档")
    async def add_knowledge(
        request: AddKnowledgeRequest,
        current_user: User = Depends(get_current_user),
    ):
        """添加知识文档到向量数据库"""
        from app.vector_db import vector_db
        doc_id = vector_db.add_document(request.content, current_user.id, request.metadata)
        return {"doc_id": doc_id, "message": "知识添加成功"}

    @app.delete("/knowledge/{doc_id}", summary="删除知识文档")
    async def delete_knowledge(
        doc_id: str,
        current_user: User = Depends(get_current_user),
    ):
        """删除指定的知识文档"""
        from app.vector_db import vector_db
        success = vector_db.delete_document(doc_id, current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="文档不存在")
        return {"message": "删除成功"}

    @app.put("/knowledge/{doc_id}", summary="更新知识文档")
    async def update_knowledge(
        doc_id: str,
        request: AddKnowledgeRequest,
        current_user: User = Depends(get_current_user),
    ):
        """更新知识文档内容（先删除旧的，再添加新的）"""
        from app.vector_db import vector_db
        # 先删除旧的
        vector_db.delete_document(doc_id, current_user.id)
        # 再添加新的（保留原 doc_id）
        collection = vector_db._get_collection(current_user.id)
        metadata = request.metadata or {"updated": "true"}
        collection.add(
            documents=[request.content],
            ids=[doc_id],
            metadatas=[metadata]
        )
        return {"doc_id": doc_id, "message": "更新成功"}

    # ==================== 统一对话接口（SSE 流式） ====================

    @app.post("/chat/stream", summary="流式统一对话接口（SSE 实时推送）")
    async def chat_stream(
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """流式统一对话接口：SSE 实时推送 AI 回答，支持 RAG 知识库问答"""
        import asyncio
        from openai import OpenAI

        session_id = request.session_id
        file_id = request.file_id

        if not session_id:
            session_id = uuid.uuid4().hex[:16]
            session = SessionModel(
                user_id=current_user.id,
                session_id=session_id,
                name="新会话",
            )
            db.add(session)
            db.commit()

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

        ai_config = _get_user_ai_config(current_user.id, db)
        system_prompt = "你是一个专业的软件测试助手。请回答用户的问题。"

        # RAG 模式：先检索知识库，然后将知识注入 prompt
        if request.use_rag:
            try:
                from app.vector_db import vector_db
                search_results = vector_db.search(effective_content, current_user.id, top_k=3)

                if search_results:
                    knowledge_context = "\n\n参考知识：\n" + "\n".join(
                        f"- {r['document']['content']}" for r in search_results
                    )
                    effective_content = f"{effective_content}{knowledge_context}"
                    system_prompt = "你是一个专业的软件测试助手。请基于以下参考资料回答用户的问题，如果资料不足以回答问题，可以结合你自己的知识来回答。\n\n"
            except Exception:
                pass

        # 检查是否是 web_test 意图
        intent_result = classify_intent_local(effective_content)
        intent = intent_result["intent"]
        confidence = intent_result["confidence"]

        if intent == "web_test":
            from app.test_engine import run_test_task

            url_match = re.search(r'https?://[^\s]+', effective_content)
            test_url = url_match.group(0) if url_match else None
            if not test_url and request.browser_url:
                test_url = request.browser_url

            if not test_url:
                async def _no_url_generator():
                    yield f"data: {json.dumps({'type': 'error', 'message': '请提供要测试的网站 URL'}, ensure_ascii=False)}\n\n"
                return StreamingResponse(_no_url_generator(), media_type="text/event-stream")

            project_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_project")
            queue: asyncio.Queue = asyncio.Queue()
            stop_event = asyncio.Event()
            test_task_id = None

            async def on_step(step_data):
                await queue.put(step_data)

            async def _event_generator():
                nonlocal test_task_id

                async def _run():
                    nonlocal test_task_id
                    try:
                        result = await run_test_task(
                            target_url=test_url,
                            project_path=project_path,
                            test_goals=[effective_content],
                            ai_config=ai_config,
                            max_steps=20,
                            on_step=on_step,
                            stop_event=stop_event,
                        )
                        test_task_id = result.get("task_id")
                        status = result.get("status", "completed")
                        if status == "cancelled":
                            await queue.put({
                                "type": "cancelled",
                                "message": result.get("message", "测试已停止"),
                                "total_steps": len(result.get("steps", [])),
                                "code_issues": result.get("code_issues", []),
                            })
                        else:
                            await queue.put({
                                "type": "done",
                                "status": status,
                                "message": result.get("message", "测试完成"),
                                "total_steps": len(result.get("steps", [])),
                                "code_issues": result.get("code_issues", []),
                            })
                    except Exception as e:
                        await queue.put({"type": "error", "message": str(e)})
                    finally:
                        await queue.put(None)

                task = asyncio.create_task(_run())
                while test_task_id is None:
                    await asyncio.sleep(0.05)
                    if task.done():
                        break

                yield f"data: {json.dumps({'type': 'start', 'url': test_url, 'message': f'开始测试 {test_url}', 'task_id': test_task_id}, ensure_ascii=False)}\n\n"

                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"

            return StreamingResponse(_event_generator(), media_type="text/event-stream")

        # 普通对话：流式调用 LLM
        client = OpenAI(api_key=ai_config["api_key"], base_url=ai_config.get("api_base_url", "https://api.openai.com/v1"))

        async def _stream_generator():
            full_text = ""
            queue: asyncio.Queue = asyncio.Queue()
            import threading

            def _fetch_stream():
                """在线程中执行流式请求，通过 queue 传递结果"""
                nonlocal full_text
                try:
                    # 加载该 session 的历史对话（最近 10 轮）
                    history_limit = 10
                    history_convs = db.query(Conversation).filter(
                        Conversation.user_id == current_user.id,
                        Conversation.session_id == session_id,
                        Conversation.module == "chat"
                    ).order_by(Conversation.created_at.desc()).limit(history_limit).all()

                    # 反转为时间正序
                    history_convs.reverse()

                    # 构建包含历史上下文的 messages
                    messages = [{"role": "system", "content": system_prompt}]
                    for conv in history_convs:
                        # 添加用户消息
                        messages.append({"role": "user", "content": conv.input_text})
                        # 添加 AI 回复
                        try:
                            output = json.loads(conv.output_data)
                            answer = output.get("answer", "")
                            if answer:
                                messages.append({"role": "assistant", "content": answer})
                        except:
                            pass
                    # 添加当前用户消息
                    messages.append({"role": "user", "content": effective_content})

                    response = client.chat.completions.create(
                        model=ai_config["chat_model"],
                        messages=messages,
                        temperature=0.7,
                        stream=True,
                    )
                    for chunk in response:
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            full_text += content
                            queue.put_nowait(content)
                    queue.put_nowait(None)  # 结束标记
                except Exception as e:
                    queue.put_nowait({"error": str(e)})

            yield f"data: {json.dumps({'type': 'meta', 'intent': 'chat', 'confidence': confidence, 'session_id': session_id}, ensure_ascii=False)}\n\n"

            try:
                t = threading.Thread(target=_fetch_stream, daemon=True)
                t.start()

                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, dict) and "error" in item:
                        raise Exception(item["error"])
                    yield f"data: {json.dumps({'type': 'chunk', 'content': item}, ensure_ascii=False)}\n\n"

                t.join()
            finally:
                # 无论正常结束还是连接中断，都保存对话记录
                chat_data = {
                    "answer": full_text,
                    "references": [],
                    "has_knowledge": request.use_rag,
                }
                input_text = f"[引用文件] {request.content}" if file_info else request.content
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

                # 尝试发送 done 事件（如果连接已断开会被静默忽略）
                try:
                    yield f"data: {json.dumps({'type': 'done', 'data': chat_data, 'message': 'AI 回复完成', 'conv_id': conversation.id}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception:
                    pass

        return StreamingResponse(_stream_generator(), media_type="text/event-stream")

    def _update_session_name(db: Session, session_id: str, first_message: str):
        """自动用第一条消息作为会话名，并更新会话时间戳"""
        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id
        ).first()
        if session:
            if session.name == "新会话":
                session.name = first_message[:20] + ("..." if len(first_message) > 20 else "")
            session.updated_at = datetime.now()

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

    @app.get("/test/project/files", summary="获取项目文件列表")
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

    @app.post("/test/stream", summary="流式执行 Web 自动化测试（SSE）")
    async def stream_test(
        request: TestRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """SSE 流式测试接口：实时推送每个测试步骤"""
        from app.test_engine import run_test_task
        import asyncio

        ai_config = _get_user_ai_config(current_user.id, db)

        # 提取 URL：优先从内容中提取，其次使用浏览器面板当前URL
        url_match = re.search(r'https?://[^\s]+', request.content)
        test_url = url_match.group(0) if url_match else None

        if not test_url and request.browser_url:
            test_url = request.browser_url

        if not test_url:
            async def _no_url_generator():
                yield f"data: {json.dumps({'type': 'error', 'message': '请提供要测试的网站 URL'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_no_url_generator(), media_type="text/event-stream")

        project_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_project")

        # 使用 Queue 在回调和生成器之间传递事件
        queue: asyncio.Queue = asyncio.Queue()
        stop_event = asyncio.Event()

        async def on_step(step_data):
            await queue.put(step_data)

        # 预先生成 task_id，前端可通过 start 事件获取
        test_task_id = None

        async def _event_generator():
            nonlocal test_task_id

            # 在后台运行测试任务
            async def _run():
                nonlocal test_task_id
                try:
                    result = await run_test_task(
                        target_url=test_url,
                        project_path=project_path,
                        test_goals=[request.content],
                        ai_config=ai_config,
                        max_steps=20,
                        on_step=on_step,
                        stop_event=stop_event,
                    )
                    test_task_id = result.get("task_id")
                    status = result.get("status", "completed")
                    if status == "cancelled":
                        await queue.put({
                            "type": "cancelled",
                            "message": result.get("message", "测试已停止"),
                            "total_steps": len(result.get("steps", [])),
                            "code_issues": result.get("code_issues", []),
                        })
                    else:
                        await queue.put({
                            "type": "done",
                            "status": status,
                            "message": result.get("message", "测试完成"),
                            "total_steps": len(result.get("steps", [])),
                            "code_issues": result.get("code_issues", []),
                        })
                except Exception as e:
                    await queue.put({"type": "error", "message": str(e)})
                finally:
                    await queue.put(None)  # 结束信号

            task = asyncio.create_task(_run())

            # 等待 task_id 生成后推送开始事件
            while test_task_id is None:
                await asyncio.sleep(0.05)
                if task.done():
                    break

            # 推送开始事件（包含 task_id 以便前端停止测试）
            yield f"data: {json.dumps({'type': 'start', 'url': test_url, 'message': f'开始测试 {test_url}', 'task_id': test_task_id}, ensure_ascii=False)}\n\n"

            # 从队列读取事件并推送
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(_event_generator(), media_type="text/event-stream")

    @app.post("/test/stop/{task_id}", summary="停止正在运行的测试任务")
    async def stop_test(
        task_id: str,
        current_user: User = Depends(get_current_user),
    ):
        """停止指定测试任务"""
        from app.test_engine import running_test_tasks

        task = running_test_tasks.get(task_id)
        if not task:
            return {"success": False, "message": "测试任务不存在或已结束"}

        # 触发停止事件
        stop_event = task.get("stop_event")
        if stop_event:
            stop_event.set()
            task["status"] = "stopping"

        return {"success": True, "message": "已发送停止信号"}
