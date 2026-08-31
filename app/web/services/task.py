"""任务执行器：subprocess 运行 CLI、实时捕获输出、更新进度。

约定：
  - 任务日志写入 reports/runs/task_{id}.log
  - 进度由脚本 stdout 输出，TaskRunner 按正则解析
  - 取消任务时 kill 子进程
"""
from __future__ import annotations

import asyncio
import re
import signal
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from db.models import Task, TaskStatus
from app.web.services.registry import build_command


REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports" / "runs"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 子进程必须使用当前虚拟环境解释器，而非 PATH 中的 python（可能缺少项目依赖）
PYTHON_EXE = sys.executable


# 进度关键字正则（各脚本需按约定输出）
PROGRESS_PATTERNS = [
    (re.compile(r"progress[:\s]+(\d+)%?"), "progress"),
    (re.compile(r"\[(\d+)/(\d+)\]"), "ratio"),
    (re.compile(r"处理[:\s]+(\d+)/(\d+)"), "ratio_cn"),
]


class TaskRunner:
    """统一任务执行器。"""

    def __init__(self, task: Task, db: Session):
        self.task = task
        self.db = db
        self.proc: asyncio.subprocess.Process | None = None
        self.log_file: Path | None = None

    async def run(self) -> None:
        self.task.status = TaskStatus.RUNNING
        self.task.started_at = datetime.now()
        self.db.commit()

        cmd = build_command(self.task.type, self.task.params)
        if cmd and cmd[0] in ("python", "python3"):
            cmd[0] = PYTHON_EXE
        self.log_file = REPORTS_DIR / f"task_{self.task.id}.log"

        try:
            with open(self.log_file, "w", encoding="utf-8") as lf:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=Path(__file__).resolve().parents[3],
                )

                # 实时读取输出，解析进度
                assert self.proc.stdout is not None
                async for line in self.proc.stdout:
                    line = line.decode(errors="replace").rstrip()
                    lf.write(line + "\n")
                    lf.flush()
                    self._parse_progress(line)

                await self.proc.wait()

            if self.proc.returncode == 0:
                self.task.status = TaskStatus.SUCCESS
                self.task.progress = 100
                self.task.current_step = "完成"
            else:
                self.task.status = TaskStatus.FAILED
                self.task.error_message = f"进程退出码: {self.proc.returncode}"
                self.task.current_step = "失败"

        except Exception as e:
            self.task.status = TaskStatus.FAILED
            self.task.error_message = str(e)
            self.task.current_step = "异常"
        finally:
            self.task.finished_at = datetime.now()
            if self.task.status == TaskStatus.SUCCESS:
                self.task.progress = 100
            self.db.commit()

    async def cancel(self) -> None:
        """取消任务：终止子进程。"""
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            except ProcessLookupError:
                pass
        self.task.status = TaskStatus.CANCELLED
        self.task.finished_at = datetime.now()
        self.db.commit()

    def _parse_progress(self, line: str) -> None:
        """从输出行解析进度，更新 task.progress/current_step。"""
        for pattern, ptype in PROGRESS_PATTERNS:
            m = pattern.search(line)
            if m:
                if ptype == "progress":
                    self.task.progress = min(100, max(0, int(m.group(1))))
                elif ptype in ("ratio", "ratio_cn"):
                    done = int(m.group(1))
                    total = int(m.group(2))
                    if total > 0:
                        self.task.progress = min(100, int(done * 100 / total))
                # 更新当前步骤（取行首非空部分）
                step = line.strip()[:128]
                if step:
                    self.task.current_step = step
                self.db.commit()
                break
