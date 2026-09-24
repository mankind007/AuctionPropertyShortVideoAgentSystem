"""房源接口：列表、详情、筛选、导出。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, BackgroundTasks
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from db import session_scope
from db.listing import Listing
from app.web.deps import get_db, get_pagination, get_current_user
from app.web.schemas import (
    ListingOut,
    ListingDetail,
    PaginatedListings,
    ListingQuery,
    WorkflowRunRequest,
    ListingWorkflow,
    TaskOut,
)


router = APIRouter(prefix="/listings", tags=["房源"])


def _apply_filters(query, q: ListingQuery):
    if q.source:
        query = query.filter(Listing.source == q.source)
    if q.status:
        query = query.filter(Listing.status == q.status)
    if q.min_price is not None:
        query = query.filter(Listing.start_price >= q.min_price)
    if q.max_price is not None:
        query = query.filter(Listing.start_price <= q.max_price)
    if q.start_time_from:
        query = query.filter(Listing.start_time >= q.start_time_from)
    if q.start_time_to:
        query = query.filter(Listing.start_time <= q.start_time_to)
    if q.keyword:
        kw = f"%{q.keyword}%"
        query = query.filter(
            or_(
                Listing.title.ilike(kw),
                Listing.item_id.ilike(kw),
            )
        )
    return query


def _to_out(listing: Listing) -> ListingOut:
    data = listing.data or {}
    return ListingOut(
        id=listing.id,
        source=listing.source,
        item_id=listing.item_id,
        title=listing.title,
        category=listing.category,
        start_price=float(listing.start_price or 0),
        ref_price=float(listing.ref_price) if listing.ref_price else None,
        ref_price_type=listing.ref_price_type,
        start_time=listing.start_time,
        status=listing.status,
        crawled_at=listing.crawled_at,
        has_script=bool(data.get("script")),
        has_images=bool(data.get("images")),
        has_posters=bool(data.get("script_images")),
        has_videos=bool(data.get("video")),
        has_voice=bool(data.get("voice")),
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


def _to_detail(listing: Listing) -> ListingDetail:
    out = _to_out(listing)
    return ListingDetail(
        **out.model_dump(),
        data=listing.data or {},
    )


@router.get("", response_model=PaginatedListings)
def list_listings(
    q: ListingQuery = Depends(),
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
):
    """分页查询房源列表（支持按开始时间/采集时间/起拍价排序）。"""
    query = db.query(Listing)
    query = _apply_filters(query, q)
    total = query.count()
    # 排序
    sort_col = {
        "created_at": Listing.created_at,
        "start_time": Listing.start_time,
        "start_price": Listing.start_price,
    }.get(q.sort_by, Listing.created_at)
    direction = "desc" if q.sort_order != "asc" else "asc"
    order_col = sort_col.asc() if direction == "asc" else sort_col.desc()
    # 固定二次排序，避免同值导致分页错乱
    query = query.order_by(order_col, Listing.id.desc())
    items = query.offset(pagination.offset).limit(pagination.limit).all()
    return PaginatedListings(
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=[_to_out(i) for i in items],
    )


@router.get("/export")
def export_listings(
    q: ListingQuery = Depends(),
    db: Session = Depends(get_db),
):
    """导出 CSV（简化版，实际可用 csv 模块生成）。"""
    query = db.query(Listing)
    query = _apply_filters(query, q)
    items = query.order_by(Listing.created_at.desc()).limit(5000).all()
    lines = ["id,source,item_id,title,category,start_price,ref_price,ref_price_type,start_time,status,crawled_at"]
    for l in items:
        lines.append(
            f"{l.id},{l.source},{l.item_id},{l.title or ''},{l.category or ''},"
            f"{float(l.start_price or 0)},{float(l.ref_price) if l.ref_price else ''},"
            f"{l.ref_price_type or ''},{l.start_time or ''},{l.status or ''},{l.crawled_at or ''}"
        )
    csv_content = "\n".join(lines)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=listings.csv"},
    )


@router.get("/{listing_id}", response_model=ListingDetail)
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    """获取房源详情（含完整 data）。"""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        from fastapi import HTTPException
        raise HTTPException(404, "房源不存在")
    return _to_detail(listing)


@router.get("/{listing_id}/images")
def get_listing_images(listing_id: int, db: Session = Depends(get_db)):
    """获取房源图片列表（含本地文件路径）。"""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        from fastapi import HTTPException
        raise HTTPException(404, "房源不存在")
    images = (listing.data or {}).get("images", [])
    return {"images": images}


@router.get("/{listing_id}/posters")
def get_listing_posters(listing_id: int, db: Session = Depends(get_db)):
    """获取房源海报列表。"""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        from fastapi import HTTPException
        raise HTTPException(404, "房源不存在")
    posters = (listing.data or {}).get("script_images", [])
    return {"posters": posters}


@router.get("/{listing_id}/videos")
def get_listing_videos(listing_id: int, db: Session = Depends(get_db)):
    """获取房源视频列表。"""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        from fastapi import HTTPException
        raise HTTPException(404, "房源不存在")
    videos = (listing.data or {}).get("video", [])
    return {"videos": videos}


@router.get("/{listing_id}/voice")
def get_listing_voice(listing_id: int, db: Session = Depends(get_db)):
    """获取房源配音列表。"""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        from fastapi import HTTPException
        raise HTTPException(404, "房源不存在")
    voice = (listing.data or {}).get("voice", [])
    return {"voice": voice}


@router.get("/{listing_id}/workflow", response_model=ListingWorkflow)
def get_listing_workflow(listing_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """获取单房源工作流状态：话术→海报→配音→视频→合成配音版。"""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        from fastapi import HTTPException
        raise HTTPException(404, "房源不存在")
    from app.web.services.workflow import get_listing_workflow
    return get_listing_workflow(listing, db)


@router.patch("/{listing_id}/voiceover")
def toggle_voiceover(
    listing_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """切换房源「是否配音」开关 + 「配音方式」backend，保存到 listing.data。"""
    from fastapi import HTTPException as _HE
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise _HE(404, "房源不存在")
    d = dict(listing.data or {})
    if "enabled" in body:
        d["voiceover_enabled"] = bool(body.get("enabled", True))
    backend = body.get("backend")
    if backend is not None:
        if backend not in ("edge", "clone"):
            raise _HE(400, "backend 必须是 edge 或 clone")
        d["voice_backend"] = backend
        # ref 克隆参考(可选)
        if body.get("ref_audio") is not None:
            d["voice_clone_ref_audio"] = body.get("ref_audio") or ""
        if body.get("ref_text") is not None:
            d["voice_clone_ref_text"] = body.get("ref_text") or ""
        if body.get("x_vector_only") is not None:
            d["voice_clone_x_vector_only"] = bool(body.get("x_vector_only"))
    listing.data = d
    db.commit()
    return {
        "voiceover_enabled": d.get("voiceover_enabled", True),
        "voice_backend": d.get("voice_backend", "edge"),
    }


@router.post("/{listing_id}/workflow/run", response_model=TaskOut, status_code=201)
def run_workflow_stage(
    listing_id: int,
    req: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """触发单房源指定阶段任务（复用 TaskRunner + registry 的 --item-id 单条能力）。"""
    from fastapi import HTTPException
    from db.models import Task, TaskStatus, TaskType
    from app.web.api.tasks import _run_task_bg
    from app.web.services.workflow import (
        STAGE_TO_TYPE,
        VOICE_BACKEND_TO_TYPE,
        get_listing_workflow,
    )

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(404, "房源不存在")

    # voice 阶段按 backend 选 TaskType；其余用 STAGE_TO_TYPE
    backend = req.backend or (listing.data or {}).get("voice_backend", "edge") or "edge"
    if req.stage == "voice":
        type_name = VOICE_BACKEND_TO_TYPE.get(backend, "generate_tts")
        if type_name not in ("generate_tts", "generate_voice_clone"):
            raise HTTPException(400, f"未知 voice backend: {backend}")
        task_type = TaskType(type_name)
    else:
        type_name = STAGE_TO_TYPE.get(req.stage)
        if not type_name:
            raise HTTPException(400, f"未知阶段: {req.stage}")
        task_type = TaskType(type_name)

    # 依赖校验：仅当依赖满足（或该阶段已可运行）才允许触发
    wf = get_listing_workflow(listing, db)
    stage_info = next((s for s in wf.stages if s.key == req.stage), None)
    if not stage_info:
        raise HTTPException(400, f"未知阶段: {req.stage}")
    if not stage_info.can_run:
        if stage_info.status == "done":
            raise HTTPException(400, "该阶段已完成，请先删除产物或使用 --force")
        deps_missing = {
            "poster": "script",
            "voice": "script",
            "lipsync": "voice",
            "video": "poster",
            "mux": "video/lipsync",
        }
        raise HTTPException(400, f"前置阶段未完成: {deps_missing.get(req.stage, '上游')}")

    vo_enabled = (listing.data or {}).get("voiceover_enabled", True)
    params = {"item_id": listing.item_id, "source": listing.source, "all": False, "force": False}
    if req.stage == "video":
        params["voiceover_enabled"] = vo_enabled
    if req.stage == "voice" and task_type == TaskType.GENERATE_VOICE_CLONE:
        d = listing.data or {}
        params["x_vector_only"] = bool(d.get("voice_clone_x_vector_only", True))
        if d.get("voice_clone_ref_audio"):
            params["ref_audio"] = d["voice_clone_ref_audio"]
        if d.get("voice_clone_ref_text"):
            params["ref_text"] = d["voice_clone_ref_text"]
    if req.stage == "lipsync":
        d = listing.data or {}
        images = d.get("images", [])
        params["image"] = images[0] if images else ""
        voice_data = d.get("voice", [])
        params["audio"] = voice_data[0] if voice_data else ""
        params["face_image"] = d.get("face_image", "")

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
    return task


@router.post("/{listing_id}/workflow/run-all", status_code=201)
def run_workflow_all(
    listing_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """一键触发整个工作流：按依赖顺序串行执行缺失阶段（话术→海报→配音→视频→合成）。

    使用串行任务链：每个任务 params 记 `_next_task_id`，前一任务成功后自动跑下一任务。
    """
    from fastapi import HTTPException
    from db.models import Task, TaskStatus, TaskType
    from app.web.api.tasks import _run_task_bg
    from app.web.services.workflow import (
        STAGE_TO_TYPE,
        VOICE_BACKEND_TO_TYPE,
        get_listing_workflow,
    )

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(404, "房源不存在")

    voiceover_enabled = (listing.data or {}).get("voiceover_enabled", True)
    voice_backend = (listing.data or {}).get("voice_backend", "edge") or "edge"
    wf = get_listing_workflow(listing, db)
    # 执行顺序：使用工作流实际返回的 stages（已按 voiceover_enabled 裁剪）
    order = [s.key for s in wf.stages]
    # 跳过已完成；失败/未开始视为待执行
    pending_keys = [s.key for s in wf.stages if s.status in ("pending", "failed")]
    to_run = [k for k in order if k in pending_keys]
    if not to_run:
        raise HTTPException(400, "该房源工作流已完成，无需重新生成")

    # 依次创建任务并串联
    created = []
    prev_task = None
    for stage in to_run:
        if stage == "voice":
            type_name = VOICE_BACKEND_TO_TYPE.get(voice_backend, "generate_tts")
            task_type = TaskType(type_name)
        else:
            type_name = STAGE_TO_TYPE.get(stage)
            if not type_name:
                continue
            task_type = TaskType(type_name)
        params = {"item_id": listing.item_id, "source": listing.source, "all": False, "force": False}
        if stage == "video":
            params["voiceover_enabled"] = voiceover_enabled
        if stage == "voice" and task_type == TaskType.GENERATE_VOICE_CLONE:
            d = listing.data or {}
            params["x_vector_only"] = bool(d.get("voice_clone_x_vector_only", True))
            if d.get("voice_clone_ref_audio"):
                params["ref_audio"] = d["voice_clone_ref_audio"]
            if d.get("voice_clone_ref_text"):
                params["ref_text"] = d["voice_clone_ref_text"]
        if prev_task is not None:
            # 把前一个任务接到当前任务
            prev_params = dict(prev_task.params)
            prev_params["_next_task_id"] = None  # 占位，commit 后填
            prev_task.params = prev_params
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
        db.flush()  # 获取 id
        created.append((stage, task))
        prev_task = task

    # 填充 _next_task_id 并提交
    for idx, (_, task) in enumerate(created):
        if idx < len(created) - 1:
            p = dict(task.params)
            p["_next_task_id"] = created[idx + 1][1].id
            task.params = p
    db.commit()
    for _, task in created:
        db.refresh(task)

    first = created[0][1]
    background_tasks.add_task(_run_task_bg, first.id)
    return {
        "tasks": [{"id": t.id, "stage": s, "type": STAGE_TO_TYPE[s]} for s, t in created],
        "message": f"已按顺序创建 {len(created)} 个任务：{' → '.join(s for s, _ in created)}",
    }