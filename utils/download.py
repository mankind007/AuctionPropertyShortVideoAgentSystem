"""跨技能共享的图片下载工具(带重试 + 并发分批)。

公拍网(gpai)与阿里资产(ali)复用的下载逻辑:
- 单张最多重试 3 次,失败退避 1/2/4s(重试间隔可配)。
- 支持按批并发下载(ThreadPoolExecutor),单张失败不中断整批。
"""
from __future__ import annotations

import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from utils.browser import UA

_Task = Tuple[Path, str]


def _download_one(dest: Path, img_url: str, timeout: int,
                  retries: int, backoff: Sequence[float]) -> bool:
    """下载单个图片到 dest,失败按 backoff 序列重试;返回是否成功。"""
    for attempt in range(retries):
        req = urllib.request.Request(img_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            return True
        except Exception:  # noqa: BLE001
            if attempt < retries - 1:
                delay = backoff[min(attempt, len(backoff) - 1)]
                time.sleep(delay)
    return False


def download_chunk(tasks: Sequence[_Task], timeout: int = 30,
                   retries: int = 3, backoff: Sequence[float] = (1.0, 2.0, 4.0)) -> List[Tuple[str, str, bool]]:
    """并发下载一批图片,逐张返回 (img_url, dest, ok)。

    tasks: [(dest_path, img_url), ...]。单张失败跳过不中断(容错),
    调用方可据 (url, ok) 组装 images:[{url, file|None}] 结构。
    """
    results: List[Tuple[str, str, bool]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        futures = [
            (img_url, str(dest), pool.submit(_download_one, dest, img_url, timeout, retries, backoff))
            for dest, img_url in tasks
        ]
        for img_url, dest, f in futures:
            results.append((img_url, dest, f.result()))
    return results