"""API 路由定义模块 - TestAssistant AI"""
import logging
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List
from fastapi import HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.credential_cipher import encrypt_credential, decrypt_credential, is_encrypted
from app.models import User, Session as SessionModel, Conversation, ModelConfig, UserActiveModel, Document
from app.auth import get_current_user
from app.schemas import (
    ConversationRecord, ConversationHistoryResponse,
    SessionInfo, SessionListResponse, CreateSessionRequest, UpdateSessionRequest,
    ChatRequest,
    SupportedPlatform, ModelConfigInfo,
    ModelListResponse, AddModelRequest, UpdateModelRequest, TestAIRequest,
    TestAIResponse, ActiveModelResponse,
    AddKnowledgeRequest,
)
from app.config import base_dir
from app.llm import build_plain_client
from app.vector_db import vector_db
from app.file_storage import save_file, delete_file as delete_file_from_disk

logger = logging.getLogger(__name__)

# 上传大小上限:文档 20MB / 项目 ZIP 200MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _migrate_plaintext_credentials():
    """单用户迁移 + 启动一次性加密:
    1. 确保内置 "local" 用户存在,把历史多用户数据全部归并到它(单用户本地版语义)
    2. 把明文 API Key 加密落盘(幂等,已加密的跳过)"""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        local = db.query(User).filter(User.username == "local").first()
        if local is None:
            first = db.query(User).order_by(User.id.asc()).first()
            if first is not None and first.username != "local":
                first.username = "local"  # 复用最早用户(保留其 created_at),改名收编
                local = first
            else:
                local = User(username="local", password_hash="")
                db.add(local)
                db.flush()
        assert local is not None

        merged = 0
        for model in (ModelConfig, UserActiveModel, Conversation, Document, SessionModel):
            changed = db.query(model).filter(model.user_id != local.id).update(
                {model.user_id: local.id}, synchronize_session=False
            )
            merged += changed
        # 归并后删除其他用户行
        db.query(User).filter(User.id != local.id).delete(synchronize_session=False)
        # 旧会话记录的 user_active_models 可能重复指向同一 config,unique 约束兜底忽略
        if merged:
            db.commit()
            logger.info("已归并 %d 条历史数据到本地用户(id=%s)", merged, local.id)
        elif db.query(User).count() != 1:
            db.commit()

        rows = db.query(ModelConfig).all()
        migrated = 0
        for mc in rows:
            if mc.api_key and not is_encrypted(mc.api_key):
                mc.api_key = encrypt_credential(mc.api_key)
                migrated += 1
        if migrated:
            db.commit()
            logger.info("已加密迁移 %d 条明文 API Key", migrated)
    except Exception as e:
        db.rollback()
        logger.warning("启动迁移失败(不影响启动): %s", e)
    finally:
        db.close()


