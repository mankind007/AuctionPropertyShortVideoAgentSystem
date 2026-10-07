"""
口型对齐：静态人物图 + 音频 -> 人物讲话视频。双 backend:
  --backend musetalk (默认)  MuseTalk V1.5, 全图融合, 保留原图构图
  --backend imtalker         IMTalker, 单图+音频直接生成 512x512 说话头口播

Run from repo root:
    .venv\\Scripts\\python.exe skills\\lip-sync\\scripts\\lipsync.py --image assets\\man1.jpg --audio assets\\me.mp3

Optional:
    --check                 只做环境/权重体检, 不跑推理
    --force                 输出已存在时强制重跑
    --backend musetalk|imtalker  选择后端(默认 musetalk)
    --max-seconds 8         限制输入音频时长(生成前后各重采样到临时文件), 0 表示不限
    --fps 25 --batch-size 2 --no-fp16   MuseTalk 显存/画质参数(6GB 卡默认 fp16 + batch=2)
    --a-cfg-scale 2 --nfe 10            IMTalker 采样参数
    --device auto|cuda:0|cpu

完整方法与踩坑记录见 skills/lip-sync/references/部署与调参.md。
"""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

# torch>=2.6 把 torch.load 默认 weights_only 改为 True, 而 DWPose/BiSeNet 这些
# 第三方 checkpoint 里含 numpy 对象, 会被 WeightsUnpickler 拒绝。
# 权重来源已知可信, 用官方逃生开关恢复旧行为(在 torch.load 调用时读取, 不需先于 import)。
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# 本文件位于 skills/lip-sync/scripts/lipsync.py -> parents[3] = 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
LIPSYNC_DIR = REPO_ROOT / "models" / "lip-sync"
# 代码仓与权重分离: 官方代码在技能 vendor/, 权重在 models/lip-sync/
MUSETALK_DIR = REPO_ROOT / "skills" / "lip-sync" / "vendor" / "MuseTalk"
UNET_DIR = LIPSYNC_DIR / "musetalkV15"
UNet_CONFIG = UNET_DIR / "musetalk.json"
UNet_WEIGHTS = UNET_DIR / "unet.pth"
VAE_DIR = LIPSYNC_DIR / "sd-vae"
WHISPER_DIR = LIPSYNC_DIR / "whisper"
DWPOSE_DIR = LIPSYNC_DIR / "dwpose"
FACE_PARSE_DIR = LIPSYNC_DIR / "face-parse-bisent"
S3FD_WEIGHTS = (
    MUSETALK_DIR
    / "musetalk"
    / "utils"
    / "face_detection"
    / "detection"
    / "sfd"
    / "s3fd.pth"
)
DEFAULT_IMAGE = REPO_ROOT / "assets" / "man1.jpg"
DEFAULT_AUDIO = REPO_ROOT / "assets" / "me.mp3"
OUTPUT_DIR = REPO_ROOT / "assets" / "lip_sync"

# IMTalker: 代码在 vendor/, 权重在 models/lip-sync/IMTalker/, vendor/checkpoints 为目录联接
IMTALKER_DIR = REPO_ROOT / "skills" / "lip-sync" / "vendor" / "IMTalker"
IMTALKER_CKPT_LINK = IMTALKER_DIR / "checkpoints"
IMTALKER_WEIGHTS_DIR = LIPSYNC_DIR / "IMTalker"
IMTALKER_GENERATOR = IMTALKER_WEIGHTS_DIR / "generator.ckpt"
IMTALKER_RENDERER = IMTALKER_WEIGHTS_DIR / "renderer.ckpt"
IMTALKER_WAV2VEC = IMTALKER_WEIGHTS_DIR / "wav2vec2-base-960h"
# face_alignment 的 2DFAN4/s3fd 权重走 torch hub 缓存(公网 adrianbulat.com 慢/gh-proxy 404)
TORCH_HUB_DIR = Path(
    os.environ.get("TORCH_HOME") or (Path.home() / ".cache" / "torch")
) / "hub"
TORCH_HUB_CKPT = TORCH_HUB_DIR / "checkpoints"
FAN4_WEIGHTS = TORCH_HUB_CKPT / "2DFAN4-11f355bf06.pth.tar"
S3FD_HUB_WEIGHTS = TORCH_HUB_CKPT / "s3fd-619a316812.pth"

