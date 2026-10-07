"""
Stage 1 of the avatar-video pipeline: generate a talking-head video with
InfiniteTalk running inside ComfyUI.

Any source image works. The script measures the image, picks a resolution that
matches its aspect ratio on the model's /16 grid under a pixel budget, and
switches the resize node to a fitting mode so the subject is never cropped.

  python generate_video.py --image man.png --audio speech.wav
  python generate_video.py --image man.png --audio speech.wav --area 180000
  python generate_video.py --check
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    COMFY_INPUT, COMFY_ROOT, COMFY_URL, OUT_DIR,
    comfy_running, history, post_json_with_retry, start_comfy, whisper_dir,
)

WF_REL = "custom_nodes/InfiniteTalk/example_workflows/wanvideo_infinitetalk_single_example.json"
GRID = 16                       # VAE 8x downsample * patch 2
DEFAULT_AREA = 256_000          # ~21k seq tokens, about 3.5 min per 10s clip
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

NODE_IMAGE = "202"    # ImageOrVideoUpload
NODE_AUDIO = "125"    # LoadAudio
NODE_RESIZE = "171"   # ImageResizeKJv2
NODE_ENCODE = "192"   # WanVideoImageToVideoEncode

DEFAULT_PROMPT = ("A man in a black shirt professionally introducing a company, speaking to "
                  "camera with a calm, confident and natural expression, subtle head and lip motion.")


def fit_resolution(src_w: int, src_h: int, area_budget: int = DEFAULT_AREA):
    """Pick a /16-aligned resolution matching the source aspect ratio.

    Sequence length is (w/16) * (h/16) * frames, so pinning w*h to a fixed
    budget keeps runtime predictable whether the source is a tall portrait or a
    wide landscape.
    """
    w16, h16 = src_w / GRID, src_h / GRID
    if w16 < 1 or h16 < 1:
        raise ValueError(f"image too small: {src_w}x{src_h}")
    scale = math.sqrt(area_budget / (src_w * src_h))
    out_w = max(8, round(w16 * scale)) * GRID
    out_h = max(8, round(h16 * scale)) * GRID
    return min(out_w, 1280), min(out_h, 1280)


def image_size(path: Path):
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def free_ram_gb() -> float:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        def __init__(self):
            self.dwLength = ctypes.sizeof(self)
            super().__init__()

    st = MEMORYSTATUSEX()
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return st.ullAvailPhys / 1e9


# --------------------------------------------------------------------------- #
# UI workflow -> API prompt
# --------------------------------------------------------------------------- #
def _is_widget(spec) -> bool:
    if not isinstance(spec, list) or not spec:
        return False
    head = spec[0]
    if isinstance(head, list):
        return True
    return isinstance(head, str) and head in WIDGET_TYPES


def _matches(value, spec) -> bool:
    head = spec[0]
    if isinstance(head, list):
        return isinstance(value, str) and value in head
    if head == "BOOLEAN":
        return isinstance(value, bool)
    if head == "INT":
        return isinstance(value, int) and not isinstance(value, bool)
    if head == "FLOAT":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if head in ("STRING", "COMBO"):
        return isinstance(value, str)
    return True


def build_prompt(wf: dict, object_info: dict, widgets: dict) -> dict:
    """Translate the UI-format workflow into an API prompt.

    Widget values map onto inputs positionally because ComfyUI's saved JSON does
    not record input names. Extra widgets such as control_after_generate are
    skipped by type-checking each value against the declared input spec.
    """
    link_by_id = {lk[0]: lk for lk in wf.get("links", [])}
    prompt: dict = {}

    for node in wf["nodes"]:
        nid = str(node["id"])
        ctype = node["type"]
        if ctype not in object_info:
            raise KeyError(f"node type not available in ComfyUI: {ctype}")
        spec = object_info[ctype]["input"]

        names, specs = [], []
        for section in ("required", "optional"):
            for name, s in spec.get(section, {}).items():
                if _is_widget(s):
                    names.append(name)
                    specs.append(s)

        wv = widgets.get(nid, node.get("widgets_values"))
        inputs: dict = {}
        if isinstance(wv, dict):
            for name in names:
                if name in wv and not isinstance(wv[name], dict):
                    inputs[name] = wv[name]
        elif isinstance(wv, list):
            vi = 0
            for name, wspec in zip(names, specs):
                if vi >= len(wv):
                    break
                if _matches(wv[vi], wspec):
                    inputs[name] = wv[vi]
                    vi += 1
                elif vi + 1 < len(wv) and _matches(wv[vi + 1], wspec):
                    vi += 1
                    inputs[name] = wv[vi]
                    vi += 1
                else:
                    inputs[name] = wv[vi]
                    vi += 1

        for inp in node.get("inputs") or []:
            if not isinstance(inp, dict):
                continue
            lk = link_by_id.get(inp.get("link"))
            if lk:
                inputs[inp["name"]] = [str(lk[1]), lk[2]]

        prompt[nid] = {"class_type": ctype, "inputs": inputs}

    # Execution order matters on a 32 GB box. ComfyUI walks the graph depth
    # first and pops a LIFO stack, so the *last* entry of each inputs dict gets
    # discovered first. Hiding the heavy model chain behind text_embeds and the
    # audio branch behind images makes the loaders run while RAM is still free.
    def move_last(inputs: dict, keys: list) -> None:
        for k in keys:
            if k in inputs:
                inputs[k] = inputs.pop(k)

    move_last(prompt.get("131", {}).get("inputs", {}), ["images"])
    move_last(prompt.get("128", {}).get("inputs", {}), ["model", "text_embeds"])
    return prompt


# --------------------------------------------------------------------------- #
# install check
# --------------------------------------------------------------------------- #
def check() -> int:
    ok = True

    wf = COMFY_ROOT / WF_REL
    if wf.exists():
        print(f"[OK] workflow  {wf}")
    else:
        print(f"[ERR] workflow missing: {wf}")
        ok = False

    models = COMFY_ROOT / "models"
    for rel in ("diffusion_models/Wan2_1-I2V-14B-480P_fp8_e5m2.safetensors",
                "diffusion_models/infinite_talk.safetensors",
                "vae/Wan2_1_VAE_fp32.safetensors",
                "clip_vision/clip_vision_h.safetensors"):
        if (models / rel).exists():
            print(f"[OK] model     {rel}")
        else:
            print(f"[ERR] model missing: {rel}")
            ok = False

    m = whisper_dir("medium")
    if m.complete:
        print(f"[OK] whisper   medium -> {m.dir}")
    else:
        print(f"[WARN] whisper medium incomplete ({m.dir})")
        print("       fetch with: python scripts/whisper_srt.py --download medium")

    if comfy_running():
        print(f"[OK] comfyui   up at {COMFY_URL}")
    else:
        print(f"[WARN] comfyui not reachable at {COMFY_URL}")
        print(f"       start: {COMFY_ROOT}\\.venv\\Scripts\\python.exe main.py --disable-async-offload --disable-cuda-malloc")

    try:
        import faster_whisper  # noqa: F401
        print("[OK] faster-whisper importable")
    except ImportError:
        print("[ERR] faster-whisper is not installed in this interpreter")
        ok = False

    ram = free_ram_gb()
    note = "  <-- below the 15 GB a generation run needs" if ram < 15 else ""
    print(f"[--] free RAM   {ram:.1f} GB{note}")
    print("[OK] ready" if ok else "[ERR] fix the items above first")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an InfiniteTalk avatar video")
    ap.add_argument("--image", help="source portrait, jpg/png/webp")
    ap.add_argument("--audio", help="driving speech, wav/mp3/m4a")
    ap.add_argument("--prompt", default=None, help="positive prompt override")
    ap.add_argument("--area", type=int, default=DEFAULT_AREA,
                    help="pixel budget; lower is faster (default %(default)s)")
    ap.add_argument("--fit", default="pillarbox_blur",
                    choices=["pillarbox_blur", "pad", "pad_edge", "crop", "resize"],
                    help="how a differently-proportioned image is fitted")
    ap.add_argument("--output", default=None, help="where to place the final mp4")
    ap.add_argument("--timeout", type=int, default=0,
                    help="give up waiting after N seconds (0 = wait forever)")
    ap.add_argument("--poll", type=int, default=15, help="poll interval, seconds")
    ap.add_argument("--no-start", action="store_true",
                    help="do not launch ComfyUI automatically")
    ap.add_argument("--check", action="store_true", help="verify the install and exit")
    args = ap.parse_args()

    if args.check:
        return check()
    if not args.image or not args.audio:
        ap.error("--image and --audio are required")

    def resolve(raw: str) -> Path:
        p = Path(raw)
        if p.exists():
            return p
        alt = COMFY_INPUT / p.name
        if alt.exists():
            return alt
        print(f"[ERR] not found: {p}")
        raise SystemExit(1)

    src_img = resolve(args.image)
    src_aud = resolve(args.audio)

    # stage into ComfyUI/input so the workflow can reference assets by name
    for p in (src_img, src_aud):
        dst = COMFY_INPUT / p.name
        if p.resolve() != dst.resolve():
            shutil.copyfile(p, dst)

    src_w, src_h = image_size(src_img)
    out_w, out_h = fit_resolution(src_w, src_h, args.area)
    seq = (out_w // GRID) * (out_h // GRID) * 21
    print(f"[ok] image   {src_img.name} {src_w}x{src_h} (ratio {src_w / src_h:.3f})")
    print(f"[ok] output  {out_w}x{out_h} (ratio {out_w / out_h:.3f}, fit={args.fit})")
    print(f"[ok] seq     {seq}   ~{seq / 20160 * 3.5:.1f} min per 10s clip")

    if not args.no_start and not comfy_running():
        print("[..] starting ComfyUI")
        start_comfy()
        for _ in range(40):
            if comfy_running():
                break
            time.sleep(3)
        else:
            print(f"[ERR] ComfyUI did not come up at {COMFY_URL}")
            return 1

    with urllib.request.urlopen(f"{COMFY_URL}/object_info", timeout=60) as r:
        object_info = json.loads(r.read().decode())
    with open(COMFY_ROOT / WF_REL, encoding="utf-8") as f:
        wf = json.load(f)

    widgets = {str(n["id"]): n.get("widgets_values") for n in wf["nodes"]}
    widgets[NODE_IMAGE][0] = src_img.name
    widgets[NODE_AUDIO][0] = src_aud.name
    widgets[NODE_RESIZE][0] = out_w
    widgets[NODE_RESIZE][1] = out_h
    widgets[NODE_RESIZE][3] = args.fit
    widgets[NODE_ENCODE][0] = out_w
    widgets[NODE_ENCODE][1] = out_h

    prompt = build_prompt(wf, object_info, widgets)
    if args.prompt:
        prompt["135"]["inputs"]["positive_prompt"] = args.prompt
    print(f"[ok] prompt  {(args.prompt or DEFAULT_PROMPT)[:64]}")

    pid = post_json_with_retry(COMFY_URL, {"prompt": prompt})["prompt_id"]
    print(f"[ok] queued  prompt_id={pid}, this takes a while")

    deadline = time.time() + args.timeout if args.timeout else None
    hist = {}
    while True:
        time.sleep(args.poll)
        try:
            hist = history(COMFY_URL, pid)
            if pid in hist:
                break
        except Exception:
            pass
        if deadline and time.time() > deadline:
            print("[ERR] timed out waiting for ComfyUI")
            return 1

    entry = hist[pid]
    if entry.get("status", {}).get("status_str") == "error":
        for msg in entry.get("status", {}).get("messages", []):
            if msg and msg[0] == "execution_error":
                print(f"[ERR] {msg[1].get('exception_message', 'execution failed')}")
        return 1

    produced = []
    for node_out in entry.get("outputs", {}).values():
        for item in node_out.get("gifs", []) or node_out.get("videos", []) or []:
            fp = Path(item["fullpath"])
            if fp.exists():
                produced.append(fp)
    if not produced:
        print("[ERR] run finished but no video file was reported")
        return 1

    # prefer the muxed audio track when ComfyUI produced both variants
    source = next((p for p in produced if p.stem.endswith("-audio")), produced[0])
    if args.output:
        dest = Path(args.output)
    else:
        dest = OUT_DIR / source.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dest.resolve():
        shutil.copyfile(source, dest)
    print(f"[OK] video    {dest}  ({dest.stat().st_size / 1048576:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
