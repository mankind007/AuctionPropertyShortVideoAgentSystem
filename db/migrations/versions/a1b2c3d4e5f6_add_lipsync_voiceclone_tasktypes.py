"""口型对齐任务类型扩展: GENERATE_LIPSYNC / GENERATE_VOICE_CLONE。

Revision ID: a1b2c3d4e5f6
Revises: 3f4598fc184f
Create Date: 2026-09-23

PostgreSQL 上 Postgres 的 native ENUM 不支持 ALTER TYPE ... ADD VALUE
在事务中执行, 因此对 tasktype 用 ALTER TYPE ... ADD VALUE IF NOT EXISTS。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3f4598fc184f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 与 db.models.TaskType 新增值保持一致(名字是 Python 枚举成员名)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'GENERATE_LIPSYNC'")
        op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'GENERATE_VOICE_CLONE'")
    else:
        # SQLite / 其他: 重建枚举(开发库常用 SQLite 时由 alembic metadata 处理)
        # SQLAlchemy Enum 在非 PG 上通常已是 VARCHAR 检查; 若已有值则跳过
        pass


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PG 不支持直接 DROP 一个仍在使用的 ENUM value; 需要重建类型。
        # 开发环境一般只 upgrade 不 downgrade 新枚举值; 此处保留空实现并提示。
        raise RuntimeError(
            "PostgreSQL 不支持删除 ENUM value。如需回退, 请手动重建 tasktype 类型。"
        )
