"""API 路由定义模块 - TestAssistant AI"""
import logging
import asyncio
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
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.credential_cipher import encrypt_credential, decrypt_credential, is_encrypted
from app.models import User, Session as SessionModel, Conversation, ModelConfig, UserActiveModel, Document, ProjectFolder
from app.auth import get_current_user
from app.schemas import (
    ConversationRecord, ConversationHistoryResponse,
    SessionInfo, SessionListResponse, CreateSessionRequest, UpdateSessionRequest,
    ChatRequest,
    SupportedPlatform, ModelConfigInfo,
    ModelListResponse, AddModelRequest, UpdateModelRequest, TestAIRequest,
    TestAIResponse, ActiveModelResponse,
    TestTaskResponse, TestStep, TestRequest,
    CodeAnalysisRequest, CodeAnalysisResponse, TestCaseRequest, TestCaseResponse,
    CodeIssue, CodeModifyRequest,
    ProjectFolderInfo, ProjectFolderListResponse, ProjectFolderCreateRequest,
    FileNode, FileContentResponse,
    AddKnowledgeRequest,
)
from app.analysis_service import analyze_bug, generate_test_cases, review_code
from app.config import PROJECT_FOLDERS_DIR, TEST_AGENT_VISION, TEST_PROJECT_DIR, base_dir
from app.intent_classifier import classify_intent_local
from app.llm import build_plain_client
from app.vector_db import chunk_text, vector_db
from app.file_parser import parse_file
from app.file_storage import save_file, delete_file as delete_file_from_disk, get_user_upload_dir
from app.file_viewer import read_file_content
from app.test_agent_graph import (
    active_runs,
    make_config,
    new_task_state,
    stop_requested,
    test_agent_manager,
)
from langgraph.types import Command

logger = logging.getLogger(__name__)

# 上传大小上限:文档 20MB / 项目 ZIP 200MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PROJECT_ZIP_BYTES = 200 * 1024 * 1024


def _extract_knowledge_content(content: str) -> str:
    """从"添加知识/记住：xxx"类指令中提取知识正文,无指令前缀时原样返回"""
    parts = re.split(r"[：:]", content, maxsplit=1)
    if len(parts) == 2 and re.search(r"添加|记住|存档|保存|录入|知识", parts[0]):
        body = parts[1].strip()
        if body:
            return body
    return content


def _resolve_use_vision(requested) -> bool:
    """视觉感知开关:请求未指定时跟随全局 TEST_AGENT_VISION 配置"""
    return TEST_AGENT_VISION if requested is None else bool(requested)


def _resolve_test_url(content: str, browser_url: str | None) -> str | None:
    """从测试指令中提取目标 URL;缺省回落浏览器面板当前 URL"""
    match = re.search(r'https?://[^\s]+', content or "")
    if match:
        return match.group(0)
    return browser_url or None


def _state_to_response(task_id: str, values: dict) -> TestTaskResponse:
    """把测试任务状态快照转换为 TestTaskResponse"""
    steps = values.get("steps", [])
    code_issues = values.get("code_issues", [])
    return TestTaskResponse(
        task_id=task_id,
        target_url=values.get("target_url", ""),
        status=values.get("status", "running"),
        steps=[TestStep(**s) for s in steps],
        errors_found=sum(
            1 for s in steps
            if s.get("console_errors") or s.get("network_errors") or not s.get("success")
        ),
        screenshots_saved=sum(1 for s in steps if s.get("screenshot")),
        code_issues=[CodeIssue(**ci) for ci in code_issues],
        message=values.get("message", ""),
        script_path=values.get("script_path", ""),
        report_path=values.get("report_path", ""),
    )


