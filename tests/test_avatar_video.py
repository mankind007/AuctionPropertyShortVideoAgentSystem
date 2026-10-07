import importlib.util
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRIPTS = PROJ / "skills" / "avatar-video" / "scripts"


def _load(name):
    """Load a skill script without leaking a generic `config` module.

    The scripts import a sibling `config` module at load time. Registering it
    under a private name and aliasing it only for the duration of the load keeps
    the app's own `config` package intact for every other test module.
    """
    saved = dict(sys.modules)
    try:
        cfg_spec = importlib.util.spec_from_file_location("avatar_video_config", SCRIPTS / "config.py")
        cfg_mod = importlib.util.module_from_spec(cfg_spec)
        sys.modules["avatar_video_config"] = cfg_mod
        cfg_spec.loader.exec_module(cfg_mod)
        sys.modules["config"] = cfg_mod

        spec = importlib.util.spec_from_file_location(f"avatar_video_{name}", SCRIPTS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for key in [k for k in sys.modules if k not in saved]:
            del sys.modules[key]
        sys.modules.update(saved)


gv = _load("generate_video")
cfg = _load("config")


def test_skill_manifest_present():
    """契约: SKILL.md 与 scripts 齐备。"""
    skill = PROJ / "skills" / "avatar-video"
    assert (skill / "SKILL.md").is_file()
    for s in ("config.py", "generate_video.py", "whisper_srt.py",
              "burn_subtitle.py", "run_pipeline.py"):
        assert (skill / "scripts" / s).is_file(), s


def test_resolution_snaps_to_grid_and_keeps_aspect():
    """契约: 分辨率按原图比例吸附到 16 的倍数, 误差 <3%。"""
    cases = [(376, 546), (574, 657), (1024, 1024), (1920, 1080), (600, 1200)]
    for w, h in cases:
        for area in (180_000, 256_000, 400_000):
            ow, oh = gv.fit_resolution(w, h, area)
            assert ow % gv.GRID == 0 and oh % gv.GRID == 0, (w, h, area, ow, oh)
            assert abs((ow / oh) / (w / h) - 1) < 0.03, (w, h, area, ow, oh)


def test_area_controls_sequence_length():
    """契约: 像素预算越小, 序列长度越短(即越快)。"""
    def seq(w, h, area):
        ow, oh = gv.fit_resolution(w, h, area)
        return (ow // gv.GRID) * (oh // gv.GRID) * 21

    assert seq(376, 546, 180_000) < seq(376, 546, 256_000) < seq(376, 546, 400_000)


def test_whisper_model_list():
    """契约: 暴露的 whisper 模型名是合法集合。"""
    assert set(cfg.WHISPER_MODELS) == {"tiny", "base", "small", "medium", "large-v3"}
    assert cfg.WHISPER_DEFAULT in cfg.WHISPER_MODELS


def test_whisper_dir_rejects_unknown_model():
    """契约: 未知模型名报错而不是静默。"""
    try:
        cfg.whisper_dir("gigantic")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unknown model")


def test_comfy_flags_avoid_gpu_mapping_crash():
    """契约: 必须带上关掉 async offload 与 cudaMalloc 的参数。"""
    assert "--disable-async-offload" in cfg.COMFY_ARGS
    assert "--disable-cuda-malloc" in cfg.COMFY_ARGS


def test_burn_styles_defined():
    """契约: 两个字幕样式都有内容。"""
    bs = _load("burn_subtitle")
    assert set(bs.STYLES) == {"corporate", "bottom"}
    for name, style in bs.STYLES.items():
        assert "FontName" in style and "Alignment" in style, name


def test_ffmpeg_available():
    """契约: imageio-ffmpeg 捆绑的 ffmpeg 可用。"""
    bs = _load("burn_subtitle")
    assert Path(bs.FFMPEG).exists()


def test_srt_timestamp_format():
    """契约: SRT 时间戳格式正确。"""
    ws = _load("whisper_srt")
    assert ws.srt_time(0) == "00:00:00,000"
    assert ws.srt_time(3661.5) == "01:01:01,500"


def test_check_help_exit_zero():
    """契约: --check / --help 可执行且退出码为 0。"""
    exe = PROJ / ".venv" / "Scripts" / "python.exe"
    for argv in (["--help"], ["--check"]):
        p = subprocess.run([str(exe), str(SCRIPTS / "generate_video.py"), *argv],
                           capture_output=True, text=True, cwd=str(PROJ))
        assert p.returncode == 0, (argv, p.stdout[-500:], p.stderr[-500:])
