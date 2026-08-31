"""任务类型 -> CLI 命令映射注册表。

每个 TaskType 有专用 builder，确保参数与实际脚本 CLI 严格一致。
"""
from __future__ import annotations

from db.models import TaskType
from app.web.services.crawl import (
    build_crawl_gpai_cmd,
    build_crawl_ali_cmd,
    build_crawl_all_cmd,
)
from app.web.services.script_gen import build_script_cmd
from app.web.services.tts import build_tts_cmd
from app.web.services.poster import build_poster_cmd
from app.web.services.video import build_make_video_cmd, build_mux_voice_cmd


# ── 采集 ──

def _crawl_gpai(p: dict) -> list[str]:
    return build_crawl_gpai_cmd(
        pages=p.get("pages", 0),
        download=p.get("download", False),
        db=p.get("db", True),
        headless=p.get("headless", True),
        skip_complete=p.get("skip_complete", False),
    )


def _crawl_ali(p: dict) -> list[str]:
    return build_crawl_ali_cmd(
        category=p.get("category", "住宅"),
        pages=p.get("pages", 2),
        download=p.get("download", False),
        db=p.get("db", True),
        headless=p.get("headless", False),
        skip_complete=p.get("skip_complete", False),
    )


def _crawl_all(p: dict) -> list[str]:
    return build_crawl_all_cmd(
        gpai_pages=p.get("gpai_pages", p.get("pages", 1)),
        ali_pages=p.get("ali_pages", p.get("pages", 1)),
        ali_category=p.get("ali_category", "住宅"),
        download=p.get("download", False),
        db=p.get("db", True),
        headless=p.get("headless", False),
        skip_complete=p.get("skip_complete", False),
        only=p.get("only"),
    )


# ── 话术 ──

def _generate_script(p: dict) -> list[str]:
    return build_script_cmd(
        source=p.get("source", "all"),
        all_items=p.get("all", True),
        limit=p.get("limit", 1000),
        force=p.get("force", False),
        llm=p.get("llm", False),
        workers=p.get("workers", 4),
        item_id=p.get("item_id"),
    )


# ── TTS ──

def _generate_tts(p: dict) -> list[str]:
    return build_tts_cmd(
        source=p.get("source", "all"),
        all_items=p.get("all", True),
        limit=p.get("limit", 1000),
        force=p.get("force", False),
        voice=p.get("voice", "zh-CN-YunxiNeural"),
        item_id=p.get("item_id"),
    )


# ── 海报 ──

def _generate_poster(p: dict) -> list[str]:
    return build_poster_cmd(
        source=p.get("source", "all"),
        all_items=p.get("all", True),
        limit=p.get("limit", 1000),
        force=p.get("force", False),
        width=p.get("width"),
        item_id=p.get("item_id"),
    )


# ── 视频 ──

def _generate_video(p: dict) -> list[str]:
    return build_make_video_cmd(
        source=p.get("source", "all"),
        all_items=p.get("all", True),
        limit=p.get("limit", 1000),
        force=p.get("force", False),
        workers=p.get("workers", 1),
        duration=p.get("duration", 4.0),
        fps=p.get("fps", 25),
        item_id=p.get("item_id"),
    )


def _mux_video(p: dict) -> list[str]:
    return build_mux_voice_cmd(
        source=p.get("source", "all"),
        all_items=p.get("all", True),
        limit=p.get("limit", 1000),
        force=p.get("force", False),
        fps=p.get("fps", 25),
        item_id=p.get("item_id"),
    )


# ── 全流程 ──

def _full_pipeline(p: dict) -> list[str]:
    return _crawl_all(p)


# ── 注册表 ──

TASK_REGISTRY: dict[TaskType, callable] = {
    TaskType.CRAWL_GPAI: _crawl_gpai,
    TaskType.CRAWL_ALI: _crawl_ali,
    TaskType.CRAWL_ALL: _crawl_all,
    TaskType.GENERATE_SCRIPT: _generate_script,
    TaskType.GENERATE_TTS: _generate_tts,
    TaskType.GENERATE_POSTER: _generate_poster,
    TaskType.GENERATE_VIDEO: _generate_video,
    TaskType.MUX_VIDEO: _mux_video,
    TaskType.FULL_PIPELINE: _full_pipeline,
}


def build_command(task_type: TaskType, params: dict) -> list[str]:
    """根据任务类型和参数构造 CLI 命令。"""
    builder = TASK_REGISTRY.get(task_type)
    if builder:
        return builder(params)
    return ["python", "-c", "print('unknown task type:', '" + str(task_type.value) + "')"]
