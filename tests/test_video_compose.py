import importlib.util
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

_spec = importlib.util.spec_from_file_location(
    "make_video", PROJ / "skills/video-compose/scripts/make_video.py")
mv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mv)


def test_ffmpeg_resolves():
    """契约: imageio-ffmpeg 捆绑的 ffmpeg 存在。"""
    assert mv.FFMPEG and Path(mv.FFMPEG).exists()


def test_find_posters_empty_when_no_dir():
    """契约: 无 imgs 目录返回空。"""
    assert mv._find_posters("none", "0", "_v.png") == []


def test_find_posters_sorted_and_filtered(tmp_path, monkeypatch):
    """契约: 只取 posters/ 下指定方向海报, 忽略原图, 按文件名排序。"""
    monkeypatch.setattr(mv, "PROJECT_ROOT", tmp_path)
    posters = tmp_path / "assets" / "gpai" / "52946" / "posters"
    posters.mkdir(parents=True)
    (posters / "poster_02_v.png").write_bytes(b"x")
    (posters / "poster_10_v.png").write_bytes(b"x")
    (posters / "poster_01_v.png").write_bytes(b"x")
    (posters / "poster_01_h.png").write_bytes(b"x")
    (posters / "i1.jpg").write_bytes(b"x")
    v = mv._find_posters("gpai", "52946", "_v.png")
    assert [p.name for p in v] == ["poster_01_v.png", "poster_02_v.png", "poster_10_v.png"]