def _test_sse_response(graph_input, task_id: str, start_payload: dict = None) -> StreamingResponse:
    """把测试 Agent 的执行过程包装为 SSE 流

    graph_input: 初始 TestTaskState / None(从最后检查点恢复) / Command(resume=...)
    事件经 astream(stream_mode="updates") 逐节点转换,替代原 Queue 回调拼接。
    """

    async def _event_generator():
        graph = await test_agent_manager.get_graph()
        config = make_config(task_id)
        active_runs.add(task_id)
        try:
            # start 事件立即推送,前端第一时间拿到 task_id 用于停止/恢复
            start_event = {"type": "start", "task_id": task_id, "message": f"开始测试任务 {task_id}"}
            if start_payload:
                start_event.update(start_payload)
            yield f"data: {json.dumps(start_event, ensure_ascii=False)}\n\n"

            async for chunk in graph.astream(graph_input, config=config, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    # 到达人工确认点:本次运行暂停,等待 /test/code/fix 恢复
                    yield f"data: {json.dumps({'type': 'waiting_confirm', 'message': '发现代码问题，等待人工确认修复'}, ensure_ascii=False)}\n\n"
                    continue

                for delta in chunk.values():
                    if not isinstance(delta, dict):
                        continue

                    new_steps = delta.get("steps") or []
                    new_issues = delta.get("code_issues") or []
                    status = delta.get("status")

                    # 仅中间步骤推送 step 事件(终态 delta 携带的是全量快照)
                    if new_steps and not status:
                        s = new_steps[-1]
                        yield f"data: {json.dumps({'type': 'step', 'step': s.get('step'), 'action': s.get('action'), 'target': s.get('target'), 'result': s.get('result'), 'success': s.get('success'), 'console_errors': s.get('console_errors', []), 'network_errors': s.get('network_errors', [])}, ensure_ascii=False)}\n\n"

                    # 错误分析出新的代码问题(非终态快照)
                    if new_issues and not status:
                        yield f"data: {json.dumps({'type': 'code_issue', 'issue': new_issues[-1], 'total': len(new_issues)}, ensure_ascii=False)}\n\n"

                    if status == "cancelled":
                        yield f"data: {json.dumps({'type': 'cancelled', 'message': delta.get('message', '测试已停止'), 'total_steps': len(new_steps), 'code_issues': new_issues, 'script_path': delta.get('script_path') or '', 'report_path': delta.get('report_path') or ''}, ensure_ascii=False)}\n\n"
                    elif status == "failed":
                        yield f"data: {json.dumps({'type': 'error', 'message': delta.get('message', '测试执行失败'), 'total_steps': len(new_steps), 'code_issues': new_issues}, ensure_ascii=False)}\n\n"
                    elif status in ("completed", "awaiting_fix"):
                        yield f"data: {json.dumps({'type': 'done', 'status': status, 'message': delta.get('message', ''), 'total_steps': len(new_steps), 'code_issues': new_issues, 'script_path': delta.get('script_path') or '', 'report_path': delta.get('report_path') or ''}, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            active_runs.discard(task_id)

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


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
        for model in (ModelConfig, UserActiveModel, Conversation, Document, ProjectFolder, SessionModel):
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

    def _get_user_active_model_id(user_id: int, db: Session) -> int:
        """获取用户当前激活模型的配置 id(供测试任务状态引用,密钥不进检查点)"""
        active = db.query(UserActiveModel).filter_by(user_id=user_id).first()
        return active.model_config_id if active else 0

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

    @app.post("/analysis/bug", response_model=CodeAnalysisResponse, summary="Bug 枚举分析")
    async def bug_analysis(
        request: CodeAnalysisRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """对代码或问题描述做 Bug类型/严重程度/影响范围 三维度分析"""
        ai_config = _get_user_ai_config(current_user.id, db)
        try:
            result = await asyncio.to_thread(analyze_bug, request.code, ai_config)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        _save_module_conversation(db, current_user.id, request.session_id, "code", request.code, result)
        return CodeAnalysisResponse(
            intent="code",
            confidence=result.get("bug_type_confidence", 0.0),
            module="code",
            data=result,
            message="Bug分析完成",
            session_id=request.session_id or "",
        )

    @app.post("/analysis/cases", response_model=TestCaseResponse, summary="测试用例生成")
    async def generate_cases(
        request: TestCaseRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """根据功能描述生成测试用例(正常/异常/边界/安全场景)"""
        ai_config = _get_user_ai_config(current_user.id, db)
        try:
            result = await asyncio.to_thread(
                generate_test_cases, request.feature_description, ai_config, current_user.id
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        _save_module_conversation(db, current_user.id, request.session_id, "case", request.feature_description, result)
        return TestCaseResponse(
            intent="case",
            confidence=1.0 if result.get("cases") else 0.0,
            module="case",
            data=result,
            message="测试用例生成完成",
            session_id=request.session_id or "",
        )

    @app.post("/analysis/code", response_model=CodeAnalysisResponse, summary="代码审查")
    async def code_review(
        request: CodeAnalysisRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """代码审查:功能/安全/性能/质量 四维度问题清单"""
        ai_config = _get_user_ai_config(current_user.id, db)
        try:
            result = await asyncio.to_thread(review_code, request.code, ai_config)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        _save_module_conversation(db, current_user.id, request.session_id, "code", request.code, result)
        return CodeAnalysisResponse(
            intent="code",
            confidence=1.0 if result.get("issues") is not None else 0.0,
            module="code",
            data=result,
            message="代码审查完成",
            session_id=request.session_id or "",
        )

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
                        metadata={"source": file_info["original_filename"], "doc_id": str(doc.id)}
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

    # 托管项目目录与默认测试项目目录统一来自 config(存储根目录)

    def _is_allowed_project_path(path: str) -> bool:
        """项目路径只允许位于托管项目目录或默认 test_project 目录内，防任意目录遍历"""
        candidate = os.path.abspath(path)
        roots = [
            str(PROJECT_FOLDERS_DIR.resolve()),
            str(TEST_PROJECT_DIR.resolve()),
        ]
        return any(
            candidate == root or candidate.startswith(root.rstrip(os.sep) + os.sep)
            for root in roots
        )

    def _resolve_project_path(user_id: int, project_id, db: Session) -> str:
        """解析测试任务的项目目录

        指定 project_id 时使用该用户的托管项目（代码定位/修复链路可用）；
        未指定时回落默认 test_project 目录并自动创建，保证测试入口开箱可用。
        """
        if project_id:
            folder = db.query(ProjectFolder).filter(
                ProjectFolder.id == project_id,
                ProjectFolder.user_id == user_id,
            ).first()
            if not folder:
                raise HTTPException(status_code=404, detail="项目不存在")
            if not os.path.isdir(folder.folder_path):
                raise HTTPException(status_code=400, detail="项目目录已丢失，请重新上传该项目")
            if not _is_allowed_project_path(folder.folder_path):
                raise HTTPException(status_code=403, detail="项目路径不在允许的目录内")
            return folder.folder_path

        default_path = str(TEST_PROJECT_DIR)
        os.makedirs(default_path, exist_ok=True)
        return default_path

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
            if len(zip_content) > MAX_PROJECT_ZIP_BYTES:
                raise HTTPException(status_code=413, detail=f"ZIP 超过大小限制({MAX_PROJECT_ZIP_BYTES // 1024 // 1024}MB)")
            with open(temp_zip, "wb") as f:
                f.write(zip_content)

            # 解压（防 zip-slip:拒绝路径逃逸出项目目录的条目）
            with zipfile.ZipFile(temp_zip, 'r') as zf:
                folder_root = str(folder_path.resolve()) + os.sep
                for member in zf.namelist():
                    member_path = os.path.normpath(os.path.join(str(folder_path), member))
                    if not member_path.startswith(folder_root):
                        temp_zip.unlink(missing_ok=True)
                        raise HTTPException(status_code=400, detail=f"ZIP 包含非法路径条目: {member}")
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
            test_url = _resolve_test_url(effective_content, request.browser_url)

            if not test_url:
                async def _no_url_generator():
                    yield f"data: {json.dumps({'type': 'error', 'message': '请提供要测试的网站 URL'}, ensure_ascii=False)}\n\n"
                return StreamingResponse(_no_url_generator(), media_type="text/event-stream")

            project_path = _resolve_project_path(current_user.id, request.project_id, db)
            task_id = uuid.uuid4().hex[:16]
            task_state = new_task_state(
                task_id=task_id,
                user_id=current_user.id,
                target_url=test_url,
                project_path=project_path,
                test_goals=[effective_content],
                model_config_id=_get_user_active_model_id(current_user.id, db),
                max_steps=20,
                use_vision=_resolve_use_vision(request.use_vision),
                storage_state=request.storage_state or "",
            )
            return _test_sse_response(task_state, task_id, start_payload={"url": test_url, "message": f"开始测试 {test_url}"})

        # code / case / knowledge 意图:同步分析类功能,使用原始输入
        # (不注入 RAG 上下文,避免参考知识污染分析与入库内容)
        if intent in ("code", "case", "knowledge"):
            async def _analysis_generator():
                try:
                    yield f"data: {json.dumps({'type': 'meta', 'intent': intent, 'confidence': confidence, 'session_id': session_id}, ensure_ascii=False)}\n\n"

                    if intent == "code":
                        data = await asyncio.to_thread(analyze_bug, request.content, ai_config)
                        result_message = "Bug分析完成"
                    elif intent == "case":
                        data = await asyncio.to_thread(
                            generate_test_cases, request.content, ai_config, current_user.id
                        )
                        result_message = "测试用例生成完成"
                    else:
                        knowledge_content = _extract_knowledge_content(request.content)
                        doc_id = vector_db.add_document(knowledge_content, current_user.id, {"source": "chat"})
                        data = {
                            "doc_id": doc_id,
                            "content": knowledge_content,
                            "chunk_count": len(chunk_text(knowledge_content)),
                        }
                        result_message = "知识已添加到知识库"

                    conversation = Conversation(
                        user_id=current_user.id,
                        session_id=session_id,
                        module=intent,
                        input_text=request.content,
                        output_data=json.dumps(data, ensure_ascii=False),
                    )
                    db.add(conversation)
                    _update_session_name(db, session_id, request.content)
                    db.commit()

                    yield f"data: {json.dumps({'type': 'result', 'module': intent, 'data': data, 'message': result_message}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'data': data, 'message': result_message, 'conv_id': conversation.id}, ensure_ascii=False)}\n\n"
                except ValueError as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_analysis_generator(), media_type="text/event-stream")

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
    # (原 /test/run 同步接口已删除:与 /test/stream 重复且长任务不应占用同步连接,
    #  统一走 /chat/stream 的 web_test 意图分支或 /test/stream)

    @app.post("/test/code/fix", summary="确认代码修复")
    async def confirm_code_fix(
        request: CodeModifyRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """用户确认是否修改代码:恢复停在 interrupt 的任务,按顺序应用或跳过当前问题"""
        graph = await test_agent_manager.get_graph()
        config = make_config(request.task_id)
        snapshot = await graph.aget_state(config)

        if not snapshot or not snapshot.values:
            raise HTTPException(status_code=404, detail="测试任务不存在")
        values = snapshot.values
        if values.get("user_id") != current_user.id:
            raise HTTPException(status_code=404, detail="测试任务不存在")

        if values.get("status") != "awaiting_fix":
            raise HTTPException(status_code=400, detail="当前没有待确认的代码问题")

        cursor = values.get("fix_cursor", 0)
        issues = values.get("code_issues", [])
        if request.issue_index != cursor or cursor >= len(issues):
            raise HTTPException(status_code=400, detail=f"请按顺序确认代码问题，当前待确认为第 {cursor} 个")

        # 恢复执行:应用本次确认后,若还有剩余问题会再次停在 interrupt
        async for _chunk in graph.astream(
            Command(resume={"confirmed": request.confirmed}),
            config=config,
            stream_mode="updates",
        ):
            pass

        snapshot = await graph.aget_state(config)
        fix_results = snapshot.values.get("fix_results", []) if snapshot and snapshot.values else []
        fix_result = next(
            (fr for fr in fix_results if fr.get("issue_index") == request.issue_index),
            {},
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
        """查询测试任务当前状态(从 SQLite 检查点读取,服务重启后仍可查询)"""
        graph = await test_agent_manager.get_graph()
        config = make_config(task_id)
        snapshot = await graph.aget_state(config)

        if not snapshot or not snapshot.values:
            raise HTTPException(status_code=404, detail="测试任务不存在")

        values = dict(snapshot.values)
        if values.get("user_id") != current_user.id:
            raise HTTPException(status_code=404, detail="测试任务不存在")

        status = values.get("status", "running")
        message = values.get("message", "")

        if status == "running" and task_id not in active_runs:
            status = "interrupted"
            message = "任务因服务重启或连接中断而暂停，可通过 POST /test/resume/{task_id} 从最后一步恢复"
        elif status == "awaiting_fix":
            message = message or "存在待确认的代码问题，请通过 POST /test/code/fix 逐个确认"

        return _state_to_response(task_id, {**values, "status": status, "message": message})

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

        if not _is_allowed_project_path(project_path):
            raise HTTPException(status_code=403, detail="项目路径不在允许的目录内")

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
        """SSE 流式测试接口：实时推送每个测试步骤(任务状态持久化到检查点)"""
        test_url = _resolve_test_url(request.content, request.browser_url)

        if not test_url:
            async def _no_url_generator():
                yield f"data: {json.dumps({'type': 'error', 'message': '请提供要测试的网站 URL'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_no_url_generator(), media_type="text/event-stream")

        project_path = _resolve_project_path(current_user.id, request.project_id, db)

        task_id = uuid.uuid4().hex[:16]
        task_state = new_task_state(
            task_id=task_id,
            user_id=current_user.id,
            target_url=test_url,
            project_path=project_path,
            test_goals=[request.content],
            model_config_id=_get_user_active_model_id(current_user.id, db),
            max_steps=20,
            use_vision=_resolve_use_vision(request.use_vision),
            storage_state=request.storage_state or "",
        )
        return _test_sse_response(task_state, task_id, start_payload={"url": test_url, "message": f"开始测试 {test_url}"})

    @app.post("/test/resume/{task_id}", summary="恢复中断的测试任务（SSE）")
    async def resume_test(
        task_id: str,
        current_user: User = Depends(get_current_user),
    ):
        """从最后一个检查点恢复测试任务(服务重启或连接中断后可用)"""
        graph = await test_agent_manager.get_graph()
        snapshot = await graph.aget_state(make_config(task_id))

        if not snapshot or not snapshot.values:
            raise HTTPException(status_code=404, detail="测试任务不存在")
        values = snapshot.values
        if values.get("user_id") != current_user.id:
            raise HTTPException(status_code=404, detail="测试任务不存在")
        if values.get("status") == "awaiting_fix":
            raise HTTPException(status_code=400, detail="任务正在等待修复确认，请调用 /test/code/fix")
        if values.get("status") in ("completed", "cancelled", "failed"):
            raise HTTPException(status_code=400, detail="任务已结束，无法恢复")

        return _test_sse_response(None, task_id)

    @app.post("/test/stop/{task_id}", summary="停止正在运行的测试任务")
    async def stop_test(
        task_id: str,
        current_user: User = Depends(get_current_user),
    ):
        """停止指定测试任务(运行中的任务在下一个步骤边界生效)"""
        graph = await test_agent_manager.get_graph()
        config = make_config(task_id)
        snapshot = await graph.aget_state(config)

        if not snapshot or not snapshot.values:
            return {"success": False, "message": "测试任务不存在或已结束"}
        values = snapshot.values
        if values.get("user_id") != current_user.id:
            return {"success": False, "message": "测试任务不存在或已结束"}

        status = values.get("status", "running")

        if task_id in active_runs:
            # 协作式停止:测试步骤之间检查标志,经 finalize 完成浏览器清理
            stop_requested.add(task_id)
            return {"success": True, "message": "已发送停止信号"}

        if status == "awaiting_fix":
            # 停在人工确认:跳过剩余确认后标记为已停止
            remaining = len(values.get("code_issues", [])) - values.get("fix_cursor", 0)
            for _ in range(max(remaining, 0)):
                async for _chunk in graph.astream(
                    Command(resume={"confirmed": False}), config=config, stream_mode="updates"
                ):
                    pass
            await graph.aupdate_state(config, {"status": "cancelled", "message": "测试已停止"})
            return {"success": True, "message": "已停止并跳过剩余修复确认"}

        if status in ("running", "interrupted"):
            await graph.aupdate_state(config, {"status": "cancelled", "message": "测试已停止"})
            return {"success": True, "message": "已发送停止信号"}

        return {"success": False, "message": "测试任务不存在或已结束"}
