"""全流程管线服务：组合子任务、依赖等待。"""
from __future__ import annotations

from db.models import Task, TaskStatus, TaskType
from app.web.services.task import TaskRunner


async def run_full_pipeline(
    task: Task,
    db,
    source: str = "all",
    limit: int = 100,
    stages: list[str] = None,
) -> None:
    """
    执行完整管线：
    1. 采集 (crawl_all)
    2. 话术生成 (generate_script)
    3. 海报生成 (generate_poster)
    4. 视频生成 (generate_video)
    5. TTS 配音 (generate_tts)
    6. 音视频合成 (mux_video)

    简化实现：顺序创建子任务，等待每个完成后再启动下一个。
    """
    if stages is None:
        stages = ["crawl", "script", "poster", "video", "tts", "mux"]

    stage_to_type = {
        "crawl": TaskType.CRAWL_ALL,
        "script": TaskType.GENERATE_SCRIPT,
        "poster": TaskType.GENERATE_POSTER,
        "video": TaskType.GENERATE_VIDEO,
        "tts": TaskType.GENERATE_TTS,
        "mux": TaskType.MUX_VIDEO,
    }

    for stage in stages:
        task.current_step = f"启动 {stage}"
        db.commit()

        sub_task = Task(
            owner_id=task.owner_id,
            type=stage_to_type[stage],
            status=TaskStatus.PENDING,
            params={"source": source, "limit": limit},
            result={},
            progress=0,
            current_step="",
            max_retries=3,
            retry_count=0,
        )
        db.add(sub_task)
        db.commit()
        db.refresh(sub_task)

        # 等待子任务完成
        runner = TaskRunner(sub_task, db)
        await runner.run()

        # 检查结果
        if sub_task.status != TaskStatus.SUCCESS:
            task.status = TaskStatus.FAILED
            task.error_message = f"阶段 {stage} 失败: {sub_task.error_message}"
            task.current_step = f"失败于 {stage}"
            db.commit()
            return

        task.result[f"{stage}_task_id"] = sub_task.id

    task.status = TaskStatus.SUCCESS
    task.progress = 100
    task.current_step = "全流程完成"
    db.commit()