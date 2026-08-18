"""多源并行采集编排(公拍网 + 阿里资产)。

以子进程同时启动两套爬虫,各持一个独立 Chromium 实例/登录态,互不阻塞。
支持双源并行或单源(--only gpai / --only ali)。逻辑集中在 src,CLI 只透传参数。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ALI = str(PROJECT_ROOT / "scripts" / "crawl_ali.py")
_GPAI = str(PROJECT_ROOT / "scripts" / "crawl_gpai.py")
_RUN_LOG_DIR = PROJECT_ROOT / "reports" / "runs"


def build_commands(sources: Sequence[str], *, pages: int = 1,
                   ali_pages: Optional[int] = None, gpai_pages: Optional[int] = None,
                   ali_category: Optional[List[str]] = None,
                   download: bool = False, db: bool = False, headless: bool = False,
                   skip_complete: bool = False) -> List[List[str]]:
    """构造各源 CLI 命令(子进程执行)。"""
    cmds: List[List[str]] = []
    if "ali" in sources:
        ali = [_ALI, "--category"] + (ali_category or ["住宅"])
        ali += ["--pages", str(ali_pages if ali_pages is not None else pages)]
        if download:
            ali.append("--download")
        if db:
            ali.append("--db")
        if headless:
            ali.append("--headless")
        if skip_complete:
            ali.append("--skip-complete")
        cmds.append(ali)
    if "gpai" in sources:
        gpai = [_GPAI, "--pages", str(gpai_pages if gpai_pages is not None else pages)]
        if download:
            gpai.append("--download")
        if db:
            gpai.append("--db")
        if headless:
            gpai.append("--headless")
        if skip_complete:
            gpai.append("--skip-complete")
        cmds.append(gpai)
    return cmds


def run_sources(sources: Sequence[str], *, pages: int = 1,
                ali_pages: Optional[int] = None, gpai_pages: Optional[int] = None,
                ali_category: Optional[List[str]] = None,
                download: bool = False, db: bool = False, headless: bool = False,
                skip_complete: bool = False) -> int:
    """并行启动各源爬虫子进程,聚合退出码。日志落 reports/runs/。"""
    cmds = build_commands(
        sources, pages=pages, ali_pages=ali_pages, gpai_pages=gpai_pages,
        ali_category=ali_category, download=download, db=db,
        headless=headless, skip_complete=skip_complete,
    )
    if not cmds:
        return 2
    procs: List[tuple] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    _RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    for cmd in cmds:
        full = [sys.executable, *cmd]
        name = Path(cmd[0]).stem
        logf = _RUN_LOG_DIR / f"{name}-{stamp}.log"
        fh = open(logf, "w", encoding="utf-8")
        print(f"[编排] 启动: {' '.join(full)} 日志→ {logf}", flush=True)
        procs.append((name, logf, subprocess.Popen(full, cwd=str(PROJECT_ROOT),
                                                   stdout=fh, stderr=subprocess.STDOUT)))
    rc = 0
    for name, logf, p in procs:
        p.wait()
        print(f"[编排] {name} 退出码 {p.returncode},日志: {logf}", flush=True)
        rc |= p.returncode
    print(f"[编排] 全部完成,退出码 {rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(run_sources(["gpai", "ali"]))