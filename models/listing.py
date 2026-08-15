"""顶层 ORM 实体(单表去重)。

设计说明(见 plans/2026-08-15-爬虫公共抽象与去重入库.txt):
- 单表 listings,`(source, item_id)` 唯一约束天然去重,重复采集自动跳过。
- 资源字段(图片数组/raw/资产路径/后续 voice/video 路径)统一放 `data` JSONB。
- 顶层 models/ 目录,不放 src/(用户指定)。
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import JSON, BigInteger, DateTime, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Listing(Base):
    """单个法拍房源(公拍网 gpai / 阿里资产 ali 共用)。"""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "item_id", name="uq_listing_source_item"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_price: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    ref_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    ref_price_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_time: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    crawled_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # 资源字段 JSONB: images 数组 / raw / 资产路径 / 后续 voice/video 路径
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_dt.datetime.now)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.now, onupdate=_dt.datetime.now
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Listing source={self.source} item_id={self.item_id} title={self.title!r}>"