"""口型对齐服务：封装 skills/lip-sync/scripts/lipsync.py。

lipsync.py 参数:
  --image path     人物图(jpg/png/webp)
  --audio path     语音(mp3/wav/m4a)
  --output path    输出 mp4(可选, 默认 assets/lip_sync/<image>_<audio>.mp4)
  --force          输出已存在时强制重跑
  --check          只体检
  --max-seconds N  限制音频时长
  --fps N          默认 25
  --batch-size N   默认 2
  --no-fp16        关闭 fp16
  --device auto|cpu|cuda:0
"""
from __future__ import annotations


def build_lipsync_cmd(
    image: str | None = None,
    audio: str | None = None,
    output: str | None = None,
    force: bool = False,
    check: bool = False,
    max_seconds: float = 0,
    fps: int = 25,
    batch_size: int = 2,
    fp16: bool = True,
    device: str = "auto",
    upper_boundary_ratio: float | None = None,
) -> list[str]:
    cmd = ["python", "skills/lip-sync/scripts/lipsync.py"]
    if check:
        cmd.append("--check")
        return cmd
    if image:
        cmd.extend(["--image", image])
    if audio:
        cmd.extend(["--audio", audio])
    if output:
        cmd.extend(["--output", output])
    if force:
        cmd.append("--force")
    if max_seconds:
        cmd.extend(["--max-seconds", str(max_seconds)])
    cmd.extend(["--fps", str(fps), "--batch-size", str(batch_size)])
    if not fp16:
        cmd.append("--no-fp16")
    if device and device != "auto":
        cmd.extend(["--device", device])
    if upper_boundary_ratio is not None:
        cmd.extend(["--upper-boundary-ratio", str(upper_boundary_ratio)])
    return cmd
