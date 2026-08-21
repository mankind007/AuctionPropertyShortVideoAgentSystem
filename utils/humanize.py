"""人类式鼠标轨迹生成(强化滑块拖动,降低行为风控识别)。

仅含可测试的纯函数: 生成贝塞尔曲线轨迹点 + 过冲/回退。
页面事件派发放在调用方(ali crawler `_try_auto_slide`),以免耦合 playwright。
"""
from __future__ import annotations

import math
import random
from typing import List, Tuple

Point = Tuple[float, float]


def _bezier(t: float, p0: Point, p1: Point, p2: Point, p3: Point) -> Point:
    """三阶贝塞尔曲线插值。"""
    mt = 1 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    d = t * t * t
    x = a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0]
    y = a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]
    return (x, y)


def human_like_path(x0: float, y0: float, x1: float, y1: float,
                    *, n: int = 40, jitter: float = 1.2,
                    overshoot_frac: float = 0.08) -> List[Point]:
    """生成从 (x0,y0) 到 (x1,y1) 的人类式拖动轨迹点。

    特性:
    - 贝塞尔曲线 + 随机控制点(加速度/减速自然)
    - 随机 lateral 抖动(jitter)
    - 到达终点前略微**过冲** overshoot_frac,然后回退到终点(模拟瞄准过头再修正)
    - 起点/终点与目标一致(终点贴近目标,抖动后归零)
    """
    # 随机控制点: p1 在 x 方向偏 1/3 处且带随机横向偏移, p2 在 2/3 处
    cp1 = (x0 + (x1 - x0) * 0.3 + random.uniform(-30, 30),
           y0 + random.uniform(-8, 8))
    cp2 = (x0 + (x1 - x0) * 0.7 + random.uniform(-30, 30),
           y0 + random.uniform(-8, 8))
    pts: List[Point] = []
    for i in range(n + 1):
        t = i / n
        x, y = _bezier(t, (x0, y0), cp1, cp2, (x1, y1))
        pts.append((x + random.uniform(-jitter, jitter),
                    y + random.uniform(-jitter / 2, jitter / 2)))
    # 过冲: 超出终点 overshoot_frac 距离, 再回退
    dx = x1 - x0
    overshoot = abs(dx) * overshoot_frac * random.uniform(0.6, 1.4)
    sign = 1.0 if dx >= 0 else -1.0
    over_x = x1 + sign * overshoot
    pts.append((over_x, y0 + random.uniform(-jitter, jitter)))
    # 回退到终点(2-3 步,模拟修正)
    cur_x = over_x
    for _ in range(random.randint(2, 3)):
        cur_x += (x1 - cur_x) * random.uniform(0.3, 0.5)
        pts.append((cur_x, y0 + random.uniform(-jitter, jitter / 2)))
    # 最后一点贴上终点(去抖)
    pts[-1] = (x1, y0)
    return pts


def human_drag_timing(n_pts: int, *, min_total_ms: float = 1500.0,
                      max_total_ms: float = 3200.0) -> List[float]:
    """返回 n_pts-1 个段间隔毫秒数(列表累积时用于 wait_for_timeout)。

    非匀速: 起慢/末慢, 中段快; 随机插入 1-2 次较长停顿(犹豫)。
    """
    if n_pts <= 1:
        return []
    total = random.uniform(min_total_ms, max_total_ms)
    # n_pts - 1 个间隔段(段与段之间)
    n_segs = n_pts - 1
    weights = []
    for i in range(n_segs):
        t = i / max(1, (n_segs - 1))
        w = math.exp(-8 * (t - 0.5) ** 2) + 0.3
        weights.append(w + random.uniform(0, 0.2))
    s = sum(weights)
    # 基线段: 缩放到 total,但为暂停腾出预算;暂停插入在随机位置(犹豫)
    pause_slots = [i for i in range(1, n_segs) if random.random() < 0.18]
    n_pause = len(pause_slots)
    pause_budget = sum(random.uniform(400, 950) for _ in range(n_pause))
    base_budget = max(total - pause_budget, total * 0.3)
    segs = [(w / s) * base_budget for w in weights]
    # 插入暂停
    out: List[float] = []
    pause_set = {i: 0 for i in pause_slots}
    for i in pause_slots:
        pause_set[i] = random.uniform(400, 950)
    for i in range(n_segs):
        ms = segs[i]
        if i in pause_set:
            ms += pause_set[i]
        out.append(max(1.0, ms))
    # 归一化微调(保持总和在 [total*0.85, total*1.15])
    cur_sum = sum(out)
    if cur_sum > 0:
        scale = total / cur_sum
        out = [max(1.0, d * scale) for d in out]
    return out
