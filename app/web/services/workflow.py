"""单房源工作流状态聚合服务。

对单个房源聚合 话术 → 海报 → 配音 → 视频 → 合成配音版 各阶段状态：
- 已完成判定依据 `listing.data` 中对应键是否存在
- 进行中/失败判定依据该房源最近的 Task 记录
- 产物预览从 `assets/{source}/{item_id}/{stage}` 目录扫描
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from db.listing import Listing
from db.models import Task, TaskStatus
from app.web.schemas import WorkflowPreview, WorkflowStage, ListingWorkflow


ASSETS_ROOT = Path(__file__).resolve().parents[3] / "assets"

# 阶段定义：key -> (名称, data 判定键, 依赖键列表)
ALL_STAGE_DEFS = [
    ("script", "话术", "script", []),
    ("poster", "海报", "script_images", ["script"]),
    ("voice", "配音", "voice", ["script"]),
    ("video", "视频", "video", ["poster"]),
    ("mux", "合成配音版", "video_voiced", ["video", "voice"]),
]

STAGE_DIR_MAP = {
    "script": None,
    "poster": "posters",
    "voice": "voice",
    "video": "videos",
    "mux": "videos",
}

# stage key -> 对应任务类型
STAGE_TO_TYPE = {
    "script": "generate_script",
    "poster": "generate_poster",
    "voice": "generate_tts",
    "video": "generate_video",
    "mux": "mux_video",
}


def _preview_url(source: str, item_id: str, stage: str, filename: str) -> str:
    return f"/api/materials/asset/{source}/{item_id}/{stage}/{filename}"


def _media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return "image"
    if suffix in (".mp4", ".webm", ".mov"):
        return "video"
    if suffix in (".mp3", ".wav", ".ogg"):
        return "audio"
    return "file"


def _scan_previews(source: str, item_id: str, stage_dir: str) -> list[WorkflowPreview]:
    """扫描 assets/{source}/{item_id}/{stage_dir}，返回预览列表。"""
    d = ASSETS_ROOT / source / item_id / stage_dir
    if not d.exists() or not d.is_dir():
        return []
    previews = []
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        previews.append(WorkflowPreview(
            url=_preview_url(source, item_id, stage_dir, f.name),
            label=f.name,
            type=_media_type(f.name),
            file=f.name,
        ))
    return previews


def _is_done(data: dict, key: str) -> bool:
    val = data.get(key)
    if not val:
        return False
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        return bool(val)
    return True


def _recent_task(db: Session, listing: Listing, stage: str):
    """查找该房源该阶段最近的 PENDING/RUNNING/FAILED 任务。

    任务数量有限，直接按 type 拉最近记录，Python 侧匹配 item_id，
    避免 JSON 路径查询在 sqlite/postgres 上的兼容性问题。
    """
    task_type = STAGE_TO_TYPE.get(stage)
    if not task_type:
        return None
    tasks = (
        db.query(Task)
        .filter(Task.type == task_type)
        .order_by(Task.created_at.desc())
        .limit(20)
        .all()
    )
    for t in tasks:
        if (t.params or {}).get("item_id") != listing.item_id:
            continue
        if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED):
            return t
    return None


def get_listing_workflow(listing: Listing, db: Session) -> ListingWorkflow:
    """聚合单房源工作流各阶段状态。"""
    data = listing.data or {}
    source = listing.source
    item_id = listing.item_id
    voiceover_enabled = data.get("voiceover_enabled", True)

    # 按 voiceover_enabled 动态裁剪 stages
    if voiceover_enabled:
        # 配音开启: script → poster → voice → video (4步，视频直接出配音版)
        stage_defs = [(k, n, dk, deps) for k, n, dk, deps in ALL_STAGE_DEFS if k in ("script", "poster", "voice", "video")]
        # video 依赖改为 voice
        stage_defs = [(k, n, dk, ["voice"] if k == "video" else deps) for k, n, dk, deps in stage_defs]
    else:
        # 配音关闭: script → poster → video (3步，纯视频)
        stage_defs = [(k, n, dk, deps) for k, n, dk, deps in ALL_STAGE_DEFS if k in ("script", "poster", "video")]
        # video 依赖改为 poster
        stage_defs = [(k, n, dk, ["poster"] if k == "video" else deps) for k, n, dk, deps in stage_defs]

    # 各阶段 done 状态（供依赖判断）
    done_map: dict[str, bool] = {
        key: _is_done(data, data_key) for key, name, data_key, _deps in stage_defs
    }

    stages: list[WorkflowStage] = []
    for key, name, data_key, deps in stage_defs:
        stage_dir = STAGE_DIR_MAP[key]

        if _is_done(data, data_key):
            status = "done"
            progress = 100
            task_id = None
            current_step = "已完成"
            error_message = None
        else:
            task = _recent_task(db, listing, key)
            if task and task.status == TaskStatus.RUNNING:
                status = "running"
                progress = task.progress
                current_step = task.current_step or "执行中"
                task_id = task.id
                error_message = None
            elif task and task.status == TaskStatus.PENDING:
                # 已创建任务但排队等待上游，不算执行中
                status = "waiting"
                progress = task.progress
                current_step = "等待上游"
                task_id = task.id
                error_message = None
            elif task and task.status == TaskStatus.FAILED:
                status = "failed"
                progress = task.progress
                current_step = "失败"
                task_id = task.id
                error_message = task.error_message
            else:
                status = "pending"
                progress = 0
                current_step = "未开始"
                task_id = None
                error_message = None

        # 依赖是否满足（仅 pending/failed 时需要判断）
        deps_ok = True
        if status in ("pending", "failed"):
            deps_ok = all(done_map.get(dep, False) for dep in deps)

        previews: list[WorkflowPreview] = []
        if status == "done":
            if key == "script":
                text = (data.get("script") or "").strip()
                if text:
                    previews.append(WorkflowPreview(
                        url="#", label="查看话术", type="text", file="script",
                        content=text,
                    ))
            elif stage_dir:
                previews = _scan_previews(source, item_id, stage_dir)
                if key == "video" and voiceover_enabled:
                    # 配音开启: 视频阶段仅展示带配音版
                    previews = [p for p in previews if "_voiced" in p.file]

        stages.append(WorkflowStage(
            key=key,
            name=name,
            status=status,
            progress=progress,
            current_step=current_step,
            can_run=status != "done" and deps_ok,
            task_id=task_id,
            error_message=error_message,
            previews=previews,
        ))

    return ListingWorkflow(
        listing_id=listing.id,
        source=source,
        item_id=item_id,
        title=listing.title,
        voiceover_enabled=voiceover_enabled,
        stages=stages,
    )
