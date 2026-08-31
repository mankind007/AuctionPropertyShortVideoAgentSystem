"""采集任务服务：封装 crawl_gpai/crawl_ali/crawl_all CLI。

crawl_gpai.py 参数:
  --pages N          抓取页数, 0=自动(默认)
  --download         抓取并下载详情页图片
  --db               upsert 进 PostgreSQL
  --headless         无头模式(默认开启)
  --skip-complete    断点续传

crawl_ali.py 参数:
  --category 住宅 商业 工业 其他  (默认 住宅)
  --pages N          每分类页数, 0=全部(默认 2)
  --headless         无头模式(默认关闭=有头)
  --download         下载图片
  --db               upsert 进 PostgreSQL
  --skip-complete    断点续传

crawl_all.py 参数:
  --pages N          两源通用页数(默认 1)
  --gpai-pages N     公拍网专属(覆盖 --pages)
  --ali-pages N      阿里专属(覆盖 --pages)
  --ali-category     阿里分类(默认 住宅)
  --download         下载图片
  --db               upsert 进 PostgreSQL
  --headless         无头模式(默认有头)
  --skip-complete    断点续传
  --only gpai|ali    只跑单源

注意：各脚本 --headless/--pages 默认值不同，需显式传入。
"""
from __future__ import annotations


def build_crawl_gpai_cmd(
    pages: int = 0,
    download: bool = False,
    db: bool = True,
    headless: bool = True,
    skip_complete: bool = False,
) -> list[str]:
    cmd = ["python", "scripts/crawl_gpai.py", f"--pages={pages}"]
    if download:
        cmd.append("--download")
    if db:
        cmd.append("--db")
    if headless:
        cmd.append("--headless")
    if skip_complete:
        cmd.append("--skip-complete")
    return cmd


def build_crawl_ali_cmd(
    category: str = "住宅",
    pages: int = 2,
    download: bool = False,
    db: bool = True,
    headless: bool = False,
    skip_complete: bool = False,
) -> list[str]:
    cmd = ["python", "scripts/crawl_ali.py", f"--category={category}", f"--pages={pages}"]
    if download:
        cmd.append("--download")
    if db:
        cmd.append("--db")
    if headless:
        cmd.append("--headless")
    if skip_complete:
        cmd.append("--skip-complete")
    return cmd


def build_crawl_all_cmd(
    gpai_pages: int = 1,
    ali_pages: int = 1,
    ali_category: str = "住宅",
    download: bool = False,
    db: bool = True,
    headless: bool = False,
    skip_complete: bool = False,
    only: str | None = None,
) -> list[str]:
    cmd = ["python", "scripts/crawl_all.py"]
    cmd.extend([f"--gpai-pages={gpai_pages}", f"--ali-pages={ali_pages}", f"--ali-category={ali_category}"])
    if download:
        cmd.append("--download")
    if db:
        cmd.append("--db")
    if headless:
        cmd.append("--headless")
    if skip_complete:
        cmd.append("--skip-complete")
    if only and only in ("gpai", "ali"):
        cmd.extend(["--only", only])
    return cmd
