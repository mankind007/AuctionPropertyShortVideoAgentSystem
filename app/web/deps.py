"""FastAPI 依赖注入：数据库会话、当前用户、分页、权限。"""
from __future__ import annotations

from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from db import session_scope
from db.models import User, UserRole
from app.web.auth import verify_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """数据库会话依赖。"""
    with session_scope() as s:
        yield s


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """从 token 解析当前用户。支持 header (Bearer) 和 query param (?token=) 两种方式。"""
    resolved = token
    # 如果 header 没有 token，尝试从 query param 获取
    if not resolved:
        resolved = request.query_params.get("token")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not resolved:
        raise credentials_exception
    payload = verify_token(resolved)
    if payload is None:
        raise credentials_exception
    sub = payload.get("sub")
    if sub is None:
        raise credentials_exception
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise credentials_exception
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=403, detail="用户已被禁用")
    return user


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求管理员角色。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


class Pagination:
    """分页参数。"""

    def __init__(self, page: int = 1, page_size: int = 20):
        self.page = max(1, page)
        self.page_size = min(max(1, page_size), 100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def get_pagination(page: int = 1, page_size: int = 20) -> Pagination:
    return Pagination(page, page_size)