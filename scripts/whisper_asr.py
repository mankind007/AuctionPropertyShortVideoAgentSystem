"""
用 faster-whisper 对视频/音频做语音识别，生成 SRT 字幕文件。

用法:
  python scripts/whisper_asr.py <video_or_audio> [-o output.srt] [--model medium|small] [--lang zh] [--vad]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("MALLOC_ARENA_MAX", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import torch  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

_TORCH_LIB = str(Path(torch.__file__).parent / "lib")
os.add_dll_directory(_TORCH_LIB)
os.environ["PATH"] = _TORCH_LIB + os.pathsep + os.environ["PATH"]

MODEL_ROOT = Path(__file__).resolve().parents[1] / "models" / "avatar-video" / "whisper"


def srt_time(ts: float) -> str:
    h, rem = divmod(int(ts), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{round((ts - int(ts)) * 1000):03d}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Whisper ASR → SRT")
    ap.add_argument("input", help="视频或音频文件路径")
    ap.add_argument("-o", "--output", default=None, help="输出 SRT 路径")
    ap.add_argument("--model", default="medium", choices=["small", "medium"])
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--vad", action="store_true", help="启用 VAD 过滤静音")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"[ERR] not found: {src}")
        return 1

    model_dir = MODEL_ROOT / args.model
    if not model_dir.exists():
        print(f"[ERR] model not found: {model_dir}")
        return 1

    compute = "float16" if args.device == "cuda" else "int8"
    print(f"[..] loading {args.model} on {args.device}", flush=True)
    whisper = WhisperModel(str(model_dir), device=args.device, compute_type=compute, cpu_threads=1, num_workers=1)
    print("[ok] model loaded", flush=True)

    segments, info = whisper.transcribe(
        str(src),
        language=args.lang,
        vad_filter=args.vad,
        beam_size=5,
    )

    rows = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            rows.append((seg.start, seg.end, text))
            print(f"[{seg.start:6.2f}-{seg.end:6.2f}] {text}")

    lines = []
    for i, (start, end, text) in enumerate(rows, 1):
        lines += [str(i), f"{srt_time(start)} --> {srt_time(end)}", text, ""]

    out = Path(args.output) if args.output else src.with_suffix(".srt")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] lang={info.language} ({info.language_probability:.2f}) segments={len(rows)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())