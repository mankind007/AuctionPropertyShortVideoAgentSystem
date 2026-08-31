"""任务接口：创建、查询、取消、SSE 进度流。"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db import session_scope
from db.models import Task, TaskStatus
from app.web.deps import get_db, get_current_user, get_pagination
from app.web.schemas import TaskCreate, TaskOut, PaginatedTasks, TaskProgress
from app.web.services.task import TaskRunner


router = APIRouter(prefix="/tasks", tags=["任务"])

# 全局引用，用于取消任务时终止进程
_runners: dict[int, TaskRunner] = {}


def _run_task_bg(task_id: int) -> None:
    """后台线程中启动任务执行（创建新的 event loop）。

    支持串行任务链：若任务成功且 params 含 `_next_task_id`，自动接着跑下一个。
    """
    import threading
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from db import session_scope
        with session_scope() as db:
            current_id = task_id
            while current_id:
                task = db.query(Task).filter(Task.id == current_id).first()
                if not task or task.status != TaskStatus.PENDING:
                    break
                runner = TaskRunner(task, db)
                _runners[current_id] = runner
                try:
                    loop.run_until_complete(runner.run())
                finally:
                    _runners.pop(current_id, None)
                # 成功后继续链中下一个任务
                if task.status == TaskStatus.SUCCESS and (task.params or {}).get("_next_task_id"):
                    current_id = task.params["_next_task_id"]
                else:
                    current_id = None
    finally:
        loop.close()


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    task_in: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """创建任务。"""
    task = Task(
        owner_id=current_user.id,
        type=task_in.type,
        status=TaskStatus.PENDING,
        params=task_in.params,
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


@router.get("", response_model=PaginatedTasks)
def list_tasks(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """分页查询当前用户的任务。"""
    query = db.query(Task).filter(Task.owner_id == current_user.id)
    if status:
        query = query.filter(Task.status == status)
    if type:
        query = query.filter(Task.type == type)
    total = query.count()
    query = query.order_by(desc(Task.created_at))
    items = query.offset(pagination.offset).limit(pagination.limit).all()
    return PaginatedTasks(
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=items,
    )


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """获取任务详情。"""
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/progress", response_model=TaskProgress)
def get_task_progress(task_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """获取任务进度（轮询用）。"""
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return TaskProgress(
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
    )


@router.get("/{task_id}/stream")
async def stream_task_progress(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """SSE 实时推送任务进度。"""
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    async def event_generator():
        last_progress = -1
        last_step = ""
        while True:
            if await request.is_disconnected():
                break
            db.expire(task)
            if task.progress != last_progress or task.current_step != last_step:
                data = TaskProgress(
                    progress=task.progress,
                    current_step=task.current_step,
                    error_message=task.error_message,
                ).model_dump_json()
                yield f"data: {data}\n\n"
                last_progress = task.progress
                last_step = task.current_step
            if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
                data = TaskProgress(
                    progress=task.progress,
                    current_step=task.current_step,
                    error_message=task.error_message,
                ).model_dump_json()
                yield f"data: {data}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.delete("/{task_id}", status_code=204)
async def cancel_task(task_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """取消任务（仅 PENDING/RUNNING 可取消）。"""
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(400, "任务已结束，无法取消")
    runner = _runners.get(task_id)
    if runner:
        await runner.cancel()
    else:
        task.status = TaskStatus.CANCELLED
        task.finished_at = __import__("datetime").datetime.now()
        db.commit()


@router.post("/{task_id}/retry", response_model=TaskOut)
def retry_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """重试失败任务（创建新任务）。"""
    old_task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not old_task:
        raise HTTPException(404, "任务不存在")
    if old_task.status != TaskStatus.FAILED:
        raise HTTPException(400, "仅失败任务可重试")
    new_task = Task(
        owner_id=current_user.id,
        type=old_task.type,
        status=TaskStatus.PENDING,
        params=old_task.params,
        result={},
        progress=0,
        current_step="",
        max_retries=3,
        retry_count=0,
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    background_tasks.add_task(_run_task_bg, new_task.id)
    return new_task