def register_routes(app):
    """注册所有 API 路由"""

    # 写文件确认的待裁决 Future 表(change_id -> Future[bool]),由 /agent/confirm 解决
    _pending_write_confirms: dict = {}

    # 初始化数据库
    init_db()
    _migrate_plaintext_credentials()

    # 前端静态文件路径(源码模式=仓库根/frontend;打包模式=exe 旁/frontend)
    frontend_dir = base_dir / "frontend"

    # vite 构建产物静态资源(/assets/*);目录不存在(未执行 npm run build)时跳过
    if (frontend_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="assets")

    # 单用户本地版:已移除 /auth/register|login|me 接口,鉴权依赖 get_current_user
    # 返回内置本地用户(app/auth.py)

    # ==================== 工作区接口(ZCode 式:打开本地项目文件夹) ====================

    @app.get("/workspace", summary="获取当前工作区")
    async def get_workspace():
        """当前打开的项目文件夹;未打开或已失效返回 null"""
        from app import workspace as ws_mod
        return {"path": ws_mod.get_current_workspace()}

    @app.post("/workspace", summary="打开(设置)工作区")
    async def set_workspace(request: dict):
        """设置本地项目文件夹为当前工作区,后续检查/修复/文件操作以它为根"""
        from app import workspace as ws_mod
        path = (request or {}).get("path", "")
        try:
            normalized = ws_mod.set_current_workspace(path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"path": normalized, "name": os.path.basename(normalized) or normalized}

    @app.post("/workspace/dialog", summary="弹出系统目录选择框")
    async def workspace_pick_dialog():
        """后端弹原生目录选择框(任何前端宿主可用),返回所选路径或 null(取消)"""
        import asyncio
        from app.native_dialog import ask_directory
        path = await asyncio.to_thread(ask_directory)
        return {"path": path}

    @app.delete("/workspace", summary="关闭工作区")
    async def close_workspace():
        from app import workspace as ws_mod
        ws_mod.clear_workspace()
        return {"message": "工作区已关闭"}

    @app.get("/workspace/files", summary="工作区文件树")
    async def get_workspace_files():
        """当前工作区的文件树(忽略依赖/构建产物目录,限 2000 项)"""
        from app import workspace as ws_mod
        ws = ws_mod.get_current_workspace()
        if not ws:
            raise HTTPException(status_code=400, detail="未打开工作区")
        return {"path": ws, "tree": ws_mod.build_file_tree(ws)}

    @app.get("/workspace/file", summary="查看工作区文件内容")
    async def get_workspace_file(path: str):
        """读取工作区内文件(路径围栏限制在工作区内部)"""
        from app import workspace as ws_mod
        from app.file_viewer import read_file_content
        ws = ws_mod.get_current_workspace()
        if not ws:
            raise HTTPException(status_code=400, detail="未打开工作区")
        if not ws_mod.is_within_workspace(path):
            raise HTTPException(status_code=403, detail="路径不在工作区内")
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="文件不存在")
        info = read_file_content(path)
        return {"path": path, **info}

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
        """脱敏 API Key，只显示前 4 位和后 4 位(入参应为已解密的明文)"""
        if not key or len(key) <= 8:
            return "****"
        return key[:4] + "****" + key[-4:]

    def _plain_api_key(mc: ModelConfig) -> str:
        """读取并解密存储的 API Key"""
        try:
            return decrypt_credential(mc.api_key)
        except ValueError as e:
            logger.warning("凭据解密失败 id=%s: %s", mc.id, e)
            return ""

    def _get_user_ai_config(user_id: int, db: Session) -> dict:
        """获取用户当前使用的 AI 配置(API Key 解密后仅在内存使用)"""
        active = db.query(UserActiveModel).filter_by(user_id=user_id).first()

        if active and active.model_config_id:
            mc = db.query(ModelConfig).filter_by(id=active.model_config_id, is_active=1).first()
            if mc:
                return {
                    "api_key": _plain_api_key(mc),
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
                api_key_masked=_mask_api_key(_plain_api_key(mc)),
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
        """添加模型配置(API Key 加密后落盘)"""
        mc = ModelConfig(
            user_id=current_user.id,
            platform="custom",
            api_key=encrypt_credential(request.api_key),
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
            "api_key_masked": _mask_api_key(_plain_api_key(mc)),
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

        # 忽略脱敏回显值(含 **** 的字符串不是有效密钥),只接受用户新输入的明文 Key(加密后落盘)
        if request.api_key and "****" not in request.api_key:
            mc.api_key = encrypt_credential(request.api_key)
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
    async def test_ai_connection(
        request: TestAIRequest,
        current_user: User = Depends(get_current_user),
    ):
        """测试 AI 连接是否正常(需登录,防止未鉴权端点被用作内网探针)"""
        try:
            client = build_plain_client({"api_key": request.api_key, "api_base_url": request.api_base_url})
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

    # ==================== 智能分析接口（Bug分析 / 测试用例 / 代码审查） ====================

    def _save_module_conversation(db: Session, user_id: int, session_id, module: str, input_text: str, data: dict):
        """按模块保存分析类对话记录(未提供会话时不落库)"""
        if not session_id:
            return
        conversation = Conversation(
            user_id=user_id,
            session_id=session_id,
            module=module,
            input_text=input_text,
            output_data=json.dumps(data, ensure_ascii=False),
        )
        db.add(conversation)
        _update_session_name(db, session_id, input_text)
        db.commit()


    # ==================== 文件管理接口 ====================

    @app.post("/files/upload", summary="上传文件")
    async def upload_file(
        file: UploadFile = File(...),
        category: str = Form("doc"),
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
            if len(file_bytes) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"文件超过大小限制({MAX_UPLOAD_BYTES // 1024 // 1024}MB)")

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
                        metadata={"source": file_info["original_filename"], "doc_id": str(doc.id),
                                  "category": category if category in ("doc", "standards") else "doc"}
                    )
                except Exception as e:
                    logger.warning("知识库同步失败(文件已保存): %s", e)

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
        """获取当前用户的所有知识文档（按父文档聚合分块）"""
        documents = vector_db.list_documents(current_user.id)
        knowledge = [
            {
                "doc_id": d["doc_id"],
                "content": d["content"],
                "metadata": d["metadata"],
                "chunk_count": d["chunk_count"],
            }
            for d in documents
        ]
        return {"knowledge": knowledge, "total": len(knowledge)}

    @app.post("/knowledge/add", summary="添加知识文档")
    async def add_knowledge(
        request: AddKnowledgeRequest,
        current_user: User = Depends(get_current_user),
    ):
        """添加知识文档到向量数据库"""
        from app.vector_db import vector_db
        if not vector_db.enabled:
            raise HTTPException(status_code=503, detail="知识库向量能力未启用:请在 .env 配置 EMBEDDING_API_KEY/EMBEDDING_API_BASE/EMBEDDING_MODEL")
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
        """更新知识文档内容（先删除旧的全部分块，再按新内容重新分块入库）"""
        vector_db.delete_document(doc_id, current_user.id)
        metadata = request.metadata or {"updated": "true"}
        new_doc_id = vector_db.add_document(request.content, current_user.id, metadata)
        return {"doc_id": new_doc_id, "message": "更新成功"}

    @app.post("/agent/confirm", summary="裁决智能体的写文件请求(diff 确认)")
    async def agent_confirm(request: dict):
        change_id = str(request.get("change_id") or "")
        approved = bool(request.get("approved"))
        fut = _pending_write_confirms.get(change_id)
        if not fut or fut.done():
            return {"success": False, "message": "确认请求不存在或已过期"}
        fut.set_result(approved)
        return {"success": True, "approved": approved}

    # ==================== 项目规范检查(inspector) ====================

    @app.post("/inspect/stream", summary="全项目规范检查(SSE 实时进度)")
    async def inspect_stream(
        request: dict,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """规则引擎秒扫 + AI 分文件语义审查(规范文件注入),SSE 推进度与报告

        request.body: {"scope": "all"(默认全量) | "changed"(仅 git 变更文件)}
        AI 审查结果按内容哈希缓存,未变更文件自动跳过
        """
        import asyncio

        from app import inspector, workspace as ws_mod

        scope = "changed" if request.get("scope") == "changed" else "all"

        ws = ws_mod.get_current_workspace()
        if not ws:
            async def _no_ws():
                yield f"data: {json.dumps({'type': 'error', 'message': '请先打开项目工作区'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_no_ws(), media_type="text/event-stream")

        ai_config = _get_user_ai_config(current_user.id, db)

        def _dedupe(rule_issues: list, ai_issues: list) -> list:
            """合并去重:AI 问题与规则问题同文件同行号时保留规则结果(确定性优先)"""
            seen = {(i["file"], i["line"]) for i in rule_issues}
            merged = list(rule_issues)
            for issue in ai_issues:
                if (issue["file"], issue["line"]) not in seen:
                    merged.append(issue)
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            merged.sort(key=lambda i: severity_order.get(i["severity"], 9))
            return merged

        async def _generator():
            step_no = 0

            def sse(event: dict) -> str:
                return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            try:
                # 0. 增量范围解析(git 变更文件)
                only_files: set | None = None
                if scope == "changed":
                    changed = await asyncio.to_thread(inspector.git_changed_files, ws)
                    if changed is None:
                        yield sse({"type": "step", "step": step_no, "action": "scope",
                                   "target": "changed", "result": "不是 git 仓库,回退全量检查", "success": False})
                    else:
                        only_files = set(changed)
                        yield sse({"type": "step", "step": step_no, "action": "scope",
                                   "target": "changed",
                                   "result": f"git 变更文件 {len(only_files)} 个", "success": True})

                # 1. 规则引擎(秒扫)
                step_no += 1
                yield sse({"type": "step", "step": step_no, "action": "rule_scan",
                           "target": ws, "result": "规则引擎扫描中...", "success": True})
                rule_issues = await asyncio.to_thread(inspector.rule_scan, ws, only_files)
                for issue in rule_issues:
                    if issue["severity"] in ("critical", "high"):
                        yield sse({"type": "step", "step": step_no, "action": f"rule:{issue['rule_id']}",
                                   "target": f"{issue['file']}:{issue['line']}",
                                   "result": issue["message"], "success": False})

                # 2. AI 语义审查(分文件;未配模型则跳过;结果按内容哈希缓存)
                ai_issues: list = []
                ai_files = 0
                cache_hits = 0
                if (ai_config or {}).get("api_key"):
                    standards = await asyncio.to_thread(inspector.load_standards_text, current_user.id)
                    candidates = await asyncio.to_thread(inspector.collect_code_files, ws, only_files)
                    review_cache = await asyncio.to_thread(inspector._load_review_cache, ws)
                    for i, item in enumerate(candidates, 1):
                        def _read_and_review(item=item):
                            try:
                                code = Path(item["path"]).read_text(encoding="utf-8")
                            except Exception:
                                return [], False
                            return inspector.ai_review_file_cached(
                                ai_config, ws, item["rel"], code, standards, review_cache)
                        found, from_cache = await asyncio.to_thread(_read_and_review)
                        ai_files += 1
                        if from_cache:
                            cache_hits += 1
                        ai_issues.extend(found)
                        note = " · 缓存命中" if from_cache else ""
                        yield sse({"type": "step", "step": step_no,
                                   "action": f"ai_review ({i}/{len(candidates)})",
                                   "target": item["rel"],
                                   "result": (f"发现 {len(found)} 个问题" if found else "未发现问题") + note,
                                   "success": True})
                    await asyncio.to_thread(inspector._save_review_cache, ws, review_cache)
                else:
                    yield sse({"type": "step", "step": step_no, "action": "ai_review",
                               "target": "skipped", "result": "未配置AI模型,仅完成规则扫描", "success": False})

                # 3. 汇总报告
                all_issues = _dedupe(rule_issues, ai_issues)
                report = {
                    "workspace": ws,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "scope": "changed" if only_files is not None else "all",
                    "score": inspector.health_score(all_issues),
                    "total": len(all_issues),
                    "by_severity": {
                        s: sum(1 for i in all_issues if i["severity"] == s)
                        for s in ("critical", "high", "medium", "low")
                    },
                    "ai_files": ai_files,
                    "cache_hits": cache_hits,
                    "rule_count": len(rule_issues),
                    "ai_count": len(ai_issues),
                    "issues": all_issues[:200],
                }
                saved = await asyncio.to_thread(inspector.save_report, ws, report)
                report["saved_to"] = saved
                yield sse({"type": "report", "data": report, "message": f"检查完成,健康分 {report['score']}"})
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.exception("规范检查失败")
                yield sse({"type": "error", "message": f"检查失败: {e}"})
                yield "data: [DONE]\n\n"

        return StreamingResponse(_generator(), media_type="text/event-stream")

    @app.get("/inspect/reports", summary="历史检查报告列表")
    async def inspect_reports(current_user: User = Depends(get_current_user)):
        from app import inspector, workspace as ws_mod
        ws = ws_mod.get_current_workspace()
        if not ws:
            return {"reports": []}
        return {"reports": inspector.list_reports(ws)}

    @app.get("/inspect/report", summary="读取检查报告详情")
    async def inspect_report(name: str, current_user: User = Depends(get_current_user)):
        from app import inspector, workspace as ws_mod
        ws = ws_mod.get_current_workspace()
        if not ws:
            raise HTTPException(status_code=400, detail="未打开工作区")
        data = inspector.load_report(ws, name)
        if not data:
            raise HTTPException(status_code=404, detail="报告不存在")
        return data

    # ==================== 统一对话接口（SSE 流式） ====================

    @app.post("/chat/stream", summary="流式统一对话接口（SSE 实时推送）")
    async def chat_stream(
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """流式统一对话接口：SSE 实时推送 AI 回答，支持 RAG 知识库问答"""
        import asyncio

        session_id = request.session_id

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

        # 智能体优先:工作区打开时,对话统一走工具调用型 Agent(ZCode 式);
        # 未打开工作区时回落为纯 LLM 流式对话
        from app import workspace as ws_mod
        current_workspace = ws_mod.get_current_workspace()
        if current_workspace:
            async def _wait_confirm(change_id: str) -> bool:
                """注册确认 Future 并等待用户裁决(/agent/confirm 解决);超时视为拒绝"""
                fut = asyncio.get_event_loop().create_future()
                _pending_write_confirms[change_id] = fut
                try:
                    return await asyncio.wait_for(fut, timeout=300)
                except asyncio.TimeoutError:
                    return False
                finally:
                    _pending_write_confirms.pop(change_id, None)

            async def _agent_generator():
                from app.agent_loop import stream_agent
                final_answer = ""
                try:
                    history_convs = db.query(Conversation).filter(
                        Conversation.user_id == current_user.id,
                        Conversation.session_id == session_id,
                        Conversation.module == "chat",
                    ).order_by(Conversation.created_at.desc()).limit(10).all()
                    history = []
                    for conv in reversed(history_convs):
                        try:
                            answer = json.loads(conv.output_data).get("answer", "")
                        except Exception:
                            answer = ""
                        history.append({"user": conv.input_text, "assistant": answer})

                    async for event in stream_agent(
                        workspace=current_workspace,
                        user_message=effective_content,
                        history=history,
                        ai_config=ai_config,
                        session_id=session_id,
                        confirm_hook=_wait_confirm,
                    ):
                        if event.get("type") == "answer":
                            final_answer = (event.get("data") or {}).get("answer", "")
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                finally:
                    chat_data = {
                        "answer": final_answer,
                        "references": [],
                        "has_knowledge": request.use_rag,
                        "agent": True,
                    }
                    conversation = Conversation(
                        user_id=current_user.id,
                        session_id=session_id,
                        module="chat",
                        input_text=request.content,
                        output_data=json.dumps(chat_data, ensure_ascii=False),
                    )
                    db.add(conversation)
                    _update_session_name(db, session_id, request.content)
                    db.commit()
                    try:
                        yield f"data: {json.dumps({'type': 'done', 'data': chat_data, 'message': '智能体任务完成', 'conv_id': conversation.id}, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                    except Exception:
                        pass

            return StreamingResponse(_agent_generator(), media_type="text/event-stream")

        # 普通对话：流式调用 LLM
        client = build_plain_client(ai_config)

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

            yield f"data: {json.dumps({'type': 'meta', 'intent': 'chat', 'session_id': session_id}, ensure_ascii=False)}\n\n"

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
                input_text = request.content
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

