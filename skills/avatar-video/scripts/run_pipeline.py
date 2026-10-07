"""
One-shot pipeline for the avatar-video skill: portrait + speech -> subtitled video.

  python run_pipeline.py --image man.png --audio speech.wav
  python run_pipeline.py --image man.png --audio speech.wav --area 180000
  python run_pipeline.py --image man.png --audio speech.wav --no-video

Each stage is skippable so a failed generation can be resumed without redoing
the sampling work, and --force re-runs stages whose output already exists.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import OUT_DIR  # noqa: E402


def run(script: str, *argv: str) -> int:
    cmd = [sys.executable, str(HERE / script), *argv]
    # Use UTF-8 encoding for subprocess output to avoid GBK encoding issues on Windows
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # Avoid printing non-ASCII in the parent process
    safe_cmd = " ".join(cmd[1:]).encode("ascii", "replace").decode("ascii")
    print(f"\n$ {safe_cmd}\n" + "-" * 60, flush=True)
    return subprocess.call(cmd, env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description="portrait + speech -> subtitled avatar video")
    ap.add_argument("--image", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--area", type=int, default=256_000, help="pixel budget, lower is faster")
    ap.add_argument("--model", default="medium", help="whisper model for subtitles")
    ap.add_argument("--style", default="corporate", choices=["corporate", "bottom"])
    ap.add_argument("--name", default=None, help="output stem, default from the audio name")
    ap.add_argument("--no-video", action="store_true", help="subtitles only, reuse an existing mp4")
    ap.add_argument("--no-subs", action="store_true", help="video only, skip subtitles")
    ap.add_argument("--force", action="store_true", help="redo stages that already have output")
    args = ap.parse_args()

    stem = args.name or Path(args.audio).stem
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{stem}_sub.mp4"

    if args.no_video:
        raw = out_dir / f"{stem}.mp4"
        if not raw.exists():
            cands = sorted(out_dir.glob(f"{stem}*"))
            cands = [c for c in cands if c.suffix == ".mp4" and "sub" not in c.stem]
            if not cands:
                print(f"[ERR] no base mp4 for {stem} in {out_dir}")
                return 1
            raw = cands[0]
    else:
        raw = out_dir / f"{stem}.mp4"
        if args.force or not raw.exists():
            rc = run("generate_video.py",
                     "--image", args.image, "--audio", args.audio,
                     "--area", str(args.area), "--output", str(raw))
            if rc != 0:
                return rc
        else:
            print(f"[ok] reusing {raw}")
        if not raw.exists():
            print(f"[ERR] expected {raw} after generation")
            return 1

    if args.no_subs:
        print(f"[OK] {raw}")
        return 0

    srt = out_dir / f"{stem}.srt"
    if args.force or not srt.exists():
        rc = run("whisper_srt.py", args.audio, "--model", args.model, "--srt", str(srt))
        if rc != 0:
            return rc
    else:
        print(f"[ok] reusing {srt}")

    rc = run("burn_subtitle.py", str(raw), str(srt), "-o", str(final),
             "--style", args.style)
    if rc != 0:
        return rc

    print("\n" + "=" * 60)
    print(f"[OK] final video: {final}")
    print(f"[OK] subtitles  : {srt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
