"""声音克隆服务：封装 skills/voice-clone/scripts/clone_voice.py。

clone_voice.py 参数:
  --ref-audio path   参考音频(必填, 除非 --check)
  --ref-text str     参考音频对应文本(精确克隆)
  --text str         目标合成文本
  --language str     默认 Chinese
  --output path      输出 wav
  --x-vector-only    不用 ref_text 的懒人模式
  --device auto|cpu|cuda:0
  --force            输出已存在时强制重跑
  --check            只体检
"""
from __future__ import annotations


def build_voice_clone_cmd(
    ref_audio: str | None = None,
    ref_text: str | None = None,
    text: str | None = None,
    language: str = "Chinese",
    output: str | None = None,
    x_vector_only: bool = False,
    device: str = "auto",
    force: bool = False,
    check: bool = False,
    source: str | None = None,
    item_id: str | None = None,
    all_items: bool = False,
    limit: int = 5,
) -> list[str]:
    cmd = ["python", "skills/voice-clone/scripts/clone_voice.py"]
    if check:
        cmd.append("--check")
        return cmd
    if source:
        cmd.extend(["--source", source])
    if item_id:
        cmd.extend(["--item-id", item_id])
    elif all_items:
        cmd.append("--all")
        cmd.extend(["--limit", str(limit)])
    if ref_audio:
        cmd.extend(["--ref-audio", ref_audio])
    if ref_text:
        cmd.extend(["--ref-text", ref_text])
    if text:
        cmd.extend(["--text", text])
    if language and language != "Chinese":
        cmd.extend(["--language", language])
    if output:
        cmd.extend(["--output", output])
    if x_vector_only:
        cmd.append("--x-vector-only")
    if device and device != "auto":
        cmd.extend(["--device", device])
    if force:
        cmd.append("--force")
    return cmd
