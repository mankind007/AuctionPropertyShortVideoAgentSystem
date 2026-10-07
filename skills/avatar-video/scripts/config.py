"""
Shared configuration and helpers for the avatar-video skill.

ComfyUI lives outside this repository and the pipeline is split across three
stages, so the locations are resolved here once and every script imports them.
"""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# ComfyUI deployment on this machine. Override with the AVATAR_VIDEO_* env vars
# when the install moves, rather than editing every script.
COMFY_ROOT = Path(os.environ.get("AVATAR_VIDEO_COMFY_ROOT", r"D:\Program\ComfyUI"))
COMFY_URL = os.environ.get("AVATAR_VIDEO_COMFY_URL", "http://127.0.0.1:8188")
COMFY_INPUT = COMFY_ROOT / "input"
COMFY_TEMP = COMFY_ROOT / "temp"

OUT_DIR = Path(os.environ.get("AVATAR_VIDEO_OUT", REPO / "assets" / "avatar_video"))

# The server must be started with these or the 14B model OOMs / crashes the
# Windows GPU mapping layer. See references/部署与调参.md for the full story.
COMFY_ARGS = ["--disable-async-offload", "--disable-cuda-malloc"]

WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
WHISPER_DEFAULT = "medium"
WHISPER_REPO = "Systran/faster-whisper-{model}"
REQUIRED_FILES = ("config.json", "tokenizer.json", "vocabulary.txt", "model.bin")

# Whisper weights follow the same layout as the other skills' weights
# (models/lip-sync/..., models/tts/...) so nothing large lands on the system
# drive. huggingface_hub's own cache also doubles the footprint because Windows
# cannot symlink, keeping a real copy under blobs/.
WHISPER_ROOT = Path(os.environ.get(
    "AVATAR_VIDEO_WHISPER_DIR", REPO / "models" / "avatar-video" / "whisper"))

SUBTITLE_STYLES = ("corporate", "bottom")


@dataclass(frozen=True)
class WhisperModelPaths:
    """Where faster-whisper expects a CTranslate2 model directory.

    huggingface_hub lays caches out as <root>/snapshots/<commit>/files, but a
    hand-populated cache may use any single subdirectory name, so the snapshot
    directory is discovered rather than assumed.
    """

    root: Path

    @property
    def dir(self) -> Path:
        return self.root

    @property
    def complete(self) -> bool:
        if not self.dir.is_dir():
            return False
        for f in REQUIRED_FILES:
            p = self.dir / f
            if not p.exists() or p.stat().st_size <= 32:
                return False
        return True

    @property
    def size_mb(self) -> float:
        return sum(p.stat().st_size for p in self.dir.glob("*") if p.is_file()) / 1048576


def whisper_dir(model: str) -> WhisperModelPaths:
    """Resolve a model directory: project location first, HF cache as fallback."""
    if model not in WHISPER_MODELS:
        raise ValueError(f"unknown whisper model {model!r}, pick one of {WHISPER_MODELS}")
    local = WhisperModelPaths(WHISPER_ROOT / model)
    if local.complete:
        return local
    # a cache populated by huggingface_hub uses snapshots/<commit>/ subdirs
    cache = os.environ.get("HF_HOME")
    root = Path(cache) / "hub" if cache else Path.home() / ".cache" / "huggingface" / "hub"
    snaps = root / f"models--Systran--faster-whisper-{model}" / "snapshots"
    if snaps.is_dir():
        for child in sorted(snaps.iterdir()):
            if child.is_dir() and all((child / f).exists() for f in REQUIRED_FILES):
                return WhisperModelPaths(child)
    return local


def comfy_running(url: str = COMFY_URL, timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/system_stats", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    import json

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/prompt", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def history(url: str, prompt_id: str, timeout: float = 10.0) -> dict:
    import json

    with urllib.request.urlopen(f"{url}/history/{prompt_id}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def post_json_with_retry(url: str, payload: dict, attempts: int = 3, delay: float = 2.0):
    last = None
    for i in range(attempts):
        try:
            return post_json(url, payload)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            if not comfy_running(url):
                raise RuntimeError(
                    f"ComfyUI is not reachable at {url}. Start it first:\n"
                    f"  {COMFY_ROOT}\\.venv\\Scripts\\python.exe main.py "
                    f"{' '.join(COMFY_ARGS)}"
                ) from exc
            time.sleep(delay * (i + 1))
    raise last  # type: ignore[misc]


import time  # noqa: E402  (kept below the helpers that reference it lazily)


def start_comfy(log_name: str = "comfy_avatar.log") -> subprocess.Popen | None:
    """Launch ComfyUI with the flags this model needs, if it is not up already."""
    if comfy_running():
        return None
    exe = COMFY_ROOT / ".venv" / "Scripts" / "python.exe"
    if not exe.exists():
        raise FileNotFoundError(f"ComfyUI interpreter not found: {exe}")
    logs = Path(os.environ.get("TEMP", "."))
    out = open(logs / f"{log_name}.out", "w", encoding="utf-8")
    err = open(logs / f"{log_name}.err", "w", encoding="utf-8")
    return subprocess.Popen(
        [str(exe), "main.py", "--listen", "127.0.0.1", "--port", "8188", *COMFY_ARGS],
        cwd=str(COMFY_ROOT), stdout=out, stderr=err,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
