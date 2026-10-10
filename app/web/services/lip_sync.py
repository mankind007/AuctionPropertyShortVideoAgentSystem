"""口型对齐服务：封装 skills/lip-sync/scripts/lipsync.py。

lipsync.py 参数:
  --backend musetalk|imtalker  后端(默认 musetalk)
  --crop          IMTalker 人脸裁剪模式(官方默认, 输出 512x512 特写, 质量更稳)
  --image path     人物图(jpg/png/webp)
  --audio path     语音(mp3/wav/m4a)
  --output path    输出 mp4(可选, 默认 assets/lip_sync/<image>_<audio>[_imtalker].mp4)
  --force          输出已存在时强制重跑
  --check          只体检
  --max-seconds N  限制音频时长
  --fps N          默认 25
  --batch-size N   默认 2
  --no-fp16        关闭 fp16
  --device auto|cpu|cuda:0
  --a-cfg-scale F --nfe N --seed N   IMTalker 采样参数
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
    backend: str = "musetalk",
    crop: bool = False,
    a_cfg_scale: float | None = None,
    nfe: int | None = None,
    seed: int | None = None,
) -> list[str]:
    cmd = ["python", "skills/lip-sync/scripts/lipsync.py"]
    if backend and backend != "musetalk":
        cmd.extend(["--backend", backend])
    if crop:
        cmd.append("--crop")
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
    if a_cfg_scale is not None:
        cmd.extend(["--a-cfg-scale", str(a_cfg_scale)])
    if nfe is not None:
        cmd.extend(["--nfe", str(nfe)])
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    return cmd
