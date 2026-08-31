"""Web 扩展数据模型: User, Task, Material, UserMaterial。

与核心业务模型(db.listing.Listing)分离,避免循环依赖。
"""
from __future__ import annotations

import datetime as _dt
import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from db.base import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, enum.Enum):
    CRAWL_GPAI = "crawl_gpai"
    CRAWL_ALI = "crawl_ali"
    CRAWL_ALL = "crawl_all"
    GENERATE_SCRIPT = "generate_script"
    GENERATE_TTS = "generate_tts"
    GENERATE_POSTER = "generate_poster"
    GENERATE_VIDEO = "generate_video"
    MUX_VIDEO = "mux_video"
    FULL_PIPELINE = "full_pipeline"


class MaterialType(str, enum.Enum):
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_username", "username", unique=True),)

    id: int = Column(BigInteger, primary_key=True, autoincrement=True)
    username: str = Column(String(64), nullable=False)
    email: str | None = Column(String(128), nullable=True)
    hashed_password: str = Column(String(128), nullable=False)
    role: UserRole = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active: bool = Column(Boolean, default=True, nullable=False)
    created_at: _dt.datetime = Column(DateTime, default=_dt.datetime.now, nullable=False)
    updated_at: _dt.datetime = Column(
        DateTime, default=_dt.datetime.now, onupdate=_dt.datetime.now, nullable=False
    )

    tasks = relationship("Task", back_populates="owner", lazy="dynamic")
    materials = relationship(
        "UserMaterial",
        foreign_keys="UserMaterial.user_id",
        back_populates="user",
        lazy="dynamic",
    )
    assigned_materials = relationship(
        "UserMaterial",
        foreign_keys="UserMaterial.assigned_by",
        back_populates="assigner",
        lazy="dynamic",
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_owner_id", "owner_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_created_at", "created_at"),
    )

    id: int = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: int = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: TaskType = Column(SQLEnum(TaskType), nullable=False)
    status: TaskStatus = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    params: dict = Column(JSON, default=dict, nullable=False)
    result: dict = Column(JSON, default=dict, nullable=False)
    progress: int = Column(Integer, default=0, nullable=False)
    current_step: str = Column(String(128), default="", nullable=False)
    error_message: str | None = Column(Text, nullable=True)
    max_retries: int = Column(Integer, default=3, nullable=False)
    retry_count: int = Column(Integer, default=0, nullable=False)
    created_at: _dt.datetime = Column(DateTime, default=_dt.datetime.now, nullable=False)
    started_at: _dt.datetime | None = Column(DateTime, nullable=True)
    finished_at: _dt.datetime | None = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="tasks")


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        Index("ix_materials_type", "type"),
        Index("ix_materials_uploader_id", "uploader_id"),
        Index("ix_materials_created_at", "created_at"),
    )

    id: int = Column(BigInteger, primary_key=True, autoincrement=True)
    name: str = Column(String(256), nullable=False)
    type: MaterialType = Column(SQLEnum(MaterialType), nullable=False)
    file_path: str = Column(String(512), nullable=False)
    file_size: int = Column(BigInteger, default=0, nullable=False)
    mime_type: str | None = Column(String(128), nullable=True)
    meta: dict = Column(JSON, default=dict, nullable=False)
    uploader_id: int = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_public: bool = Column(Boolean, default=False, nullable=False)
    tags: list = Column(JSON, default=list, nullable=False)
    created_at: _dt.datetime = Column(DateTime, default=_dt.datetime.now, nullable=False)

    uploader = relationship("User", foreign_keys=[uploader_id])
    shares = relationship("UserMaterial", back_populates="material", lazy="dynamic")


class UserMaterial(Base):
    __tablename__ = "user_materials"
    __table_args__ = (
        UniqueConstraint("user_id", "material_id", name="uq_user_material"),
        Index("ix_user_materials_user_id", "user_id"),
        Index("ix_user_materials_material_id", "material_id"),
    )

    id: int = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id: int = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    material_id: int = Column(BigInteger, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False)
    permission: str = Column(String(32), default="view", nullable=False)
    assigned_at: _dt.datetime = Column(DateTime, default=_dt.datetime.now, nullable=False)
    assigned_by: int = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="materials")
    material = relationship("Material", back_populates="shares")
    assigner = relationship("User", foreign_keys=[assigned_by])