"""数据库 engine/session 工厂(PostgreSQL, SQLAlchemy)。

用法:
    from db import session_scope, init_db
    with session_scope() as s:
        s.merge(listing_obj)
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL

_engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(create_all: bool = True) -> bool:
    """建表(幂等)。返回是否成功;DB 不可用时返回 False 不抛异常。

    采集流程在 DB 不可用时降级为纯文件模式,不中断。
    """
    try:
        from db.listing import Base

        if create_all:
            Base.metadata.create_all(bind=_engine)
        return True
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def session_scope() -> Iterator[Session]:
    """带事务的 session 上下文: 正常 commit,异常 rollback。"""
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_listing(listing_data: dict) -> bool:
    """按 (source, item_id) upsert 一条房源。失败返回 False(不抛出,不阻塞采集)。

    listing_data: 与 db.listing.Listing 字段一致的 dict(data 为资源 JSON)。
    """
    try:
        from db.listing import Listing

        with session_scope() as s:
            existing = s.query(Listing).filter_by(
                source=listing_data["source"], item_id=listing_data["item_id"]
            ).first()
            if existing:
                for k, v in listing_data.items():
                    if v is not None:
                        setattr(existing, k, v)
            else:
                s.add(Listing(**listing_data))
        return True
    except Exception:  # noqa: BLE001
        return False


def get_source_images(source: str) -> dict:
    """返回 {item_id: [{"url", "file"|None}, ...]} —— DB 中各房源的图片清单。

    images 结构: 每张图 {url(远端), file(本地文件名, 失败为 None)}。
    断点续传用: DB 已采(images 非空)的子页可跳过,失败图可离线补下。
    """
    from sqlalchemy import text

    out: dict = {}
    try:
        with session_scope() as s:
            rows = s.execute(text(
                "SELECT item_id, data->>'images' FROM listings WHERE source=:src"
            ), {"src": source}).fetchall()
        import json

        for item_id, raw in rows:
            try:
                imgs = json.loads(raw) if raw else []
            except Exception:  # noqa: BLE001
                imgs = []
            if isinstance(imgs, list):
                out[item_id] = imgs
    except Exception:  # noqa: BLE001
        pass
    return out


def get_source_poi(source: str) -> dict:
    """返回 {item_id: poi_dict} —— DB 中已捕获周围情况(阿里)的记录。

    poi 结构: {"transportation","education","shopping","medical","parks"}。
    只要 data 里存在 `poi` 键即视为已采集(即使各项为空,避免重复刷新重抓)。
    断点续传用: 图片齐 + poi 在库 → 整页跳过;poi 缺失 → 需开浏览器补周围。
    """
    from sqlalchemy import text

    out: dict = {}
    try:
        with session_scope() as s:
            rows = s.execute(text(
                "SELECT item_id, data->>'poi' FROM listings "
                "WHERE source=:src AND data->'poi' IS NOT NULL"
            ), {"src": source}).fetchall()
        import json

        for item_id, raw in rows:
            try:
                poi = json.loads(raw) if raw else {}
            except Exception:  # noqa: BLE001
                poi = {}
            out[item_id] = poi
    except Exception:  # noqa: BLE001
        pass
    return out


def get_source_data(source: str) -> dict:
    """返回 {item_id: {"title", "data"}} —— DB 中各房源整份 data 与标题。

    增量补抓/断点续传用: 判断标题是否变化(变化=新数据,data 需重建)
    及各字段缺失情况,避免整块覆盖把已采的 description/property_info 清掉。
    """
    from sqlalchemy import text

    out: dict = {}
    try:
        with session_scope() as s:
            rows = s.execute(text(
                "SELECT item_id, title, data FROM listings WHERE source=:src"
            ), {"src": source}).fetchall()
        for item_id, title, data in rows:
            out[item_id] = {"title": title, "data": (data or {})}
    except Exception:  # noqa: BLE001
        pass
    return out


def listing_exists(source: str, item_id: str) -> bool:
    """判断 (source, item_id) 是否已在库。"""
    try:
        from db.listing import Listing

        with session_scope() as s:
            return s.query(Listing).filter_by(source=source, item_id=item_id).first() is not None
    except Exception:  # noqa: BLE001
        return False