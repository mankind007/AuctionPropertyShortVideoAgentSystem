"""
Stage 3 of the avatar-video pipeline: burn an SRT subtitle file into a video.

  python burn_subtitle.py video.mp4 subtitles.srt
  python burn_subtitle.py video.mp4 subs.srt --style bottom

Two looks are available: `corporate` (light font on a translucent dark bar,
suited to company profiles) and `bottom` (outlined white text, the usual default).

The subtitle filter cannot read non-ASCII paths on Windows and chokes on the
drive-letter colon, so the SRT is staged into a temp directory and referenced by
a bare relative filename while ffmpeg runs from there.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# ASS colours are &HAABBGGRR
STYLES = {
    "corporate": (
        "FontName=Microsoft YaHei,"
        "FontSize=15,"
        "PrimaryColour=&H00FFFFFF,"
        "SecondaryColour=&H00FFFFFF,"
        "OutlineColour=&HC0000000,"
        "BackColour=&HA0000000,"
        "BorderStyle=3,"      # opaque box behind the glyphs
        "Outline=8,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=60"
    ),
    "bottom": (
        "FontName=Microsoft YaHei,"
        "FontSize=18,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=40"
    ),
}


def probe_duration(video: Path) -> float | None:
    proc = subprocess.run([FFMPEG, "-i", str(video)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return None


def burn(video: Path, srt: Path, out: Path, style: str, reencode_audio: bool) -> int:
    stage = Path(tempfile.gettempdir()) / "avatar_video_subs"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(srt, stage / "sub.srt")

    vf = f"subtitles=filename=sub.srt:force_style='{STYLES[style]}'"
    cmd = [FFMPEG, "-y", "-i", str(video.resolve()), "-vf", vf]
    cmd += ["-c:a", "aac", "-b:a", "192k"] if reencode_audio else ["-c:a", "copy"]
    cmd += ["-movflags", "+faststart", str(out.resolve())]

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(stage))
    if proc.returncode != 0:
        print(proc.stderr[-2000:])
        return 1

    dur = probe_duration(out)
    print(f"[OK] {out}  ({out.stat().st_size / 1048576:.2f} MB"
          + (f", {dur:.2f}s" if dur else "") + ")")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Burn SRT subtitles into a video")
    ap.add_argument("video")
    ap.add_argument("srt")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--style", default="corporate", choices=sorted(STYLES))
    ap.add_argument("--reencode-audio", action="store_true",
                    help="re-encode audio instead of stream copy")
    args = ap.parse_args()

    video, srt = Path(args.video), Path(args.srt)
    for p in (video, srt):
        if not p.exists():
            print(f"[ERR] not found: {p}")
            return 1

    if args.output:
        out = Path(args.output)
    else:
        out = video.with_name(video.stem + "_sub" + video.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)

    return burn(video, srt, out, args.style, args.reencode_audio)


if __name__ == "__main__":
    raise SystemExit(main())
