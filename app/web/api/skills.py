"""技能接口：列表、手动触发。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import session_scope
from app.web.deps import get_db, get_current_user
from app.web.schemas import SkillInfo, SkillRunRequest


router = APIRouter(prefix="/skills", tags=["技能"])

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


def _load_skill_metadata(skill_dir: Path) -> Optional[dict]:
    """从 SKILL.md 的 YAML frontmatter 提取 name 和 description。
    
    使用正则提取而非 yaml.safe_load，因为 description 可能包含冒号等特殊字符。
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        end = content.find("---", 3)
        if end <= 0:
            return None
        fm_text = content[3:end].strip()
        
        # 用正则提取 name 和 description
        name_match = re.search(r"^name:\s*(.+)$", fm_text, re.MULTILINE)
        desc_match = re.search(r"^description:\s*(.+)$", fm_text, re.MULTILINE)
        
        name = name_match.group(1).strip() if name_match else skill_dir.name
        description = desc_match.group(1).strip() if desc_match else ""
        
        return {"name": name, "description": description}
    except Exception:
        return None


@router.get("", response_model=list[SkillInfo])
def list_skills(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """获取所有技能元数据。"""
    skills = []
    if SKILLS_DIR.exists():
        for skill_dir in SKILLS_DIR.iterdir():
            if skill_dir.is_dir():
                fm = _load_skill_metadata(skill_dir)
                if fm:
                    skills.append(SkillInfo(
                        name=fm.get("name", skill_dir.name),
                        description=fm.get("description", ""),
                    ))
    return skills


@router.post("/{skill_name}/run")
def run_skill(
    skill_name: str,
    req: SkillRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """手动触发技能（创建对应任务）。"""
    from db.models import Task, TaskStatus, TaskType
    from app.web.api.tasks import _run_task_bg

    skill_to_type = {
        "gpai-crawler": TaskType.CRAWL_GPAI,
        "ali-assets-crawler": TaskType.CRAWL_ALI,
        "script-writer": TaskType.GENERATE_SCRIPT,
        "voice-tts": TaskType.GENERATE_TTS,
        "promo-image": TaskType.GENERATE_POSTER,
        "video-compose": TaskType.GENERATE_VIDEO,
        "video-mux": TaskType.MUX_VIDEO,
    }

    task_type = skill_to_type.get(skill_name)
    if not task_type:
        raise HTTPException(404, f"未知技能: {skill_name}")

    task = Task(
        owner_id=current_user.id,
        type=task_type,
        status=TaskStatus.PENDING,
        params=req.params,
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
    return {"task_id": task.id, "status": "started"}