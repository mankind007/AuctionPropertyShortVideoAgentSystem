"""video-compose: 法拍房宣传短视频合成(静音, TTS 后续叠加)。

读 promo-image 生成的海报(poster_*_v.png/_h.png) → 按序 concat 拼接 → 输出
assets/<source>/<item_id>/video/<item_id>_{v,h}.mp4 → 写 DB data.video。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"[FATAL] 找不到 ffmpeg(imageio-ffmpeg 未安装): {exc}")


# ─── 工具 ───

def _find_posters(source: str, item_id: str, suffix: str) -> list[Path]:
    """取某方向的海报(按文件名排序)。suffix: "_v.png" / "_h.png"。
    海报位于 assets/<source>/<item_id>/posters/ (promo-image 输出)。"""
    d = PROJECT_ROOT / "assets" / source / item_id / "posters"
    if not d.exists():
        return []
    return sorted(p for p in d.glob(f"poster_*{suffix}"))


def _ffmpeg_concat(posters: list[Path], out: Path, duration: float, fps: int) -> bool:
    """每张海报停留 duration 秒, concat 拼接为静音 MP4。

    每路输入先 scale 成偶数宽高(yuv420p/libx264 要求偶数尺寸, 奇数海报会编码失败)。
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [FFMPEG, "-y"]
    for p in posters:
        cmd += ["-loop", "1", "-t", f"{duration:g}", "-framerate", str(fps), "-i", str(p)]
    n = len(posters)
    # 长边限 1920(超大的 4096x7282 会超 libx264 宏块上限编码失败), 不放大, 再偶数化(yuv420p 要求)
    scale = ("scale=min(iw\\,1920):min(ih\\,1920):force_original_aspect_ratio=decrease,"
             "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1")
    chains = "".join(f"[{i}:v]{scale}[v{i}];" for i in range(n))
    filter_complex = f"{chains}{''.join(f'[v{i}]' for i in range(n))}concat=n={n}:v=1:a=0[v]"
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-r", str(fps), "-an",
        "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[ERR] ffmpeg: {r.stderr[-600:]}")
        return False
    return True


# ─── DB ───

def _write_video(source: str, item_id: str, video: dict):
    from db import get_source_data, upsert_listing
    entry = get_source_data(source).get(item_id, {})
    new_data = dict(entry.get("data", {}))
    new_data["video"] = video
    ok = upsert_listing({
        "source": source,
        "item_id": item_id,
        "title": entry.get("title", ""),
        "data": new_data,
    })
    print(f"[DB {'OK' if ok else 'FAIL'}] video → {source}/{item_id} {video}")


# ─── 主流程 ───

def run(source: str, item_id: str, *, duration: float = 4.0, fps: int = 25) -> dict:
    """为一套房源拼接竖版/横版视频, 返回 {orientation: relpath}。"""
    v_posters = _find_posters(source, item_id, "_v.png")
    h_posters = _find_posters(source, item_id, "_h.png")
    if not v_posters and not h_posters:
        print(f"[SKIP] {source}/{item_id}: no posters(先跑 promo-image)")
        return {}

    outdir = PROJECT_ROOT / "assets" / source / item_id / "videos"
    video: dict = {}

    def _rel(p: Path) -> str:
        return p.relative_to(PROJECT_ROOT).as_posix()

    if v_posters:
        out = outdir / f"{item_id}_v.mp4"
        if _ffmpeg_concat(v_posters, out, duration, fps):
            video["vertical"] = _rel(out)
            print(f"[OK] {out} ({len(v_posters)} posters × {duration}s)")
    if h_posters:
        out = outdir / f"{item_id}_h.mp4"
        if _ffmpeg_concat(h_posters, out, duration, fps):
            video["horizontal"] = _rel(out)
            print(f"[OK] {out} ({len(h_posters)} posters × {duration}s)")

    if video:
        _write_video(source, item_id, video)
    return video


def run_all(source: str = "gpai", limit: int = 5, force: bool = False,
            duration: float = 4.0, fps: int = 25, workers: int = 1):
    """批量拼接(幂等: 已有 data.video 默认跳过, --force 强制; workers>1 并行)。"""
    from db import get_source_data
    data_map = get_source_data(source)
    items = [it for it, e in data_map.items()
             if (e.get("data") or {}).get("script_images")
             and (force or not (e.get("data") or {}).get("video"))]
    items = items[:limit] if limit and limit > 0 else items

    def _do(it):
        print(f"\n=== {source}/{it} ===", flush=True)
        return bool(run(source, it, duration=duration, fps=fps))

    done = skipped = 0
    if workers > 1 and len(items) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_do, items))
        done = sum(1 for r in results if r)
        skipped = len(items) - done
    else:
        for it in items:
            if _do(it):
                done += 1
            else:
                skipped += 1
    print(f"\n[DONE] generated={done} skipped(already done)={skipped}")


# ─── CLI ───

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="法拍房短视频合成(海报→静音MP4)")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式(已有视频则跳过)")
    ap.add_argument("--force", action="store_true", help="批量模式下强制重做")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--duration", type=float, default=4.0, help="每张海报停留秒数")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--workers", type=int, default=1, help="批量并发数(ffmpeg 独立进程)")
    args = ap.parse_args()

    if args.item_id:
        run(args.source, args.item_id, duration=args.duration, fps=args.fps)
    elif args.all:
        run_all(args.source, args.limit, force=args.force,
                duration=args.duration, fps=args.fps, workers=args.workers)
    else:
        ap.print_help()
