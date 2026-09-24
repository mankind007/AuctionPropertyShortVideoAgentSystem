"""任务执行器：subprocess 运行 CLI、实时捕获输出、更新进度。

约定：
  - 任务日志写入 reports/runs/task_{id}.log
  - 进度由脚本 stdout 输出，TaskRunner 按正则解析
  - 取消任务时 kill 子进程（含进程组，彻底清理 ffmpeg 等孙进程）
"""
from __future__ import annotations

import asyncio
import os
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

# 阶段标记行: 匹配到就更新 current_step(不改 progress), 让前端显示当前环节
STAGE_PATTERNS = [
    re.compile(r"^\[?阶段\]?[:\s]*(.+)$"),
    re.compile(r"^Step[:\s]+(.+)$", re.IGNORECASE),
    re.compile(r"^(加载模型|提取音频|提取关键点|人脸检测|VAE|推理|回填|合成|克隆|生成|写入).*"),
]


def _stage_label(line: str) -> str | None:
    """若该行是阶段标记, 返回阶段名; 否则 None。"""
    s = line.strip()
    for pat in STAGE_PATTERNS:
        m = pat.match(s)
        if m:
            return (m.group(1) if m.groups() else s)[:80]
    return None


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
                # PYTHONUNBUFFERED: 管道下 print 默认块缓冲(8KB), 进度会攒着不吐导致前端卡住
                env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=Path(__file__).resolve().parents[3],
                    env=env,
                    start_new_session=True,  # 新建会话/进程组，便于 killpg 杀树
                )

                assert self.proc.stdout is not None
                async for line in self.proc.stdout:
                    line = line.decode("utf-8", errors="replace").rstrip()
                    lf.write(line + "\n")
                    lf.flush()
                    self._parse_progress(line)

                await self.proc.wait()

            if self.proc.returncode == 0:
                self.task.status = TaskStatus.SUCCESS
                self.task.progress = 100
                self.task.current_step = "完成"
                self._fill_success_result()
            else:
                self.task.status = TaskStatus.FAILED
                last = self._last_log_error()
                self.task.error_message = (
                    f"进程退出码: {self.proc.returncode}" + (f" | {last}" if last else "")
                )
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
        """取消任务：终止子进程及其进程组（含 ffmpeg 等孙进程）。"""
        if self.proc and self.proc.returncode is None:
            try:
                pgid = os.getpgid(self.proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=30)
                except asyncio.TimeoutError:
                    os.killpg(pgid, signal.SIGKILL)
                    await self.proc.wait()
            except (ProcessLookupError, PermissionError):
                pass
        self.task.status = TaskStatus.CANCELLED
        self.task.finished_at = datetime.now()
        self.db.commit()

    def _last_log_error(self) -> str:
        """从任务日志尾部提取关键错误行，便于前端展示真实失败原因。"""
        try:
            if not (self.log_file and self.log_file.exists()):
                return ""
            lines = [
                ln.strip()
                for ln in self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip()
            ]
            keys = ("ERROR", "Error", "error", "RuntimeError", "Traceback", "Exception", "失败")
            for ln in reversed(lines):
                if any(k in ln for k in keys):
                    return ln[:240]
            return lines[-1][:240] if lines else ""
        except Exception:
            return ""

    def _parse_progress(self, line: str) -> None:
        """从输出行解析进度/阶段，更新 task.progress/current_step。"""
        stage = _stage_label(line)
        if stage:
            self.task.current_step = stage
            self.db.commit()
            return
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
                # 进度行后面若带中文阶段描述则展示它, 否则取行首
                rest = line.split("%", 1)[-1].strip(" |:-") if "%" in line else ""
                step = rest or line.strip()[:80]
                if step:
                    self.task.current_step = step
                self.db.commit()
                break

    def _fill_success_result(self) -> None:
        """成功后把已知输出路径写入 task.result，供前端预览。"""
        params = self.task.params or {}
        result = dict(self.task.result or {})
        # lipsync: --output 或默认 assets/lip_sync/<stem>_<stem>.mp4
        if getattr(self.task.type, "value", str(self.task.type)) == "generate_lipsync":
            out = params.get("output")
            if out:
                result.setdefault("output", out)
            else:
                img = Path(params.get("image") or "image")
                aud = Path(params.get("audio") or "audio")
                result.setdefault(
                    "output",
                    f"assets/lip_sync/{img.stem}_{aud.stem}.mp4",
                )
        elif getattr(self.task.type, "value", str(self.task.type)) == "generate_voice_clone":
            out = params.get("output")
            if out:
                result.setdefault("output", out)
            else:
                ref = Path(params.get("ref_audio") or "voice")
                result.setdefault("output", f"assets/voice_clone/{ref.stem}.wav")
        self.task.result = result
