"""共享的 SQLAlchemy DeclarativeBase。

所有 ORM 模型应继承此 Base,确保 metadata 统一,便于 Alembic 自动检测。
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass