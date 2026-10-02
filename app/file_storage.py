"""文件存储模块 - 管理用户上传的文件"""
import logging
import os
import uuid
from datetime import datetime, timezone

from app.config import UPLOAD_DIR
from app.file_parser import parse_file

logger = logging.getLogger(__name__)

# 支持的文件类型
SUPPORTED_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}

SUPPORTED_EXTENSIONS = {".pdf", ".txt"}


def get_user_upload_dir(user_id: int):
    """获取用户专属的上传目录"""
    user_dir = UPLOAD_DIR / str(user_id)
    user_dir.mkdir(exist_ok=True)
    return user_dir


def save_file(file_bytes: bytes, filename: str, user_id: int) -> dict:
    """
    保存文件到用户专属目录

    Args:
        file_bytes: 文件字节内容
        filename: 原始文件名
        user_id: 用户 ID

    Returns:
        文件信息字典
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型: {ext}，仅支持 {SUPPORTED_EXTENSIONS}")

    # 生成唯一存储文件名
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    user_dir = get_user_upload_dir(user_id)
    file_path = user_dir / stored_filename

    # 写入文件
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # 尝试提取文本
    extracted_text = ""
    try:
        extracted_text = parse_file(str(file_path), filename)
    except Exception as e:
        # 如果解析失败，记录错误但文件仍然保存
        logger.warning("文件解析失败但文件已保存: %s: %s", filename, e)
        extracted_text = f"[解析失败: {e}]"

    return {
        "original_filename": filename,
        "stored_filename": stored_filename,
        "file_path": str(file_path),
        "file_type": ext.lstrip("."),
        "file_size": len(file_bytes),
        "extracted_text": extracted_text,
    }


def delete_file(file_path: str) -> bool:
    """
    删除文件

    Args:
        file_path: 文件路径

    Returns:
        是否成功删除
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception:
        pass
    return False