# 权重缺失时给出的下载命令(hf-mirror 为本机唯一可达源)
DOWNLOAD_HINT = r"""
$env:HF_ENDPOINT = "https://hf-mirror.com"
$hf   = ".venv\Scripts\hf.exe"
$base = "$PWD\models\lip-sync"

& $hf download stabilityai/sd-vae-ft-mse --local-dir "$base\sd-vae" `
    --include "config.json" "diffusion_pytorch_model.bin"
& $hf download openai/whisper-tiny --local-dir "$base\whisper" `
    --include "config.json" "pytorch_model.bin" "preprocessor_config.json"
& $hf download yzd-v/DWPose --local-dir "$base\dwpose" `
    --include "dw-ll_ucoco_384.pth"
& $hf download ManyOtherFunctions/face-parse-bisent --local-dir "$base\face-parse-bisent" `
    --include "79999_iter.pth" "resnet18-5c106cde.pth"

# s3fd: adrianbulat 官方源极慢, 走 hf-mirror
$tmp = "$env:TEMP\s3fd"
& $hf download n0x1103/s3fd --local-dir $tmp --include "s3fd-619a316812.pth"
Copy-Item "$tmp\s3fd-619a316812.pth" `
  "$PWD\skills\lip-sync\vendor\MuseTalk\musetalk\utils\face_detection\detection\sfd\s3fd.pth" -Force
"""


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
def required_weights() -> list[tuple[Path, int | None]]:
    """(路径, 期望字节数 or None)。字节数非 None 时用于发现截断下载。"""
    return [
        (UNet_WEIGHTS, None),
        (UNet_CONFIG, None),
        (VAE_DIR / "config.json", None),
        (VAE_DIR / "diffusion_pytorch_model.bin", None),
        (WHISPER_DIR / "config.json", None),
        (WHISPER_DIR / "preprocessor_config.json", None),
        (WHISPER_DIR / "pytorch_model.bin", None),
        (DWPOSE_DIR / "dw-ll_ucoco_384.pth", None),
        (FACE_PARSE_DIR / "79999_iter.pth", None),
        (FACE_PARSE_DIR / "resnet18-5c106cde.pth", None),
        # 89843225 = 官方原始字节数; 小于它说明被中断/截断
        (S3FD_WEIGHTS, 89843225),
    ]


def missing_weights() -> list[str]:
    problems: list[str] = []
    if not MUSETALK_DIR.is_dir():
        problems.append(
            f"缺少代码仓 {MUSETALK_DIR}\n"
            "  git clone --depth 1 https://gh-proxy.com/https://github.com/TMElyralab/MuseTalk.git"
            f' "{MUSETALK_DIR}"'
        )
    for path, expected in required_weights():
        if not path.is_file():
            problems.append(f"缺失: {path}")
            continue
        if expected is not None and path.stat().st_size < expected:
            problems.append(
                f"截断: {path} ({path.stat().st_size} < {expected} 字节)"
            )
    return problems


# 官方原始字节数, 小于它说明被中断/截断
IMTALKER_GENERATOR_BYTES = 621318134
IMTALKER_RENDERER_BYTES = 2121068003
FAN4_BYTES = 95641761
S3FD_HUB_BYTES = 89843225


def required_weights_imtalker() -> list[tuple[Path, int | None]]:
    return [
        (IMTALKER_GENERATOR, IMTALKER_GENERATOR_BYTES),
        (IMTALKER_RENDERER, IMTALKER_RENDERER_BYTES),
        (IMTALKER_WAV2VEC / "config.json", None),
        (IMTALKER_WAV2VEC / "pytorch_model.bin", None),
        (FAN4_WEIGHTS, FAN4_BYTES),
        (S3FD_HUB_WEIGHTS, S3FD_HUB_BYTES),
    ]


IMTALKER_DOWNLOAD_HINT = r"""
$env:HF_ENDPOINT = "https://hf-mirror.com"
$hf   = ".venv\Scripts\hf.exe"
$base = "$PWD\models\lip-sync\IMTalker"

# 代码仓(已含 generator/renderer 训练权重发布页)
git clone --depth 1 https://gh-proxy.com/https://github.com/bigai-nlco/IMTalker.git `
  "skills\lip-sync\vendor\IMTalker"

# 模型权重
& $hf download cbsjtu01/IMTalker --local-dir $base `
    --include "generator.ckpt" "renderer.ckpt"
& $hf download facebook/wav2vec2-base-960h --local-dir "$base\wav2vec2-base-960h" `
    --include "config.json" "preprocessor_config.json" "pytorch_model.bin"

# face_alignment 2DFAN4: 官方源(gh-proxy 对 release 资产 404, 只能直连)
$tmp = "$env:TEMP\2DFAN4_official.pth.tar"
curl.exe -L -o $tmp "https://www.adrianbulat.com/downloads/python-fan/2DFAN4-11f355bf06.pth.tar"
# 校验: sha256 必须以 11f355bf06 开头, 否则重下
New-Item -ItemType Directory -Force "$PWD\.fa_hub\checkpoints" | Out-Null
Copy-Item $tmp "$env:USERPROFILE\.cache\torch\hub\checkpoints\2DFAN4-11f355bf06.pth.tar" -Force

# s3fd(与 MuseTalk 同一个)
& $hf download n0x1103/s3fd --local-dir "$env:TEMP\s3fd" --include "s3fd-619a316812.pth"
Copy-Item "$env:TEMP\s3fd\s3fd-619a316812.pth" `
  "$env:USERPROFILE\.cache\torch\hub\checkpoints\s3fd-619a316812.pth" -Force
"""


def missing_weights_imtalker() -> list[str]:
    problems: list[str] = []
    if not IMTALKER_DIR.is_dir():
        problems.append(
            f"缺少代码仓 {IMTALKER_DIR}\n"
            "  git clone --depth 1 https://gh-proxy.com/https://github.com/bigai-nlco/IMTalker.git"
            f' "{IMTALKER_DIR}"'
        )
    for path, expected in required_weights_imtalker():
        if not path.is_file():
            problems.append(f"缺失: {path}")
            continue
        if expected is not None and path.stat().st_size < expected:
            problems.append(
                f"截断: {path} ({path.stat().st_size} < {expected} 字节)"
            )
    return problems


