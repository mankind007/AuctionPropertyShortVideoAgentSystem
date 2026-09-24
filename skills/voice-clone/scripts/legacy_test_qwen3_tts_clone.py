"""
Test Qwen3-TTS-12Hz-0.6B-Base voice clone with a real-estate auction promo script.

Run from repo root:
    .venv\\Scripts\\python.exe skills\\voice-clone\\scripts\\legacy_test_qwen3_tts_clone.py
(正式入口: skills/voice-clone/scripts/clone_voice.py)

Environment:
- Uses the local model at models/tts/Qwen3-TTS-12Hz-0.6B-Base
- Requires qwen-tts (already installed in .venv)
- SoX is required by qwen-tts/torchaudio; if missing, the script prints a setup hint.
- CPU-only torch is OK but slow; set device_map="cuda:0" if a GPU is available.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import tempfile
import urllib.request
import warnings
from pathlib import Path

import soundfile as sf
import torch

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "models" / "tts" / "Qwen3-TTS-12Hz-0.6B-Base"
PROMO_CSV = REPO_ROOT / "assets" / "短视频宣传话术.csv"
OUTPUT_DIR = REPO_ROOT / "assets" / "tts_test_output"

# Official Qwen demo reference audio (English, ~8 s). Used as fallback when no
# local reference audio is supplied. Downloaded on first run.
DEFAULT_REF_AUDIO_URL = (
    "https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-TTS-Repo/clone.wav"
)
DEFAULT_REF_TEXT = (
    "Okay. Yeah. I resent you. I love you. I respect you. "
    "But you know what? You blew it! And thanks to you."
)

# A Chinese reference (CCTV clip) is also provided in assets; its transcript is
# the first sentence of the 2023-11-11 Xinhua interview.
CCTV_REF_AUDIO = REPO_ROOT / "assets" / "cctv_audio_segment.mp3"
CCTV_REF_TEXT = (
    "今年以来，房地产市场备受关注，一系列政策效果怎么样，"
    "如何看待房地产市场，如何重构房地产发展模式？"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def pick_promo_script(csv_path: Path) -> tuple[str, str, str]:
    """Pick a fixed-field promo script that does not need variable filling."""
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get("话术类型") == "固定"]

    if not rows:
        raise RuntimeError("No fixed promo scripts found in CSV.")

    row = random.choice(rows)
    return row["角度"], row["子主题"], row["话术模板"]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_reference_audio(dst: Path, url: str = DEFAULT_REF_AUDIO_URL) -> None:
    if dst.exists():
        return
    print(f"Downloading reference audio to {dst} ...")
    ensure_dir(dst.parent)
    urllib.request.urlretrieve(url, dst)
    print("Reference audio downloaded.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test Qwen3-TTS voice clone with a promo script."
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=MODEL_DIR,
        help="Local Qwen3-TTS-12Hz-0.6B-Base directory.",
    )
    parser.add_argument(
        "--ref-audio",
        type=str,
        default="cctv",
        choices=["cctv", "official"],
        help="Reference audio source: cctv=local Chinese clip, official=English demo WAV.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Device for inference: auto/cpu/cuda:0.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory to write output WAV files.",
    )
    args = parser.parse_args()

    if not MODEL_DIR.exists():
        print(f"ERROR: Model directory not found: {MODEL_DIR}", file=sys.stderr)
        return 1

    if args.device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device

    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    print(f"Device: {device}, dtype: {dtype}")

    # Resolve reference audio
    if args.ref_audio == "cctv":
        if not CCTV_REF_AUDIO.exists():
            print(
                f"WARNING: {CCTV_REF_AUDIO.name} not found, falling back to official reference.",
                file=sys.stderr,
            )
            ref_audio_path = args.output_dir / "clone.wav"
            ref_text = DEFAULT_REF_TEXT
            download_reference_audio(ref_audio_path)
        else:
            ref_audio_path = CCTV_REF_AUDIO
            ref_text = CCTV_REF_TEXT
    else:
        ref_audio_path = args.output_dir / "clone.wav"
        ref_text = DEFAULT_REF_TEXT
        download_reference_audio(ref_audio_path)

    # Pick a promo script
    angle, topic, script = pick_promo_script(PROMO_CSV)
    print(f"Selected promo script [{angle} / {topic}]:")
    print(f"  {script}")

    # Lazy import so the script can show helpful errors before heavy loading
    print("\nImporting qwen_tts... (SoX warning is normal if SoX is not on PATH)")
    try:
        from qwen_tts import Qwen3TTSModel
    except ImportError as exc:
        print(f"ERROR: qwen_tts import failed: {exc}", file=sys.stderr)
        print("Run: .venv\\Scripts\\python.exe -m pip install qwen-tts", file=sys.stderr)
        return 1

    # Load model
    print(f"\nLoading model from {args.model_dir} ...")
    try:
        model = Qwen3TTSModel.from_pretrained(
            str(args.model_dir),
            device_map=device,
            dtype=dtype,
            attn_implementation="eager",
        )
    except Exception as exc:
        print(f"ERROR: Failed to load model: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        print(
            "\nTroubleshooting hints:\n"
            "1. SoX must be installed and on PATH (qwen-tts requires it).\n"
            "   Windows: choco install sox.portable\n"
            "   Or download from https://sourceforge.net/projects/sox/files/sox/\n"
            "2. If a segmentation fault occurs with CPU torch, try using a GPU\n"
            "   or reinstall torch with a matching CUDA version.\n"
            "3. flash-attn is optional but recommended for GPU inference.\n",
            file=sys.stderr,
        )
        return 1

    # Voice clone generation
    print("\nGenerating cloned speech...")
    try:
        wavs, sr = model.generate_voice_clone(
            text=script,
            language="Chinese",
            ref_audio=str(ref_audio_path),
            ref_text=ref_text,
        )
    except Exception as exc:
        print(f"ERROR: Generation failed: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    # Save outputs
    ensure_dir(args.output_dir)
    ref_name = "cctv" if args.ref_audio == "cctv" and CCTV_REF_AUDIO.exists() else "official"
    out_wav = args.output_dir / f"tts_clone_{ref_name}_{topic}.wav"
    out_ref = args.output_dir / f"tts_clone_{ref_name}_{topic}_reference.wav"

    sf.write(str(out_wav), wavs[0], sr)
    # Copy reference audio next to output for easy A/B comparison
    import shutil

    shutil.copy2(str(ref_audio_path), str(out_ref))

    print(f"\nOutput written to:")
    print(f"  Generated: {out_wav}")
    print(f"  Reference: {out_ref}")
    print("\nListen to both files and compare whether the cloned voice matches the reference.")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    sys.exit(main())
