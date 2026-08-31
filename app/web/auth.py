"""JWT 认证工具：签发/校验 access token，密码哈希。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.hash import bcrypt as bcrypt_hash

from app.web.config import get_settings


settings = get_settings()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """生成 JWT access token。"""
    to_encode = data.copy()
    # jose 要求 sub 必须是字符串
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGO)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """校验 token，返回 payload 或 None。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGO])
        return payload
    except JWTError:
        return None


def hash_password(password: str) -> str:
    """bcrypt 哈希密码。"""
    return bcrypt_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码是否匹配哈希。"""
    return bcrypt_hash.verify(plain_password, hashed_password)