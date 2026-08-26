"""video-compose/mux_voice: 视频+配音合成。

把 voice-tts 生成的逐角度 mp3 混入视频: 每张海报的展示时长 = 该角度音频时长,
整条音轨 = 逐角度音频按海报顺序 concat, 声画对齐, 输出 <id>_{v,h}_voiced.mp4。

前置: 已有 script_images(promo-image) + voice(voice-tts)。
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


# ─── 素材映射(读 DB) ───

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


# ─── 合成 ───

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


def run(source: str, item_id: str, *, fps: int = 25) -> dict:
    """为一套房源合成竖版/横版带配音视频, 返回 {orientation: relpath}。"""
    voice_map = _voice_map(source, item_id)
    if not voice_map:
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
            vv = voice_map.get(angle)
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

    if result:
        from db import get_source_data, upsert_listing
        entry = get_source_data(source).get(item_id, {})
        new_data = dict(entry.get("data", {}))
        new_data["video_voiced"] = result
        ok = upsert_listing({"source": source, "item_id": item_id, "data": new_data})
        print(f"[DB {'OK' if ok else 'FAIL'}] video_voiced → {source}/{item_id} {result}")
    return result


def run_all(source: str = "gpai", limit: int = 5, force: bool = False, fps: int = 25):
    """批量带配音合成(幂等: 已有 video_voiced 默认跳过, --force 强制)。"""
    from db import get_source_data
    data_map = get_source_data(source)
    done = skipped = 0
    for item_id, entry in data_map.items():
        if done >= limit:
            break
        data = entry.get("data") or {}
        if not data.get("voice"):
            continue
        if not force and data.get("video_voiced"):
            skipped += 1
            continue
        print(f"\n=== {source}/{item_id} ===")
        if run(source, item_id, fps=fps):
            done += 1
        else:
            skipped += 1
    print(f"\n[DONE] generated={done} skipped(already done)={skipped}")


# ─── CLI ───

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="视频+配音合成(海报段时长=音频时长, 声画对齐)")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式(已有 video_voiced 则跳过)")
    ap.add_argument("--force", action="store_true", help="批量模式下强制重做")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--fps", type=int, default=25)
    args = ap.parse_args()

    if args.item_id:
        run(args.source, args.item_id, fps=args.fps)
    elif args.all:
        run_all(args.source, args.limit, force=args.force, fps=args.fps)
    else:
        ap.print_help()
