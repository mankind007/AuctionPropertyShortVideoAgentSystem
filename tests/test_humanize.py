"""utils/humanize 契约测试: 轨迹生成器结构稳定性。"""
from __future__ import annotations

import random

import pytest

from utils.humanize import human_like_path, human_drag_timing


def test_path_endpoints():
    path = human_like_path(100, 50, 300, 50, n=20, jitter=0.0)
    start, end = path[0], path[-1]
    assert abs(start[0] - 100) < 1.0
    assert abs(end[0] - 300) < 1.0
    assert abs(end[1] - 50) < 1.0


def test_path_overshoot_and_return():
    """路径应在终点外过冲一次, 然后回退。"""
    random.seed(42)
    path = human_like_path(0, 100, 200, 100, n=25, jitter=0.0)
    xs = [p[0] for p in path]
    # 最大值应超过 200(过冲)
    assert max(xs) > 200


def test_path_reverse():
    """从右向左拖动: x 趋势递减。"""
    path = human_like_path(300, 50, 100, 50, n=20, jitter=0.0)
    forward = sum(p[0] for p in path[:15]) / 15
    backward = sum(p[0] for p in path[-5:]) / 5
    assert backward < forward


def test_path_length():
    path = human_like_path(100, 50, 300, 50, n=10)
    # n+1 贝塞尔点 + 过冲段 + 回退段(2-3 点)
    assert len(path) >= 13


def test_timings_length_and_positive():
    """计时段数 = 路径点数 - 1, 全部为正。"""
    path = human_like_path(0, 50, 200, 50, n=15, jitter=0.5)
    timings = human_drag_timing(len(path), min_total_ms=100, max_total_ms=200)
    assert len(timings) == len(path) - 1
    assert all(t >= 1.0 for t in timings)


def test_timings_total_in_range():
    for seed in range(5):
        random.seed(seed)
        timings = human_drag_timing(20, min_total_ms=500, max_total_ms=1000)
        total = sum(timings)
        assert 450 < total < 1100


def test_timings_inserts_pause():
    """计时中应含较长停顿(>300ms 的犹豫点)出现概率。"""
    random.seed(7)
    delays_seen = 0
    for _ in range(20):
        timings = human_drag_timing(30, min_total_ms=800, max_total_ms=1500)
        if any(t > 300 for t in timings):
            delays_seen += 1
    assert delays_seen > 0
