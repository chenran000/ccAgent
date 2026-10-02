"""AI 配置加载器

按 model_config_id 从业务库现取配置并解密,避免 API Key 明文进入
LangGraph 检查点(data/checkpoints.db)。任务恢复后同样按 id 现取。
"""
from app.credential_cipher import decrypt_credential
from app.database import SessionLocal
from app.models import ModelConfig


def load_ai_config(model_config_id: int, user_id: int) -> dict:
    """加载指定模型配置;不存在或解密失败返回空 dict(由调用方判定失败)"""
    if not model_config_id:
        return {}
    db = SessionLocal()
    try:
        mc = db.query(ModelConfig).filter_by(id=model_config_id, user_id=user_id).first()
        if not mc:
            return {}
        try:
            api_key = decrypt_credential(mc.api_key)
        except ValueError:
            return {}
        return {
            "api_key": api_key,
            "api_base_url": mc.api_base_url,
            "chat_model": mc.model_name,
        }
    finally:
        db.close()
