"""
Stage 2 of the avatar-video pipeline: turn speech audio into an SRT subtitle file,
then optionally burn it into a video.

  python whisper_srt.py speech.wav                       # -> speech.srt
  python whisper_srt.py speech.wav --model medium        # more accurate than small
  python whisper_srt.py --download medium                # fetch the model first
  python whisper_srt.py speech.wav --print-only          # review the transcript

Recognition quality matters for on-screen subtitles, so `medium` is the default
even though `small` runs several times faster; `tiny` mis-renders common Chinese
words badly enough that it is only useful for smoke tests.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import WHISPER_MODELS, whisper_dir  # noqa: E402

# The HF mirror serves the repo fine but its xet backend stalls on big files,
# so downloads go through curl against the plain resolve endpoint.
HF_MIRROR = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
REQUIRED_FILES = ("config.json", "tokenizer.json", "vocabulary.txt", "model.bin")


def srt_time(ts: float) -> str:
    h, rem = divmod(int(ts), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{round((ts - int(ts)) * 1000):03d}"


def download(model: str) -> Path:
    """Fetch the CTranslate2 files into models/avatar-video/whisper/<model>/."""
    import urllib.request

    from config import WHISPER_ROOT

    dest_dir = WHISPER_ROOT / model
    dest_dir.mkdir(parents=True, exist_ok=True)

    base = f"{HF_MIRROR}/Systran/faster-whisper-{model}/resolve/main"
    for name in REQUIRED_FILES:
        dest = dest_dir / name
        if dest.exists() and dest.stat().st_size > 32:
            print(f"[ok] {name} already present ({dest.stat().st_size / 1048576:.1f} MB)")
            continue
        print(f"[..] downloading {name}")
        req = urllib.request.Request(f"{base}/{name}", headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r     {done / 1048576:7.1f} / {total / 1048576:.1f} MB",
                          end="", flush=True)
        print()
    return dest_dir


def transcribe(src: Path, model_name: str, lang: str, beam: int, prompt: str | None):
    from faster_whisper import WhisperModel

    paths = whisper_dir(model_name)
    if not paths.complete:
        print(f"[..] model {model_name} is incomplete, downloading")
        download(model_name)
        if not paths.complete:
            raise SystemExit(f"[ERR] {paths.dir} is still incomplete after download")

    # pass the directory rather than the model name: a name would make
    # faster-whisper ask huggingface_hub for a revision, which fails offline and
    # stalls online when the mirror redirects to the xet backend
    whisper = WhisperModel(str(paths.dir), device="cpu", compute_type="int8")
    segments, info = whisper.transcribe(
        str(src), language=lang, vad_filter=True, beam_size=beam,
        initial_prompt=prompt,
    )

    rows = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            rows.append((seg.start, seg.end, text))
    return rows, info


def write_srt(rows, dest: Path) -> None:
    lines = []
    for i, (start, _end, text) in enumerate(rows, 1):
        lines += [str(i), f"{srt_time(start)} --> {srt_time(_end)}", text, ""]
    dest.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcribe speech audio to SRT")
    ap.add_argument("audio", nargs="?", help="speech audio, wav/mp3/m4a")
    ap.add_argument("--model", default="medium", choices=WHISPER_MODELS)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--srt", default=None, help="output path (default alongside the audio)")
    ap.add_argument("--prompt", default=None,
                    help="initial_prompt to bias punctuation and wording")
    ap.add_argument("--print-only", action="store_true",
                    help="show the transcript without writing a file")
    ap.add_argument("--download", choices=WHISPER_MODELS,
                    help="download a model and exit")
    args = ap.parse_args()

    if args.download:
        dest = download(args.download)
        print(f"[OK] {args.download} ready at {dest}")
        return 0
    if not args.audio:
        ap.error("an audio path is required")

    src = Path(args.audio)
    if not src.exists():
        print(f"[ERR] not found: {src}")
        return 1

    rows, info = transcribe(src, args.model, args.lang, args.beam, args.prompt)
    print(f"[ok] language {info.language} ({info.language_probability:.2f}), "
          f"{len(rows)} segments, model={args.model}")
    for start, end, text in rows:
        print(f"     [{start:6.2f}-{end:6.2f}] {text}")

    if args.print_only:
        return 0
    dest = Path(args.srt) if args.srt else src.with_suffix(".srt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_srt(rows, dest)
    print(f"[OK] srt -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
