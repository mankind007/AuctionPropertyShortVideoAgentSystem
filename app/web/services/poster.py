"""海报生成服务：封装 skills/promo-image/scripts/compose.py。

compose.py 参数:
  --source gpai|ali|all   (默认 gpai)
  --item-id  单套房源 ID
  --all      批量模式(已生成则跳过, 幂等)
  --force    批量模式下强制重生成(仅 --all 生效)
  --limit N  批量上限(默认 5)
  --width    输出宽度(默认自动)
"""
from __future__ import annotations


def build_poster_cmd(
    source: str = "all",
    all_items: bool = True,
    limit: int = 1000,
    force: bool = False,
    width: int | None = None,
    item_id: str | None = None,
) -> list[str]:
    cmd = ["python", "skills/promo-image/scripts/compose.py"]
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
    if width is not None:
        cmd.extend(["--width", str(width)])
    return cmd
