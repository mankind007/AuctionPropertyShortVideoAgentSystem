"""video-compose: 法拍房宣传短视频合成(可选配音)。

无配音(--no-voiceover): 海报 → 固定时长 concat → 静音 MP4 → data.video
有配音(--voiceover):    海报+音频 → 声画对齐 mux → 带配音 MP4 → data.video + data.video_voiced

不再生成 raw 中间文件再删除, 配音时直接产出最终视频。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"[FATAL] 找不到 ffmpeg(imageio-ffmpeg 未安装): {exc}")

FALLBACK_SEC = 4.0


# ─── 工具 ───

def _find_posters(source: str, item_id: str, suffix: str) -> list[Path]:
    """取某方向的海报(按文件名排序)。suffix: "_v.png" / "_h.png"。"""
    d = PROJECT_ROOT / "assets" / source / item_id / "posters"
    if not d.exists():
        return []
    return sorted(p for p in d.glob(f"poster_*{suffix}"))


def _ffmpeg_concat(posters: list[Path], out: Path, duration: float, fps: int) -> bool:
    """每张海报停留 duration 秒, concat 拼接为静音 MP4。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [FFMPEG, "-y"]
    for p in posters:
        cmd += ["-loop", "1", "-t", f"{duration:g}", "-framerate", str(fps), "-i", str(p)]
    n = len(posters)
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


# ─── 配音合成(mux_voice 逻辑内联) ───

def _poster_angle_map(source: str, item_id: str, orientation: str) -> list[tuple[str, str]]:
    """从 data.script_images 取某方向 [(海报文件名, 角度)] 按顺序。"""
    from db import get_source_data
    data = (get_source_data(source).get(item_id) or {}).get("data") or {}
    si = data.get("script_images") or []
    return [(e["file"], e["angle"]) for e in si if e.get("orientation") == orientation]


def _voice_map(source: str, item_id: str) -> dict[str, dict]:
    """角度 → {file, duration}。"""
    from db import get_source_data
    data = (get_source_data(source).get(item_id) or {}).get("data") or {}
    voice = data.get("voice") or {}
    return {v["angle"]: v for v in (voice.get("files") or [])}


