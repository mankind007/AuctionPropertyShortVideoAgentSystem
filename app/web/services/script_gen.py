"""话术生成服务：封装 skills/script-writer/scripts/generate_scripts.py。

generate_scripts.py 参数:
  --source gpai|ali|all   (默认 gpai)
  --item-id  单套房源 ID
  --all      批量模式(已有话术则跳过)
  --force    批量模式下强制重生成
  --limit N  批量上限(默认 5)
  --llm      用 LLM 润色增强(默认纯规则)
  --workers N  LLM 批量并发数(默认 4)
  --dry-run  只打印不写库
"""
from __future__ import annotations


def build_script_cmd(
    source: str = "all",
    all_items: bool = True,
    limit: int = 1000,
    force: bool = False,
    llm: bool = False,
    workers: int = 4,
    item_id: str | None = None,
) -> list[str]:
    cmd = ["python", "skills/script-writer/scripts/generate_scripts.py"]
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
    if llm:
        cmd.append("--llm")
    cmd.extend(["--workers", str(workers)])
    return cmd
