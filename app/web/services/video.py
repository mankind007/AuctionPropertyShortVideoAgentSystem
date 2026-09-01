"""视频合成服务：封装 skills/video-compose/scripts/make_video.py 和 mux_voice.py。

make_video.py 参数:
  --source gpai|ali|all   (默认 gpai)
  --item-id  单套房源 ID
  --all      批量模式(已有视频则跳过)
  --force    批量模式下强制重做
  --limit N  批量上限(默认 5)
  --duration 4.0  每张海报停留秒数
  --fps 25         帧率
  --workers 1      批量并发数(默认 1)

mux_voice.py 参数:
  --source gpai|ali|all   (默认 gpai)
  --item-id  单套房源 ID
  --all      批量模式(已有 video_voiced 则跳过)
  --force    批量模式下强制重做
  --limit N  批量上限(默认 5)
  --fps 25         帧率

注意：mux_voice.py 没有 --workers 参数。
"""
from __future__ import annotations


def build_make_video_cmd(
    source: str = "all",
    all_items: bool = True,
    limit: int = 1000,
    force: bool = False,
    workers: int = 1,
    duration: float = 4.0,
    fps: int = 25,
    item_id: str | None = None,
    voiceover_enabled: bool = True,
) -> list[str]:
    cmd = ["python", "skills/video-compose/scripts/make_video.py"]
    if item_id:
        cmd.extend(["--item-id", item_id])
    else:
        if source != "all":
            cmd.extend(["--source", source])
        if all_items:
            cmd.append("--all")
        else:
            cmd.extend(["--limit", str(limit)])
        if force:
            cmd.append("--force")
        cmd.extend(["--workers", str(workers)])
    cmd.extend(["--duration", str(duration), "--fps", str(fps)])
    if voiceover_enabled:
        cmd.append("--voiceover")
    return cmd


def build_mux_voice_cmd(
    source: str = "all",
    all_items: bool = True,
    limit: int = 1000,
    force: bool = False,
    fps: int = 25,
    item_id: str | None = None,
) -> list[str]:
    cmd = ["python", "skills/video-compose/scripts/mux_voice.py"]
    if item_id:
        cmd.extend(["--item-id", item_id])
    else:
        if source != "all":
            cmd.extend(["--source", source])
        if all_items:
            cmd.append("--all")
        else:
            cmd.extend(["--limit", str(limit)])
        if force:
            cmd.append("--force")
    cmd.extend(["--fps", str(fps)])
    return cmd