def _mux_duration(posters: list[tuple[Path, str]], audios: list[tuple[Path, float]],
                  out: Path, fps: int) -> bool:
    """每张海报段时长 = 对应音频时长(声画对齐), 音轨逐段 concat 后合成。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    n = len(posters)
    cmd: list[str] = [FFMPEG, "-y"]
    for (p, _), (_, dur) in zip(posters, audios):
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-framerate", str(fps), "-i", str(p)]
    for a, _ in audios:
        cmd += ["-i", str(a)]

    scale = ("scale=min(iw\\,1920):min(ih\\,1920):force_original_aspect_ratio=decrease,"
             "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1")
    vchain = "".join(f"[{i}:v]{scale}[v{i}];" for i in range(n))
    vconcat = f"{''.join(f'[v{i}]' for i in range(n))}concat=n={n}:v=1:a=0[vv]"
    achain = "".join(f"[{n + i}:a]anull[a{i}];" for i in range(n))
    aconcat = f"{''.join(f'[a{i}]' for i in range(n))}concat=n={n}:v=0:a=1[aa]"

    cmd += [
        "-filter_complex", f"{vchain}{vconcat};{achain}{aconcat}",
        "-map", "[vv]", "-map", "[aa]",
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart", "-shortest",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(f"[ERR] mux: {r.stderr.decode('utf-8', errors='replace')[-600:]}")
        return False
    return True


def _mux_voiced(source: str, item_id: str, fps: int) -> dict:
    """声画对齐合成带配音视频, 返回 {orientation: relpath}。"""
    vmap = _voice_map(source, item_id)
    if not vmap:
        print(f"[SKIP] {source}/{item_id}: no voice(先跑 voice-tts)")
        return {}

    posters_dir = PROJECT_ROOT / "assets" / source / item_id / "posters"
    voice_dir = PROJECT_ROOT / "assets" / source / item_id / "voice"
    outdir = PROJECT_ROOT / "assets" / source / item_id / "videos"
    result: dict = {}

    for orientation, suffix in (("vertical", "_v"), ("horizontal", "_h")):
        mapping = _poster_angle_map(source, item_id, orientation)
        if not mapping:
            continue
        posters: list[tuple[Path, str]] = []
        audios: list[tuple[Path, float]] = []
        missing: list[str] = []
        for fname, angle in mapping:
            pf = posters_dir / fname
            vv = vmap.get(angle)
            if not pf.exists():
                missing.append(fname)
            elif not vv:
                missing.append(f"{angle}(无配音)")
            else:
                posters.append((pf, angle))
                audios.append((voice_dir / vv["file"], float(vv.get("duration") or FALLBACK_SEC)))
        if missing:
            print(f"[SKIP] {source}/{item_id} {orientation}: 缺素材 {missing[:3]}")
            continue
        out = outdir / f"{item_id}{suffix}_voiced.mp4"
        if _mux_duration(posters, audios, out, fps):
            result[orientation] = out.relative_to(PROJECT_ROOT).as_posix()
            print(f"[OK] {out}")

    return result


# ─── DB ───

def _write_video(source: str, item_id: str, video: dict, video_voiced: dict | None = None):
    from db import get_source_data, upsert_listing
    entry = get_source_data(source).get(item_id, {})
    new_data = dict(entry.get("data", {}))
    new_data["video"] = video
    if video_voiced:
        new_data["video_voiced"] = video_voiced
    ok = upsert_listing({
        "source": source,
        "item_id": item_id,
        "title": entry.get("title", ""),
        "data": new_data,
    })
    print(f"[DB {'OK' if ok else 'FAIL'}] video → {source}/{item_id} {video}")


# ─── 主流程 ───

def run(source: str, item_id: str, *, duration: float = 4.0, fps: int = 25, voiceover: bool = False) -> dict:
    """为一套房源拼接竖版/横版视频, 返回 {orientation: relpath}。

    voiceover=False: 固定时长 concat, 输出静音 MP4 → data.video
    voiceover=True:  声画对齐 mux, 输出带配音 MP4 → data.video + data.video_voiced
    """
    v_posters = _find_posters(source, item_id, "_v.png")
    h_posters = _find_posters(source, item_id, "_h.png")
    if not v_posters and not h_posters:
        print(f"[SKIP] {source}/{item_id}: no posters(先跑 promo-image)")
        return {}

    outdir = PROJECT_ROOT / "assets" / source / item_id / "videos"

    if voiceover:
        # 直接声画对齐合成, 不生成 raw 中间文件
        result = _mux_voiced(source, item_id, fps=fps)
        if result:
            _write_video(source, item_id, result, video_voiced=result)
        return result

    # 无配音: 固定时长 concat
    video: dict = {}
    def _rel(p: Path) -> str:
        return p.relative_to(PROJECT_ROOT).as_posix()

    if v_posters:
        out = outdir / f"{item_id}_v.mp4"
        if _ffmpeg_concat(v_posters, out, duration, fps):
            video["vertical"] = _rel(out)
            print(f"[OK] {out} ({len(v_posters)} posters x {duration}s)")
    if h_posters:
        out = outdir / f"{item_id}_h.mp4"
        if _ffmpeg_concat(h_posters, out, duration, fps):
            video["horizontal"] = _rel(out)
            print(f"[OK] {out} ({len(h_posters)} posters x {duration}s)")

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
    ap = argparse.ArgumentParser(description="法拍房短视频合成(海报→MP4, 可选配音)")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式(已有视频则跳过)")
    ap.add_argument("--force", action="store_true", help="批量模式下强制重做")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--duration", type=float, default=4.0, help="每张海报停留秒数(无配音时)")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--workers", type=int, default=1, help="批量并发数(ffmpeg 独立进程)")
    ap.add_argument("--voiceover", action="store_true", help="声画对齐合成带配音视频(先跑 voice-tts)")
    args = ap.parse_args()

    if args.item_id:
        run(args.source, args.item_id, duration=args.duration, fps=args.fps, voiceover=args.voiceover)
    elif args.all:
        run_all(args.source, args.limit, force=args.force,
                duration=args.duration, fps=args.fps, workers=args.workers)
    else:
        ap.print_help()