def ensure_junction_imtalker() -> bool:
    """vendor/IMTalker/checkpoints -> models/lip-sync/IMTalker。"""
    link = IMTALKER_CKPT_LINK
    if link.exists():
        return False
    link.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(IMTALKER_WEIGHTS_DIR)],
        capture_output=True,
        text=True,
        encoding="gbk",errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"创建目录联接失败: {link} -> {IMTALKER_WEIGHTS_DIR}\n{(r.stderr or r.stdout).strip()}"
        )
    return True


def ensure_junction() -> bool:
    """官方代码按 cwd=MuseTalk 解析 ./models/..., 用目录联接指回 models/lip-sync。"""
    link = MUSETALK_DIR / "models"
    if link.exists():
        return False
    link.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(LIPSYNC_DIR)],
        capture_output=True,
        text=True,
        encoding="gbk", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"创建目录联接失败: {link} -> {LIPSYNC_DIR}\n{(r.stderr or r.stdout).strip()}"
        )
    return True


def ffmpeg_exe() -> str:
    """项目内 ffmpeg 统一来源: imageio-ffmpeg 捆绑二进制(不一定在 PATH)。"""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"[FATAL] 找不到 ffmpeg(imageio-ffmpeg 未安装): {exc}"
        )


def enter_musetalk_pkg() -> None:
    """cwd 必须是 MuseTalk 仓根, 并把仓根加到 sys.path。"""
    os.chdir(MUSETALK_DIR)
    if str(MUSETALK_DIR) not in sys.path:
        sys.path.insert(0, str(MUSETALK_DIR))


def load_mmpose_stack():
    """
    导入 mmpose/mmdet。

    mmdet 3.3.0 的版本守卫是 `mmcv >= 2.0.0rc4 and mmcv < 2.2.0`, 而本项目
    用的是 MiroPsota 构建的 mmcv 2.2.0+pt2.6.0cu126, 正好卡死一位。
    mmcv 2.2.0 对 2.1.0 向后兼容, 因此 import 前临时压低版本号通过守卫
    (只影响守卫读到的值, 不改 site-packages, 重装 mmdet 后依然有效)。
    """
    import mmcv

    mmcv.__version__ = "2.1.0"
    from mmpose.apis import inference_topdown, init_model
    from mmpose.structures import merge_data_samples

    return inference_topdown, init_model, merge_data_samples


