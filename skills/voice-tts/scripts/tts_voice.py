"""voice-tts: 法拍房话术 TTS 配音(edge-tts, 免费无 key)。

读 DB data.script(8 角度) → 逐角度 edge-tts 合成 mp3 → assets/<source>/<item_id>/voice/
→ 写 DB data.voice(含时长)。用于后续视频声画对齐。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_VOICE = "zh-CN-YunxiNeural"
TTS_TIMEOUT = 60  # 单文件合成超时(秒): 防 edge-tts websocket 挂死卡住整个进程


def _parse_script(full_script: str) -> list[tuple[str, str]]:
    """解析 data.script → [(角度, 文案)] 保持顺序。"""
    out: list[tuple[str, str]] = []
    if not full_script:
        return out
    for m in re.finditer(r"【(.+?)】([^【]*)", full_script):
        angle, text = m.group(1).strip(), m.group(2).strip()
        if angle and text:
            out.append((angle, text))
    return out


def _mp3_duration(path: Path) -> float:
    """用 imageio-ffmpeg 取 mp3 时长(秒), 字节安全(Windows stderr 非 GBK 可解码)。"""
    try:
        import imageio_ffmpeg
        import subprocess
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([exe, "-i", str(path)], capture_output=True)
        stderr = r.stderr.decode("utf-8", errors="replace")
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", stderr)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _synth(text: str, out: Path, voice: str) -> bool:
    """edge-tts 合成单个 mp3(异步), 失败重试退避; 成功且非空才算。"""
    import edge_tts
    out.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice)
            asyncio.run(asyncio.wait_for(communicate.save(str(out)), timeout=TTS_TIMEOUT))
            if out.exists() and out.stat().st_size > 0:
                return True
            if out.exists():
                out.unlink()
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] tts {out.name} 第{attempt + 1}次失败: {exc}")
        time.sleep(2 * (attempt + 1))  # 限流退避
    return False


def run(source: str, item_id: str, *, voice: str = DEFAULT_VOICE,
        reuse_existing: bool = True) -> dict:
    """为一套房源生成逐角度 mp3 + 整篇 mp3, 返回 data.voice 结构。

    reuse_existing: DB 已有的有效角度(时长>0 且文件在盘)直接保留, 只补缺失角度。
    """
    from db import get_source_data, upsert_listing
    entry = get_source_data(source).get(item_id, {})
    data = entry.get("data") or {}
    script = data.get("script", "")
    angles = _parse_script(script)
    if not angles:
        print(f"[SKIP] {source}/{item_id}: no data.script(先跑 script-writer)")
        return {}

    voice_dir = PROJECT_ROOT / "assets" / source / item_id / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    prev = {}
    if reuse_existing:
        prev = {v["angle"]: v for v in (data.get("voice") or {}).get("files", [])}

    files: list[dict] = []
    full_parts: list[str] = []
    for i, (angle, text) in enumerate(angles, 1):
        name = f"{i:02d}_{angle}.mp3"
        out = voice_dir / name
        old = prev.get(angle)
        if old and (voice_dir / old.get("file", "")).exists() \
                and (voice_dir / old["file"]).stat().st_size > 0 \
                and float(old.get("duration") or 0) > 0:
            files.append(old)
            full_parts.append(f"【{angle}】{text}")
            print(f"  = {old['file']} ({old['duration']}s, 已有跳过)")
            continue
        if not _synth(text, out, voice):
            continue
        files.append({"angle": angle, "file": name, "duration": round(_mp3_duration(out), 2)})
        full_parts.append(f"【{angle}】{text}")
        time.sleep(1.0)  # edge-tts 限流防护
        print(f"  → {name} ({files[-1]['duration']}s)")

    old_voice = data.get("voice") or {}
    combined = ""
    if reuse_existing and old_voice.get("combined") \
            and (voice_dir / old_voice["combined"]).exists():
        combined = old_voice["combined"]
        print(f"  = {combined} (整篇已有跳过)")
    elif full_parts:
        cname = f"{item_id}_full.mp3"
        full_text = "。".join(text for _, text in angles)  # 整篇只连正文, 不读【角度】标记
        if _synth(full_text, voice_dir / cname, voice):
            combined = cname
            print(f"  → {cname} (整篇)")

    voice = {"files": files, "combined": combined}
    new_data = dict(data)
    new_data["voice"] = voice
    ok = upsert_listing({"source": source, "item_id": item_id, "data": new_data})
    print(f"[DB {'OK' if ok else 'FAIL'}] voice({len(files)}条) → {source}/{item_id}")
    return voice


def run_all(source: str = "gpai", limit: int = 5, force: bool = False,
            voice: str = DEFAULT_VOICE):
    """批量配音(幂等: 已有 data.voice 默认跳过, --force 强制)。edge-tts 并发受限, 串行。"""
    from db import get_source_data
    data_map = get_source_data(source)
    done = skipped = 0
    for item_id, entry in data_map.items():
        if done >= limit:
            break
        data = entry.get("data") or {}
        if not data.get("script"):
            continue
        v = data.get("voice")
        # 幂等跳过的条件: 已有 voice 且角度数齐全(缺角度的不完整结果自动重做)
        need = len(_parse_script(data["script"]))
        if not force and v and len(v.get("files", [])) >= need:
            skipped += 1
            continue
        print(f"\n=== {source}/{item_id} ===")
        if run(source, item_id, voice=voice, reuse_existing=not force):
            done += 1
        else:
            skipped += 1
    print(f"\n[DONE] generated={done} skipped(already done)={skipped}")


# ─── CLI ───

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="法拍房话术 TTS 配音(edge-tts, 免费)")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式(已有 voice 则跳过)")
    ap.add_argument("--force", action="store_true", help="批量模式下强制重做")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="音色(默认 zh-CN-YunxiNeural)")
    args = ap.parse_args()

    if args.item_id:
        run(args.source, args.item_id, voice=args.voice)
    elif args.all:
        run_all(args.source, args.limit, force=args.force, voice=args.voice)
    else:
        ap.print_help()
