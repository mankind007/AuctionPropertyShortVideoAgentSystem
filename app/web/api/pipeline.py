"""管线进度与批量触发接口。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from db import session_scope
from db.listing import Listing
from app.web.deps import get_db, get_current_user
from app.web.schemas import PipelineStatus, PipelineStage


router = APIRouter(prefix="/pipeline", tags=["管线"])


STAGES = ["script", "script_images", "video", "voice", "video_voiced"]


@router.get("", response_model=PipelineStatus)
def get_pipeline_status(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """获取全量管线进度。"""
    total = db.query(func.count(Listing.id)).scalar() or 0
    stages = []
    for st in STAGES:
        # 使用 JSON 字段的 exists 判断
        from sqlalchemy import text
        rows = db.query(
            Listing.source,
            func.count(Listing.id)
        ).filter(
            Listing.data[st].isnot(None)  # type: ignore
        ).group_by(Listing.source).all()
        counts = {src: cnt for src, cnt in rows}
        stages.append(PipelineStage(
            stage=st,
            gpai=counts.get("gpai", 0),
            ali=counts.get("ali", 0),
        ))
    return PipelineStatus(total_listings=total, stages=stages)


STAGE_TO_TYPE = {
    "crawl": "crawl_all",
    "script": "generate_script",
    "poster": "generate_poster",
    "video": "generate_video",
    "tts": "generate_tts",
    "mux": "mux_video",
}


class TriggerRequest(BaseModel):
    source: str = "all"
    stages: list[str] = Field(default_factory=list)
    limit: int = 100


@router.post("/trigger")
def trigger_pipeline(
    req: TriggerRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """批量触发管线任务。

    每个选中的 stage 按 source 拆分为独立 Task 记录，由 TaskRunner 顺序执行。
    """
    from db.models import Task, TaskStatus, TaskType
    from app.web.api.tasks import _run_task_bg

    if not req.stages:
        stages = list(STAGE_TO_TYPE.keys())
    else:
        stages = req.stages

    # source -> TaskType 映射
    source_type_map = {
        "all": TaskType.CRAWL_ALL,
        "gpai": TaskType.CRAWL_GPAI,
        "ali": TaskType.CRAWL_ALI,
    }

    type_map = {
        "crawl": source_type_map.get(req.source, TaskType.CRAWL_ALL),
        "script": TaskType.GENERATE_SCRIPT,
        "poster": TaskType.GENERATE_POSTER,
        "video": TaskType.GENERATE_VIDEO,
        "tts": TaskType.GENERATE_TTS,
        "mux": TaskType.MUX_VIDEO,
    }

    created_tasks = []
    for stage in stages:
        task_type = type_map.get(stage)
        if not task_type:
            continue

        params = {"limit": req.limit, "source": req.source, "all": True, "force": False}
        task = Task(
            owner_id=current_user.id,
            type=task_type,
            status=TaskStatus.PENDING,
            params=params,
            result={},
            progress=0,
            current_step="",
            max_retries=3,
            retry_count=0,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        background_tasks.add_task(_run_task_bg, task.id)
        created_tasks.append({"id": task.id, "source": req.source, "stage": stage, "type": task_type.value})

    return {"tasks": created_tasks}
