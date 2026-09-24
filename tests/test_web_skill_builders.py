"""build_*_cmd 与 CLI 参数名一致性契约测试。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _help(script_rel: str) -> str:
    p = subprocess.run(
        [sys.executable, str(REPO / script_rel), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO), timeout=30,
    )
    assert p.returncode == 0, p.stderr
    return p.stdout


def test_lipsync_builder_matches_cli():
    from app.web.services.lip_sync import build_lipsync_cmd

    cmd = build_lipsync_cmd(
        image="a.jpg", audio="b.mp3", output="o.mp4", force=True,
        max_seconds=8, fps=25, batch_size=2, fp16=False,
        device="cpu", upper_boundary_ratio=0.58,
    )
    help_text = _help("skills/lip-sync/scripts/lipsync.py")
    for a in cmd[2:]:
        if a.startswith("--"):
            assert a in help_text, f"unknown flag {a}"
    assert "python" == cmd[0]
    assert "skills/lip-sync/scripts/lipsync.py" in cmd[1]


def test_voice_clone_builder_matches_cli():
    from app.web.services.voice_clone import build_voice_clone_cmd

    cmd = build_voice_clone_cmd(
        ref_audio="r.mp3", ref_text="hi", text="yo", output="o.wav",
        x_vector_only=True, force=True, source="gpai", item_id="1",
        device="cpu",
    )
    help_text = _help("skills/voice-clone/scripts/clone_voice.py")
    for a in cmd[2:]:
        if a.startswith("--"):
            assert a in help_text, f"unknown flag {a}"
    assert "skills/voice-clone/scripts/clone_voice.py" in cmd[1]


def test_registry_has_new_task_types():
    from db.models import TaskType
    from app.web.services.registry import TASK_REGISTRY, build_command

    assert TaskType.GENERATE_LIPSYNC in TASK_REGISTRY
    assert TaskType.GENERATE_VOICE_CLONE in TASK_REGISTRY
    cmd = build_command(TaskType.GENERATE_LIPSYNC, {"image": "a", "audio": "b"})
    assert "skills/lip-sync/scripts/lipsync.py" in cmd[1]
    cmd2 = build_command(TaskType.GENERATE_VOICE_CLONE, {"ref_audio": "r", "text": "t"})
    assert "skills/voice-clone/scripts/clone_voice.py" in cmd2[1]


def test_skills_api_maps_new_skills():
    from app.web.api.skills import run_skill
    # 只验证映射字典逻辑存在: 通过源码断言避免起完整 app
    src = (REPO / "app/web/api/skills.py").read_text(encoding="utf-8")
    assert '"lip-sync": TaskType.GENERATE_LIPSYNC' in src
    assert '"voice-clone": TaskType.GENERATE_VOICE_CLONE' in src
