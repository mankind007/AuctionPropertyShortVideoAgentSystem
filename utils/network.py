"""网络不佳/断网时的 goto 重试封装(带 10 分钟强制刷新)。

两爬虫共用: 列表页打开、翻页、子页打开统一经 goto_with_retry 保证
网络短暂抖动时不崩;每累到 10 分钟打印提示并强制 goto 刷新一次(等价继续重试)。
"""
from __future__ import annotations

import asyncio
from typing import Optional

REFRESH_INTERVAL_S = 600  # 10 分钟


async def goto_with_retry(page, url: str, *, timeout: int = 45000,
                          wait_ms: int = 1000,
                          warn: Optional[str] = None) -> bool:
    """打开/刷新 url,兼容网络不佳或断网。

    每 3s 重试一次;每累计到 10 分钟打印"强制刷新"提示(仍重试 goto)。
    返回 True 表示已成功打开。页面对象需有 goto/wait_for_timeout。
    """
    waited = 0
    while True:
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if wait_ms:
                await page.wait_for_timeout(wait_ms)
            return True
        except Exception as e:  # noqa: BLE001
            waited += 3
            loc = f"({warn}) " if warn else ""
            force = " — 已达10分钟,强制刷新继续重试" if waited % REFRESH_INTERVAL_S == 0 else ""
            print(f"  [网络] {loc}goto 失败: {type(e).__name__}: {e} — "
                  f"已等 {waited}s{force}…", flush=True)
            await asyncio.sleep(3)