def free_ram_mb() -> int:
    """当前可用物理内存(MB)。用于在 native 崩溃前给出可读的错误。"""
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return int(stat.ullAvailPhys // (1024 * 1024))


def load_unet_cpu(unet_config: str, unet_weight: str, use_fp16: bool = True):
    """
    低内存加载 MuseTalk UNet(849.9M 参数)。

    坑叠在本机(6GB 显存 / 15GB 内存)上会直接把进程打死:

    1. `unet.pth` 由官方脚本在 GPU 上导出, 张量带 cuda 设备标签。不传 map_location
       时 torch 按原设备解包 -> GPU 上一次性吃 3.4GB fp32 -> `CUDA out of memory`。
    2. `UNet2DConditionModel(**cfg)` + `torch.load` 同时持有模型和 checkpoint
       = 6.8GB 峰值 -> **native 崩溃 0xC0000005**, 没有任何 Python traceback。
    3. 用字典推导式做 fp16 转换时, 新旧两份 dict 短暂并存
       = 3.4GB(fp32) + 1.7GB(fp16) = **5.1GB 峰值**。
       机器空闲内存 7GB 时能过、3.7GB 时必崩 -> 表现为"时好时坏"。
    4. torch>=2.6 默认 `weights_only=True`(由模块顶部环境变量覆盖)。

    方案: `mmap` 读(不占常驻内存) -> **逐条**转 fp16 并立刻丢弃原引用(峰值 ~2GB)
    -> 在 `meta` 设备上建空模型 -> `load_state_dict(assign=True)` 直接挂成参数。
    注意 `diffusers` 必须在 meta 上下文**之外** import, 否则 import 期的张量运算
    会报 `Tensor.item() cannot be called on meta tensors`。
    """
    import json

    import torch
    from diffusers import UNet2DConditionModel  # noqa: E402  必须在 meta 之外

    need_mb = 2500 if use_fp16 else 4500
    free_mb = free_ram_mb()
    if free_mb < need_mb:
        raise RuntimeError(
            f"可用物理内存仅 {free_mb}MB, 加载 UNet 需要约 {need_mb}MB 峰值。\n"
            "  内存不足会表现为 native 崩溃 0xC0000005(无 Python traceback), "
            "详见 skills/lip-sync/references/部署与调参.md §7.5。\n"
            "  请关闭浏览器/其他大内存程序后重试。"
        )
    print(f"[mem] 可用物理内存 {free_mb}MB (阈值 {need_mb}MB)")

    with open(unet_config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    raw = torch.load(unet_weight, map_location="cpu", mmap=True)
    # 必须逐条转换并立刻丢弃原引用。字典推导式会让新旧两份同时存活, 峰值翻倍。
    weights: dict = {}
    for key in list(raw):
        value = raw.pop(key)          # 先从源 dict 摘除
        if use_fp16 and value.is_floating_point():
            weights[key] = value.to(torch.float16)
        elif value.is_floating_point():
            weights[key] = value.clone()   # 解除对 mmap 页的引用
        else:
            weights[key] = value
        del value                      # 释放本条 fp32/mmap 引用
    del raw

    with torch.device("meta"):
        model = UNet2DConditionModel(**cfg)
    model.load_state_dict(weights, assign=True, strict=True)
    del weights
    return model.eval()


def release_face_detectors() -> None:
    """
    关键点提完后把 DWPose + S3FD 挪回 CPU, 释放推理期显存(6GB 卡的余量很关键)。

    结构是三层: `preprocessing.fa`(FaceAlignment) -> `.face_detector`(SFDDetector)
    -> `.face_detector`(s3fd 模块)。`SFDDetector.detect()` 用 `self.device`
    决定输入张量放哪, 所以模块搬走时 device 字符串必须一起改成 "cpu",
    否则 net 在 CPU、img 在 cuda 会报设备不匹配。
    """
    import torch

    moved = False
    try:
        from musetalk.utils import preprocessing as _prep

        dwpose = getattr(_prep, "model", None)
        if dwpose is not None:
            dwpose.to("cpu")            # mmpose 会按模型设备推断推理设备
            moved = True

        sfd = getattr(getattr(_prep, "fa", None), "face_detector", None)
        if sfd is not None:
            net = getattr(sfd, "face_detector", None)
            if net is not None:
                net.to("cpu")
            if hasattr(sfd, "device"):
                sfd.device = "cpu"
            moved = True
    except Exception:  # noqa: BLE001
        pass
    if moved and torch.cuda.is_available():
        torch.cuda.empty_cache()
        print("[OK] DWPose/S3FD 已释放到 CPU")


# ---------------------------------------------------------------------------
# Audio pre-trim
# ---------------------------------------------------------------------------
def trim_audio(
    src: Path,
    max_seconds: float,
    work_dir: Path,
    tag: str = "asr",
    sample_rate: int | None = 16000,
    channels: int | None = 1,
) -> Path:
    """
    按 max_seconds 截断音频。

    需要两份不同用途的产物, 不能共用:
      - `sample_rate=16000, channels=1` 是 **Whisper 的输入格式**, 不能当音轨;
      - 音轨必须用 `sample_rate=None` 的版本, 否则成片音质被压成 16k 单声道。
    """
    if max_seconds <= 0 and sample_rate is None and channels is None:
        return src
    ext = "wav" if sample_rate or channels else src.suffix.lstrip(".") or "wav"
    dst = work_dir / f"trim_{src.stem}_{tag}.{ext}"
    ff = ffmpeg_exe()
    cmd = [ff, "-y", "-v", "error", "-i", str(src)]
    if max_seconds > 0:
        cmd += ["-t", f"{max_seconds:g}"]
    if sample_rate:
        cmd += ["-ar", str(sample_rate)]
    if channels:
        cmd += ["-ac", str(channels)]
    if ext == "wav":
        cmd += ["-c:a", "pcm_s16le"]
    cmd.append(str(dst))
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not dst.is_file():
        raise RuntimeError(f"裁剪音频失败: {(r.stderr or '').strip()}")
    return dst


# ---------------------------------------------------------------------------
# Inference (按官方 scripts/inference.py 改写: 修图片模式清理 bug + 自有输出路径)
# ---------------------------------------------------------------------------
def run_inference(
    args,
    image_path: Path,
    audio_path: Path,
    ffmpeg_path: str,
    mux_audio: Path | None = None,
) -> Path:
    import torch

    device = torch.device(args.device if args.device != "auto" else
                          (f"cuda:{args.gpu_id}" if torch.cuda.is_available() else "cpu"))
    use_fp16 = args.fp16 and device.type == "cuda"
    print(f"device={device} fp16={use_fp16} batch_size={args.batch_size}")

    # ---- 加载模型 ----
    # 顺序很重要: 先加载最重的 UNet(此时 CPU 占用最小), 上卡后 CPU 侧 1.7GB 立即归还,
    # 再加载 VAE。反过来会让两个模型的 CPU 峰值叠加。
    # 官方 musetalk.models.unet.UNet 在 cuda 可用时直接 torch.load(model_path),
    # 而 unet.pth 存的是 cuda 设备标签 -> 会把 3.4GB fp32 原样解到 GPU, 6GB 卡必 OOM。
    # 还必须排在 musetalk/mmpose/face_alignment 等重 import 之前: 那些模块 import 期
    # 就吃 ~600MB, 与 load_unet_cpu 的 2.5GB 峰值叠加会把 free_ram_mb() 压到阈值下,
    # 导致本可运行的机器误报"可用内存不足"。
    print("阶段: 加载模型 UNet/VAE/Whisper/FaceParsing")
    print("progress: 15% | 加载模型")
    unet = load_unet_cpu(
        str(UNet_CONFIG), str(UNet_WEIGHTS), use_fp16=use_fp16
    )
    unet = unet.to(device).eval()          # CPU 侧 1.7GB 在此归还

    from musetalk.models.unet import PositionalEncoding
    from musetalk.models.vae import VAE
    from musetalk.utils.audio_processor import AudioProcessor
    from musetalk.utils.blending import get_image
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.preprocessing import get_landmark_and_bbox
    from musetalk.utils.utils import datagen

    import cv2

    vae = VAE(model_path=str(VAE_DIR))     # 构造时 diffusers 会先在 GPU 放一份 fp32
    if use_fp16:
        vae.vae = vae.vae.half()           # 立刻降半, 释放 ~170MB

    pe = PositionalEncoding(d_model=384)
    if use_fp16:
        pe = pe.half()
    pe = pe.to(device)
    vae.vae = vae.vae.to(device)

    from transformers import WhisperModel

    weight_dtype = unet.dtype
    whisper = WhisperModel.from_pretrained(str(WHISPER_DIR))
    whisper = whisper.to(device=device, dtype=weight_dtype).eval()
    whisper.requires_grad_(False)

    audio_processor = AudioProcessor(feature_extractor_path=str(WHISPER_DIR))

    fp = FaceParsing(
        left_cheek_width=args.left_cheek_width,
        right_cheek_width=args.right_cheek_width,
    )

    timesteps = torch.tensor([0], device=device)

    # ---- 音频特征 ----
    print(f"Extracting audio features: {audio_path.name}")
    features, librosa_length = audio_processor.get_audio_feature(str(audio_path))
    whisper_chunks = audio_processor.get_whisper_chunk(
        features,
        device,
        weight_dtype,
        whisper,
        librosa_length,
        fps=args.fps,
        audio_padding_length_left=args.audio_padding_length_left,
        audio_padding_length_right=args.audio_padding_length_right,
    )
    num_frames = len(whisper_chunks)
    print(f"audio frames = {num_frames}")
    print("阶段: 提取人脸关键点 DWPose+S3FD")
    print("progress: 30% | 音频特征完成, 开始提关键点")

    # ---- 人脸关键点 ----
    print("Extracting landmarks (mmpose DWPose + S3FD) ...")
    coord_list, frame_list = get_landmark_and_bbox(
        [str(image_path)], args.bbox_shift
    )
    if all(c == (0.0, 0.0, 0.0, 0.0) for c in coord_list):
        raise RuntimeError(
            f"未在图片中检测到人脸: {image_path}\n"
            "  请换一张正面、人脸清晰的图片(assets/man1.jpg / man2.webp / man3.webp)"
        )
    print(f"frames={len(frame_list)} coord={coord_list}")
    release_face_detectors()
    print("阶段: VAE 编码人脸 latent")
    print("progress: 45% | 关键点完成, 开始 VAE 编码")

    # ---- VAE latent ----
    input_latent_list = []
    for bbox, frame in zip(coord_list, frame_list):
        if bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        x1, y1, x2, y2 = bbox
        y2 = min(y2 + args.extra_margin, frame.shape[0])  # 官方 v15: 加下边距
        crop_frame = frame[y1:y2, x1:x2]
        if crop_frame.size == 0:
            continue
        crop_frame = cv2.resize(
            crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4
        )
        input_latent_list.append(vae.get_latents_for_unet(crop_frame))
    if not input_latent_list:
        raise RuntimeError("人脸框为空, 无法生成")
    print("阶段: UNet 批量推理生成口型帧")
    print("progress: 55% | VAE 完成, 开始 UNet 推理")

    frame_cycle = frame_list + frame_list[::-1]
    coord_cycle = coord_list + coord_list[::-1]
    latent_cycle = input_latent_list + input_latent_list[::-1]

    # ---- 批量推理 ----
    print("Starting UNet inference ...")
    gen = datagen(
        whisper_chunks=whisper_chunks,
        vae_encode_latents=latent_cycle,
        batch_size=args.batch_size,
        delay_frame=0,
        device=device,
    )
    import math as _math
    _total_batches = max(1, _math.ceil(num_frames / args.batch_size))
    res_frames = []
    with torch.no_grad():
        for _bi, (whisper_batch, latent_batch) in enumerate(gen, 1):
            audio_feature = pe(whisper_batch)
            latent_batch = latent_batch.to(dtype=unet.dtype)
            pred = unet(
                latent_batch, timesteps, encoder_hidden_states=audio_feature
            ).sample
            res_frames.extend(vae.decode_latents(pred))
            if _bi % 3 == 0 or _bi == _total_batches:
                _pct = min(85, 55 + int(30 * min(_bi, _total_batches) / _total_batches))
                print(f"progress: {_pct}% | UNet 推理 {_bi}/{_total_batches} 批")

    # ---- 回填到原图 ----
    print("阶段: 回填人脸到原图")
    print("Pasting generated faces back ...")
    print("progress: 86% | 推理完成, 开始回填")
    out_frames = args.result_dir
    if out_frames.exists():
        shutil.rmtree(out_frames, ignore_errors=True)
    out_frames.mkdir(parents=True, exist_ok=True)

    kept = 0
    _total_paste = len(res_frames)
    for i, res_frame in enumerate(res_frames):
        bbox = coord_cycle[i % len(coord_cycle)]
        ori_frame = copy.deepcopy(frame_cycle[i % len(frame_cycle)])
        x1, y1, x2, y2 = bbox
        y2 = min(y2 + args.extra_margin, ori_frame.shape[0])
        h, w = y2 - y1, x2 - x1
        if h <= 0 or w <= 0:
            continue
        res_frame = cv2.resize(
            res_frame.astype("uint8"), (w, h), interpolation=cv2.INTER_LANCZOS4
        )
        combined = get_image(
            ori_frame, res_frame, [x1, y1, x2, y2],
            mode=args.parsing_mode, fp=fp,
            upper_boundary_ratio=args.upper_boundary_ratio,
            expand=args.expand,
        )
        cv2.imwrite(str(out_frames / f"{kept:08d}.png"), combined)
        kept += 1
        if _total_paste and (i + 1) % max(1, _total_paste // 10) == 0:
            print(f"progress: {min(93, 86 + int(7 * (i + 1) / _total_paste))}% | 回填 {i+1}/{_total_paste}")
    if kept == 0:
        raise RuntimeError("没有生成任何帧(人脸框异常)")

    # ---- 合成视频 + 音轨 ----
    print("阶段: ffmpeg 合成输出视频")
    print(f"Assembling {kept} frames @ {args.fps}fps ...")
    print("progress: 95% | 回填完成, 开始合成视频")
    silent_fd, silent_path = tempfile.mkstemp(suffix="_silent.mp4")
    os.close(silent_fd)
    silent = Path(silent_path)
    try:
        r = subprocess.run(
            [
                ffmpeg_path, "-y", "-v", "warning",
                "-r", str(args.fps),
                "-f", "image2",
                "-i", str(out_frames / "%08d.png"),
                # libx264+yuv420p 要求宽高均为偶数；源图奇数尺寸(如 man2.webp 374x249)
                # 会报 height not divisible by 2，用 scale 强制向下取偶
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-vcodec", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "18",
                str(silent),
            ],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise RuntimeError(f"帧序列合成失败:\n{(r.stderr or '').strip()}")

        r = subprocess.run(
            [
                ffmpeg_path, "-y", "-v", "warning",
                # 音轨用原采样率版本, 不能用给 Whisper 的 16k 单声道版
                "-i", str(mux_audio or audio_path),
                "-i", str(silent),
                "-map", "1:v:0", "-map", "0:a:0",
                "-c:v", "copy", "-c:a", "aac",
                "-shortest",
                str(args.output),
            ],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise RuntimeError(f"音视频封装失败:\n{(r.stderr or '').strip()}")
    finally:
        silent.unlink(missing_ok=True)
        shutil.rmtree(out_frames, ignore_errors=True)

    del vae, unet, whisper, pe, fp
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return args.output


# ---------------------------------------------------------------------------
# IMTalker backend: 单图 + 音频 -> 512x512 说话头口播(子进程跑 vendor 推理入口)
# ---------------------------------------------------------------------------
def run_imtalker(args, image_path: Path, audio_path: Path) -> Path:
    """
    子进程执行 vendor/IMTalker/generator/generate.py。

    不能 in-process import: generate.py 依赖 cwd=IMTalker + 仓根/generator
    都在 sys.path(顶部 `from generator.xxx` / `from renderer.xxx` / `from options.xxx`),
    且 face_alignment 的 torch.compile 在无 triton 时会挂(用环境变量压回 eager)。
    """
    if not IMTALKER_DIR.is_dir():
        raise RuntimeError(f"缺少代码仓 {IMTALKER_DIR}")

    created = ensure_junction_imtalker()
    if created:
        print(f"[OK] 创建目录联接: {IMTALKER_CKPT_LINK} -> {IMTALKER_WEIGHTS_DIR}")

    # IMTalker 输出固定为 res_dir/<ref 文件名>.mp4, 先落临时目录再搬到 --output
    work_dir = Path(tempfile.mkdtemp(prefix="imtalker_"))
    env = dict(os.environ)
    env.update(
        PYTHONUNBUFFERED="1",
        PYTHONIOENCODING="utf-8",
        TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",
        # face_alignment 会 torch.compile, 本机无 triton -> 压回 eager 路径
        TORCH_COMPILE_DISABLE="1",
        TORCHDYNAMO_SUPPRESS_ERRORS="1",
        PYTHONPATH=os.pathsep.join(
            [str(IMTALKER_DIR), str(IMTALKER_DIR / "generator")]
        ),
    )
    cmd = [
        sys.executable, "-u", str(IMTALKER_DIR / "generator" / "generate.py"),
        "--ref_path", str(image_path),
        "--aud_path", str(audio_path),
        "--res_dir", str(work_dir),
        "--generator_path", str(IMTALKER_GENERATOR),
        "--renderer_path", str(IMTALKER_RENDERER),
        "--wav2vec_model_path", str(IMTALKER_WAV2VEC),
        "--a_cfg_scale", str(args.a_cfg_scale),
        "--nfe", str(args.nfe),
        "--seed", str(args.seed),
    ]
    # 裁剪默认关: 硬编码 --crop 会让 IMTalker 输出人脸特写而 MuseTalk 全帧输出,
    # 同图同音频对比不公平; 关闭时原图直入(内部仅等比压到 512), 构图与 MuseTalk 同口径
    if args.crop:
        cmd.append("--crop")
    print(f"阶段: IMTalker 推理 ({image_path.name} + {audio_path.name})")
    print("progress: 5% | 启动 IMTalker 子进程", flush=True)
    try:
        # 不 capture: stdout/stderr 直通, 阶段/progress 行才能被上层解析
        r = subprocess.run(
            cmd, cwd=str(IMTALKER_DIR), env=env,
        )
        if r.returncode != 0:
            raise RuntimeError(f"IMTalker 推理退出码 {r.returncode}")
        produced = work_dir / f"{image_path.stem}.mp4"
        if not produced.is_file() or produced.stat().st_size < 1024:
            raise RuntimeError(f"IMTalker 未产出有效视频: {produced}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(args.output))
        # 脸部修复(方案2): GFPGAN 逐帧 + landmarks 羽化贴回, 治生成柔化。
        # 默认开; --no-restore 关闭。权重缺失/失败只警告不阻断。
        if not getattr(args, "no_restore", False):
            print("progress: 97% | 脸部修复(GFPGAN)", flush=True)
            try:
                if str(Path(__file__).resolve().parent) not in sys.path:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                from face_restore import restore_video
                restore_video(args.output)  # 原地替换, 音轨保留
            except Exception as e:
                print(f"[warn] 脸部修复跳过: {e}", flush=True)
        print("progress: 100% | IMTalker 完成", flush=True)
        return args.output
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="口型对齐: 人物图 + 音频 -> 讲话视频(musetalk/imtalker 双后端)。"
    )
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE,
                        help="人物图片(jpg/png/webp)。")
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO,
                        help="说话音频(mp3/wav/m4a)。")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 mp4, 默认 assets/lip_sync/<图名>_<音频名>[_imtalker].mp4")
    parser.add_argument("--result-dir", type=Path, default=None,
                        help="中间帧目录, 默认临时目录。")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=2,
                        help="UNet 批大小。6GB 显存建议 2。")
    parser.add_argument("--fp16", dest="fp16", action="store_true", default=True,
                        help="半精度推理(6GB 卡必开)。")
    parser.add_argument("--no-fp16", dest="fp16", action="store_false")
    parser.add_argument("--device", default="auto",
                        help="auto / cuda:0 / cpu")
    parser.add_argument("--gpu-id", type=int, default=0)
    parser.add_argument("--extra-margin", type=int, default=10,
                        help="人脸 crop 下边界外扩像素。")
    parser.add_argument("--audio-padding-length-left", type=int, default=2)
    parser.add_argument("--audio-padding-length-right", type=int, default=2)
    parser.add_argument("--left-cheek-width", type=int, default=90)
    parser.add_argument("--right-cheek-width", type=int, default=90)
    parser.add_argument("--parsing-mode", default="jaw",
                        choices=["raw", "jaw", "neck"])
    parser.add_argument("--bbox-shift", type=int, default=0,
                        help="人脸框上边界平移, 官方提示范围见运行日志。")
    parser.add_argument("--upper-boundary-ratio", type=float, default=0.58,
                        help="融合区域上边界(占 crop 高度比例)。越大越保留原图表情、"
                             "但口型运动幅度越小。0.5=官方默认(口型最大/表情替换最多), "
                             "实测 0.58 为平衡点, 0.62 口型幅度降约 25%%。")
    parser.add_argument("--expand", type=float, default=1.5,
                        help="融合 crop 外扩倍数, 影响 mask 可用范围。")
    parser.add_argument("--backend", default="musetalk",
                        choices=["musetalk", "imtalker"],
                        help="musetalk=全图融合(默认); imtalker=单图直接生成 512x512 说话头。")
    parser.add_argument("--a-cfg-scale", type=float, default=2.0,
                        help="IMTalker 音频 CFG 强度, 官方示例 2。")
    parser.add_argument("--nfe", type=int, default=10,
                        help="IMTalker ODE 采样步数, 越大越稳越慢。")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--crop", action="store_true", default=False,
                        help="IMTalker 输出人脸裁剪特写; 默认不裁(原图直入), 与 MuseTalk 全帧输出同口径可比")
    parser.add_argument("--no-restore", action="store_true",
                        help="跳过 IMTalker 输出的 GFPGAN 脸部修复(默认开启, 治生成柔化/模糊)")
    parser.add_argument("--max-seconds", type=float, default=0,
                        help="限制音频时长(秒), 0 不限制。冒烟测试建议 8。")
    parser.add_argument("--force", action="store_true",
                        help="输出已存在时强制重跑。")
    parser.add_argument("--check", action="store_true",
                        help="只体检环境与权重, 不做推理。")
    args = parser.parse_args()

    # ---- 1. 体检 ----
    if not LIPSYNC_DIR.is_dir():
        print(f"ERROR: 未找到 {LIPSYNC_DIR}", file=sys.stderr)
        return 1

    imtalker = args.backend == "imtalker"
    try:
        created = ensure_junction_imtalker() if imtalker else ensure_junction()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if created:
        link = IMTALKER_CKPT_LINK if imtalker else MUSETALK_DIR / "models"
        target = IMTALKER_WEIGHTS_DIR if imtalker else LIPSYNC_DIR
        print(f"[OK] 创建目录联接: {link} -> {target}")

    problems = missing_weights_imtalker() if imtalker else missing_weights()
    if problems:
        print("ERROR: 权重不完整:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(IMTALKER_DOWNLOAD_HINT if imtalker else DOWNLOAD_HINT, file=sys.stderr)
        return 1

    for label, path in (
        ("image", args.image),
        ("audio", args.audio),
    ):
        if not path.is_file():
            print(f"ERROR: {label} 文件不存在: {path}", file=sys.stderr)
            return 1

    # 重要: 后面会 os.chdir() 到 MuseTalk 仓根, 相对路径必须先转绝对
    args.image = Path(os.path.abspath(args.image))
    args.audio = Path(os.path.abspath(args.audio))
    if args.output:
        args.output = Path(os.path.abspath(args.output))

    # 幂等: 输出已存在且未 --force 则跳过
    default_name = (
        f"{args.image.stem}_{args.audio.stem}_imtalker.mp4" if imtalker
        else f"{args.image.stem}_{args.audio.stem}.mp4"
    )
    planned_output = args.output or (OUTPUT_DIR / default_name)
    if (
        not args.check
        and not args.force
        and planned_output.is_file()
        and planned_output.stat().st_size >= 1024
    ):
        print(f"[OK] 输出已存在, 跳过: {planned_output}")
        print("  需要重跑请加 --force")
        return 0

    if args.check:
        if imtalker:
            print("[OK] 权重完整, 检查 IMTalker 依赖 ...")
            try:
                import av  # noqa: F401
                import cv2  # noqa: F401
                import face_alignment  # noqa: F401
                import librosa  # noqa: F401
                import timm  # noqa: F401
                import torchdiffeq  # noqa: F401
                import torch
                from transformers import Wav2Vec2FeatureExtractor  # noqa: F401
                if not torch.cuda.is_available():
                    print("ERROR: IMTalker 需要 CUDA, 当前不可用", file=sys.stderr)
                    return 1
            except Exception:
                traceback.print_exc()
                return 1
            print("[OK] 依赖导入正常 (av/torchdiffeq/timm/face_alignment/librosa/transformers)")
            print("[OK] CUDA 可用")
            return 0
        print("[OK] 权重完整, 检查依赖与 DWPose ...")
        enter_musetalk_pkg()
        try:
            load_mmpose_stack()
            import diffusers, cv2  # noqa: F401
            from musetalk.utils.utils import load_all_model  # noqa: F401
            # 真正触发 DWPose checkpoint + S3FD 加载(import 即建模)
            from musetalk.utils.preprocessing import get_landmark_and_bbox  # noqa: F401
            from musetalk.utils.face_parsing import FaceParsing  # noqa: F401
        except Exception:
            traceback.print_exc()
            return 1
        print("[OK] 依赖导入正常 (mmcv/mmpose/mmdet/diffusers/opencv/musetalk)")
        print("[OK] DWPose + S3FD + FaceParsing 权重加载成功")
        return 0

    if not args.output:
        args.output = OUTPUT_DIR / default_name
    else:
        args.output = Path(os.path.abspath(args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # ---- 2. IMTalker 后端 ----
    if imtalker:
        work_dir = Path(tempfile.mkdtemp(prefix="lipsync_it_"))
        try:
            # librosa 会自行重采样, 只需按 max_seconds 截断且保原始音质
            audio_in = trim_audio(
                args.audio, args.max_seconds, work_dir,
                tag="mux", sample_rate=None, channels=None,
            )
            try:
                out = run_imtalker(args, args.image, audio_in)
            except Exception:
                print("ERROR: IMTalker 推理失败:", file=sys.stderr)
                traceback.print_exc()
                return 1
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        size = out.stat().st_size if out.is_file() else 0
        print(f"\n[OK] 输出: {out}  ({size} 字节)")
        if size < 1024:
            print("ERROR: 输出文件过小, 可能生成失败", file=sys.stderr)
            return 1
        print("  播放: ffplay / 直接双击打开即可核对口型。")
        return 0

    # ---- 2'. MuseTalk 后端 ----
    enter_musetalk_pkg()
    try:
        load_mmpose_stack()
    except Exception:
        print("ERROR: mmpose/mmdet 导入失败:", file=sys.stderr)
        traceback.print_exc()
        return 1

    ffmpeg_path = ffmpeg_exe()

    work_dir = Path(tempfile.mkdtemp(prefix="lipsync_"))
    try:
        audio_path = trim_audio(
            args.audio, args.max_seconds, work_dir,
            tag="asr", sample_rate=16000, channels=1,
        )
        mux_audio = trim_audio(
            args.audio, args.max_seconds, work_dir,
            tag="mux", sample_rate=None, channels=None,
        )
        frames_dir = args.result_dir or (work_dir / "frames")
        args.result_dir = Path(frames_dir)

        try:
            out = run_inference(
                args, args.image, audio_path, ffmpeg_path, mux_audio=mux_audio
            )
        except Exception:
            print("ERROR: 推理失败:", file=sys.stderr)
            traceback.print_exc()
            return 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    size = out.stat().st_size if out.is_file() else 0
    print(f"\n[OK] 输出: {out}  ({size} 字节)")
    if size < 1024:
        print("ERROR: 输出文件过小, 可能生成失败", file=sys.stderr)
        return 1
    print("  播放: ffplay / 直接双击打开即可核对口型。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
