"""voice-clone 技能契约测试: 路径 / CLI / 权重清单, 不跑重推理。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "voice-clone" / "scripts" / "clone_voice.py"
SKILL_MD = REPO / "skills" / "voice-clone" / "SKILL.md"
MODEL_DIR = REPO / "models" / "tts" / "Qwen3-TTS-12Hz-0.6B-Base"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO),
        timeout=60,
    )


def test_layout_files_exist():
    assert SCRIPT.is_file(), SCRIPT
    assert SKILL_MD.is_file(), SKILL_MD
    assert MODEL_DIR.is_dir(), MODEL_DIR


def test_skill_frontmatter_name():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---")
    body = text.split("---", 2)[1]
    assert "name: voice-clone" in body


def test_repo_root_constant_in_source():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "parents[3]" in src
    assert 'MODEL_DIR = REPO_ROOT / "models" / "tts" / "Qwen3-TTS-12Hz-0.6B-Base"' in src


def test_cli_help_exit0():
    p = _run(["--help"])
    assert p.returncode == 0, p.stderr
    assert "--ref-audio" in p.stdout
    assert "--x-vector-only" in p.stdout
    assert "--force" in p.stdout
    assert "--check" in p.stdout


def test_weights_manifest():
    assert (MODEL_DIR / "config.json").is_file(), MODEL_DIR
    weights = list(MODEL_DIR.glob("*.safetensors")) + list(MODEL_DIR.glob("*.bin"))
    assert weights, f"no weight files in {MODEL_DIR}"


def test_check_exit0():
    p = _run(["--check"])
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
