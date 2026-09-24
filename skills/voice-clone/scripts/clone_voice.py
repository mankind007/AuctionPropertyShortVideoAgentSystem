"""
Qwen3-TTS 声音克隆：参考音频 + 目标文本 -> 克隆音色 wav / 房源 data.voice。

Studio 模式（任意文本）:
    .venv\\Scripts\\python.exe skills\\voice-clone\\scripts\\clone_voice.py ^
        --ref-audio assets\\汲总.mp3 ^
        --ref-text "还没签，正在审他的合同和谈条件呢啊" ^
        --text "这里是深圳市特资投资集团公司。" ^
        --output assets\\voice_clone\\out.wav

房源模式（与 voice-tts 同一 data.voice 结构, 写 DB）:
    ... --source gpai --item-id 52946
    ... --source gpai --all --limit 50 --force

Modes:
    (default)            精确克隆: 需 --ref-text 与参考音频对齐, 质量最好
    --x-vector-only      懒人模式: 仅参考音频, 不写 ref_text, 质量略降

Optional:
    --check              只体检模型/依赖, 不推理
    --force              输出已存在时强制重跑 / 房源强制重做
    --device auto|cpu|cuda:0
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "models" / "tts" / "Qwen3-TTS-12Hz-0.6B-Base"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "assets" / "voice_clone"
DEFAULT_REF_AUDIO = REPO_ROOT / "assets" / "汲总.mp3"
DEFAULT_REF_TEXT = "还没签，正在审他的合同和谈条件呢啊"


def missing_weights() -> list[str]:
    problems: list[str] = []
    if not MODEL_DIR.is_dir():
        problems.append(f"模型目录不存在: {MODEL_DIR}")
        return problems
    for name in ("config.json",):
        if not (MODEL_DIR / name).is_file():
            problems.append(f"缺少 {MODEL_DIR / name}")
    weight_globs = list(MODEL_DIR.glob("*.safetensors")) + list(
        MODEL_DIR.glob("*.bin")
    )
    if not weight_globs:
        problems.append(f"未找到任何权重文件 (*.safetensors/*.bin) in {MODEL_DIR}")
    return problems


def do_check() -> int:
    problems = missing_weights()
    if problems:
        print("ERROR: 模型不完整:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\n提示: 权重应在 models/tts/Qwen3-TTS-12Hz-0.6B-Base "
            "(hf-mirror.com 下载, 不入 git)。",
            file=sys.stderr,
        )
        return 1
    print(f"[OK] 模型目录: {MODEL_DIR}")

    try:
        import qwen_tts  # noqa: F401
        print("[OK] qwen_tts 可导入")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] qwen_tts 导入失败: {exc}", file=sys.stderr)
        print(
            "  安装: .venv\\Scripts\\python.exe -m pip install qwen-tts",
            file=sys.stderr,
        )
        return 1

    try:
        import soundfile  # noqa: F401
        import torch
        print(f"[OK] torch={torch.__version__} cuda={torch.cuda.is_available()}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] torch/soundfile: {exc}", file=sys.stderr)
        return 1

    print("[OK] 环境体检通过")
    return 0


def _parse_script(full_script: str) -> list[tuple[str, str]]:
    """解析 data.script → [(角度, 文案)] 保持顺序（与 voice-tts 一致）。"""
    out: list[tuple[str, str]] = []
    if not full_script:
        return out
    for m in re.finditer(r"【(.+?)】([^【]*)", full_script):
        angle, text = m.group(1).strip(), m.group(2).strip()
        if angle and text:
            out.append((angle, text))
    return out


def _mp3_duration(path: Path) -> float:
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


def _load_model(device: str | None = None):
    import torch

    if not device or device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    from qwen_tts import Qwen3TTSModel

    print(f"Device: {device}, dtype: {dtype}")
    print(f"正在加载模型: {MODEL_DIR}")
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL_DIR),
        device_map=device,
        dtype=dtype,
        attn_implementation="eager",
    )
    return model


def _clone_to_wav(
    model,
    text: str,
    ref_audio: Path,
    ref_text: str | None,
    out: Path,
    *,
    x_vector_only: bool = False,
    language: str = "Chinese",
) -> bool:
    import soundfile as sf

    kwargs = {
        "text": text,
        "language": language,
        "ref_audio": str(ref_audio),
    }
    if x_vector_only or not ref_text:
        kwargs["x_vector_only_mode"] = True
    else:
        kwargs["ref_text"] = ref_text
    wavs, sr = model.generate_voice_clone(**kwargs)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), wavs[0], sr)
    return out.is_file() and out.stat().st_size > 0


def run_listing(
    source: str,
    item_id: str,
    *,
    ref_audio: Path | None = None,
    ref_text: str | None = None,
    x_vector_only: bool = False,
    force: bool = False,
    device: str = "auto",
    language: str = "Chinese",
) -> dict:
    """房源模式：读 data.script → 逐角度克隆 → 写 data.voice（结构与 voice-tts 一致）。"""
    sys.path.insert(0, str(REPO_ROOT))
    from db import get_source_data, upsert_listing

    entry = get_source_data(source).get(item_id, {})
    data = entry.get("data") or {}
    script = data.get("script", "")
    angles = _parse_script(script)
    if not angles:
        print(f"[SKIP] {source}/{item_id}: no data.script(先跑 script-writer)")
        return {}

    ref_audio = Path(ref_audio) if ref_audio else DEFAULT_REF_AUDIO
    if not ref_audio.is_file():
        print(f"ERROR: 参考音频不存在: {ref_audio}", file=sys.stderr)
        return {}
    if not x_vector_only and not ref_text:
        ref_text = DEFAULT_REF_TEXT if ref_audio == DEFAULT_REF_AUDIO else None
        if not ref_text:
            print(
                "ERROR: 房源克隆需要 --ref-text 或 --x-vector-only",
                file=sys.stderr,
            )
            return {}

    voice_dir = REPO_ROOT / "assets" / source / item_id / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    prev = {}
    if not force:
        prev = {v["angle"]: v for v in (data.get("voice") or {}).get("files", [])}

    problems = missing_weights()
    if problems:
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return {}

    try:
        model = _load_model(device)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"ERROR: 模型加载失败: {exc}", file=sys.stderr)
        return {}

    files: list[dict] = []
    for i, (angle, text) in enumerate(angles, 1):
        name = f"{i:02d}_{angle}.mp3"
        out = voice_dir / name
        old = prev.get(angle)
        if (
            old
            and (voice_dir / old.get("file", "")).exists()
            and (voice_dir / old["file"]).stat().st_size > 0
            and float(old.get("duration") or 0) > 0
        ):
            files.append(old)
            print(f"  = {old['file']} ({old['duration']}s, 已有跳过)")
            continue
        try:
            ok = _clone_to_wav(
                model, text, ref_audio, ref_text, out,
                x_vector_only=x_vector_only, language=language,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {angle}: {exc}", file=sys.stderr)
            ok = False
        if not ok:
            continue
        # qwen 输出 wav; voice-tts 是 mp3。mux 侧按扩展名读, 统一保留 wav 文件名
        files.append({
            "angle": angle,
            "file": out.name,
            "duration": round(_mp3_duration(out), 2),
        })
        print(f"  → {out.name} ({files[-1]['duration']}s)")

    old_voice = data.get("voice") or {}
    combined = ""
    if (
        not force
        and old_voice.get("combined")
        and (voice_dir / old_voice["combined"]).exists()
    ):
        combined = old_voice["combined"]
        print(f"  = {combined} (整篇已有跳过)")
    else:
        # 整篇：拼接正文后克隆一次
        full_text = "。".join(t for _, t in angles)
        cname = f"{item_id}_full.wav"
        try:
            if _clone_to_wav(
                model, full_text, ref_audio, ref_text, voice_dir / cname,
                x_vector_only=x_vector_only, language=language,
            ):
                combined = cname
                print(f"  → {cname} (整篇)")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] full: {exc}", file=sys.stderr)

    voice_out = {"files": files, "combined": combined, "backend": "clone"}
    new_data = dict(data)
    new_data["voice"] = voice_out
    ok = upsert_listing({"source": source, "item_id": item_id, "data": new_data})
    print(f"[DB {'OK' if ok else 'FAIL'}] voice({len(files)}条) → {source}/{item_id}")
    return voice_out


def run_all_listing(
    source: str = "gpai",
    limit: int = 5,
    force: bool = False,
    **kwargs,
) -> None:
    sys.path.insert(0, str(REPO_ROOT))
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
        need = len(_parse_script(data["script"]))
        if not force and v and len(v.get("files", [])) >= need:
            skipped += 1
            continue
        print(f"\n=== {source}/{item_id} ===")
        if run_listing(source, item_id, force=force, **kwargs):
            done += 1
        else:
            skipped += 1
    print(f"\n[DONE] generated={done} skipped(already done)={skipped}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qwen3-TTS voice clone: studio wav or listing data.voice."
    )
    # studio
    parser.add_argument("--ref-audio", type=Path, default=None,
                        help="参考音频(wav/mp3/m4a)。")
    parser.add_argument("--ref-text", type=str, default=None,
                        help="参考音频对应文本(精确克隆)。")
    parser.add_argument("--text", type=str, default=None, help="目标文本。")
    parser.add_argument("--language", type=str, default="Chinese")
    parser.add_argument("--output", type=Path, default=None,
                        help="studio 输出 wav。")
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")
    # listing
    parser.add_argument("--source", type=str, default=None,
                        help="房源 source(房源模式)。")
    parser.add_argument("--item-id", type=str, default=None,
                        help="单套房源 ID(房源模式)。")
    parser.add_argument("--all", action="store_true",
                        help="房源批量(已有 voice 则跳过)。")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    if args.check:
        return do_check()

    listing_mode = bool(args.source and (args.item_id or args.all))
    if listing_mode:
        if args.item_id:
            voice = run_listing(
                args.source,
                args.item_id,
                ref_audio=args.ref_audio,
                ref_text=args.ref_text,
                x_vector_only=args.x_vector_only,
                force=args.force,
                device=args.device,
                language=args.language,
            )
            return 0 if voice else 1
        if args.all:
            run_all_listing(
                args.source,
                limit=args.limit,
                force=args.force,
                ref_audio=args.ref_audio,
                ref_text=args.ref_text,
                x_vector_only=args.x_vector_only,
                device=args.device,
                language=args.language,
            )
            return 0
        parser.error("房源模式需要 --item-id 或 --all")

    # studio 模式
    problems = missing_weights()
    if problems:
        print("ERROR: 模型不完整:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    if not args.ref_audio:
        if args.x_vector_only:
            args.ref_audio = DEFAULT_REF_AUDIO
        else:
            print("ERROR: 需要 --ref-audio", file=sys.stderr)
            return 1
    args.ref_audio = Path(os.path.abspath(args.ref_audio))
    if not args.ref_audio.is_file():
        print(f"ERROR: 参考音频不存在: {args.ref_audio}", file=sys.stderr)
        return 1

    if not args.x_vector_only and not args.ref_text:
        if args.ref_audio == DEFAULT_REF_AUDIO:
            args.ref_text = DEFAULT_REF_TEXT
        else:
            print(
                "ERROR: 精确克隆需要 --ref-text; 或改用 --x-vector-only",
                file=sys.stderr,
            )
            return 1

    if not args.text or not args.text.strip():
        print("ERROR: 需要非空 --text", file=sys.stderr)
        return 1

    out = args.output or (DEFAULT_OUTPUT_DIR / f"{args.ref_audio.stem}.wav")
    out = Path(os.path.abspath(out))
    if not args.force and out.is_file() and out.stat().st_size >= 1024:
        print(f"[OK] 输出已存在, 跳过: {out}")
        print("  需要重跑请加 --force")
        return 0

    print(f"参考音频: {args.ref_audio}")
    print(f"目标文本: {args.text}")
    print("阶段: 加载声音克隆模型")
    print("progress: 10% | 加载模型")
    try:
        model = _load_model(args.device)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"ERROR: 模型加载失败: {exc}", file=sys.stderr)
        return 1
    print("阶段: 语音克隆生成")
    print("progress: 50% | 模型加载完成, 开始克隆生成")

    try:
        ok = _clone_to_wav(
            model, args.text, args.ref_audio, args.ref_text, out,
            x_vector_only=args.x_vector_only, language=args.language,
        )
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"ERROR: 克隆生成失败: {exc}", file=sys.stderr)
        return 1
    print("阶段: 写入音频文件")
    print("progress: 95% | 克隆完成, 写入文件")
    if not ok:
        return 1
    print(f"[OK] 完成: {out}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    sys.exit(main())
