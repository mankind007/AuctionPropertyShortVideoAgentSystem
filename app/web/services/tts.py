"""TTS 配音服务：封装 skills/voice-tts/scripts/tts_voice.py。

tts_voice.py 参数:
  --source gpai|ali|all   (默认 gpai)
  --item-id  单套房源 ID
  --all      批量模式(已有 voice 则跳过)
  --force    批量模式下强制重做
  --limit N  批量上限(默认 5)
  --voice zh-CN-YunxiNeural  音色(默认 zh-CN-YunxiNeural)

注意：tts_voice.py 没有 --workers 参数，edge-tts 内部串行执行。
"""
from __future__ import annotations


def build_tts_cmd(
    source: str = "all",
    all_items: bool = True,
    limit: int = 1000,
    force: bool = False,
    voice: str = "zh-CN-YunxiNeural",
    item_id: str | None = None,
) -> list[str]:
    cmd = ["python", "skills/voice-tts/scripts/tts_voice.py"]
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
    cmd.extend(["--voice", voice])
    return cmd
