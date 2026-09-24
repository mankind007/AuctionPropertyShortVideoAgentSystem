"""lip-sync 技能契约测试: 路径常量 / CLI / 权重清单, 不跑重推理。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "lip-sync" / "scripts" / "lipsync.py"
SKILL_MD = REPO / "skills" / "lip-sync" / "SKILL.md"
REF_DOC = REPO / "skills" / "lip-sync" / "references" / "部署与调参.md"
VENDOR = REPO / "skills" / "lip-sync" / "vendor" / "MuseTalk"
WEIGHTS = REPO / "models" / "lip-sync"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO),
        timeout=120,
    )


def test_layout_files_exist():
    assert SCRIPT.is_file(), SCRIPT
    assert SKILL_MD.is_file(), SKILL_MD
    assert REF_DOC.is_file(), REF_DOC
    assert (VENDOR / "musetalk").is_dir(), VENDOR
    assert WEIGHTS.is_dir(), WEIGHTS


def test_skill_frontmatter_name():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: lip-sync" in text.split("---", 2)[1]


def test_repo_root_constant_in_source():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "parents[3]" in src
    assert 'MUSETALK_DIR = REPO_ROOT / "skills" / "lip-sync" / "vendor" / "MuseTalk"' in src
    # 相对 --output 必须在 os.chdir(MUSETALK_DIR) 之前转绝对, 否则写到 vendor 下
    assert "if args.output:\n        args.output = Path(os.path.abspath(args.output))" in src


def test_output_path_not_under_vendor():
    """回归: 相对 output 不得落到 skills/lip-sync/vendor/ 下。"""
    vendor_out = VENDOR / "assets" / "lip_sync"
    if vendor_out.is_dir():
        leftovers = list(vendor_out.glob("*.mp4"))
        assert not leftovers, f"vendor 下有误写成片: {leftovers}"


def test_cli_help_exit0():
    p = _run(["--help"])
    assert p.returncode == 0, p.stderr
    assert "--force" in p.stdout
    assert "--check" in p.stdout


def test_weights_manifest():
    expected = [
        WEIGHTS / "musetalkV15" / "unet.pth",
        WEIGHTS / "musetalkV15" / "musetalk.json",
        WEIGHTS / "sd-vae" / "config.json",
        WEIGHTS / "whisper" / "config.json",
        WEIGHTS / "dwpose" / "dw-ll_ucoco_384.pth",
        WEIGHTS / "face-parse-bisent" / "79999_iter.pth",
    ]
    missing = [str(p) for p in expected if not p.is_file()]
    assert not missing, f"missing weights: {missing}"


def test_check_exit0():
    p = _run(["--check"])
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
