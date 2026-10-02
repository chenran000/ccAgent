"""本地用户依赖(单用户本地版)

原 JWT 注册/登录体系已移除(参考 ZCode:本地单用户工具无应用级用户系统)。
保留 get_current_user 依赖名与签名,所有路由的 user_id 数据隔离逻辑不变:
固定返回数据库中最早创建的用户;库为空时自动创建内置 "local" 用户。
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


def get_current_user(db: Session = Depends(get_db)) -> User:
    """获取本地固定用户(替代原 JWT 鉴权依赖)"""
    user = db.query(User).order_by(User.id.asc()).first()
    if user is None:
        user = User(username="local", password_hash="")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
