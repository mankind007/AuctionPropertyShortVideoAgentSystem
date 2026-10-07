#!/usr/bin/env python
"""视频脸部修复(逐帧) — IMTalker 输出固有柔化的后处理补救。

链路: face_alignment 68点 -> 取5点 -> FFHQ 仿射对齐到512 -> GFPGANv1.4 修复
      -> 逆仿射贴回原帧 + 羽化椭圆蒙版 + 固定 strength 混合。

防闪烁(社区经验, 见 ruslanmv/avatar-renderer-mcp 9acb436 讨论):
  - 逐帧独立修复会 shimmer -> landmarks 时序 EMA 平滑对齐矩阵
  - 固定 blend strength, 蒙版只盖脸不动背景(非脸像素逐位不变)
  - 无脸帧直接透传, 不做任何改动

不依赖 facexlib 检测权重(retinaface/parsenet): FaceRestoreHelper 构造时会
急切加载这两个模型, 这里直接用底层 GFPGANv1Clean + face_alignment 自带检测。

用法:
  python face_restore.py --input in.mp4 --output out.mp4
  python face_restore.py --input in.mp4            # 原地替换(写临时文件)
"""
import argparse
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]  # scripts -> lip-sync -> skills -> repo
WEIGHTS = REPO_ROOT / "models" / "face_restore" / "GFPGANv1.4.pth"

# FFHQ 5点模板(GFPGAN 训练对齐口径, 与 facexlib FaceRestoreHelper 一致)
FFHQ5 = np.array(
    [
        [192.98138, 239.94708],  # left eye
        [318.90277, 240.19360],  # right eye
        [256.63416, 314.01935],  # nose
        [201.26117, 371.41043],  # mouth left
        [313.08905, 371.15118],  # mouth right
    ],
    dtype=np.float32,
)


def lm68_to_5(lm68) -> np.ndarray:
    lm = np.asarray(lm68, dtype=np.float32)
    return np.stack(
        [
            lm[36:42].mean(axis=0),  # left eye center
            lm[42:48].mean(axis=0),  # right eye center
            lm[30],  # nose tip
            lm[48],  # mouth left
            lm[54],  # mouth right
        ]
    ).astype(np.float32)


def _warp(img: np.ndarray, M: np.ndarray, dsize, bilinear=True):
    import cv2
    flags = cv2.INTER_LINEAR if bilinear else cv2.INTER_NEAREST
    return cv2.warpAffine(img, M, dsize, flags=flags, borderMode=cv2.BORDER_REPLICATE)


def _invert_affine(M: np.ndarray) -> np.ndarray:
    M3 = np.vstack([np.asarray(M, np.float64), [0.0, 0.0, 1.0]])
    return np.linalg.inv(M3)[:2].astype(np.float32)


def _ellipse_mask(w: int, h: int) -> np.ndarray:
    """对齐空间 512x512 椭圆蒙版: FFHQ 脸约 x100..410 / y60..470, 内缩留边。"""
    import cv2
    mask = np.zeros((h, w), np.uint8)
    cv2.ellipse(mask, (256, 268), (150, 195), 0, 0, 360, 255, -1)
    return mask


class FaceRestorer:
    def __init__(self, weight_path: Path = WEIGHTS, gfpgan_weight: float = 0.5, device: str = "cuda"):
        import torch
        from basicsr.utils import img2tensor, tensor2img
        from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean
        import face_alignment

        self.torch = torch
        self.img2tensor = img2tensor
        self.tensor2img = tensor2img

        weight_path = Path(weight_path)
        if not weight_path.is_file():
            raise FileNotFoundError(
                f"缺少 GFPGAN 权重: {weight_path}\n"
                "下载: gh-proxy.com/https://github.com/TencentARC/GFPGAN/releases/"
                "download/v1.3.0/GFPGANv1.4.pth"
            )

        self.model = GFPGANv1Clean(
            out_size=512, num_style_feat=512, channel_multiplier=2,
            decoder_load_path=None, fix_decoder=False, num_mlp=8,
            input_is_latent=True, different_w=True, narrow=1, sft_half=True,
        )
        try:
            ckpt = torch.load(str(weight_path), map_location="cpu")
        except Exception:
            ckpt = torch.load(str(weight_path), map_location="cpu", weights_only=False)
        key = "params_ema" if "params_ema" in ckpt else "params"
        self.model.load_state_dict(ckpt[key], strict=True)
        self.model.eval().to(device)
        self.device = device
        self.gw = gfpgan_weight

        self.fa = face_alignment.FaceAlignment(
            face_alignment.LandmarksType.TWO_D, flip_input=False,
            device=device, compile=False,
        )
        self.prev5 = None  # landmarks 时序 EMA 状态

    def restore_rgb(self, frame_rgb: np.ndarray, strength: float = 1.0, feather: float = 12.0):
        """frame_rgb: HxWx3 uint8 RGB。返回 (修复后 RGB, 是否修复)。"""
        from torchvision.transforms.functional import normalize

        try:
            lms = self.fa.get_landmarks(frame_rgb)
        except Exception:
            lms = None
        if not lms:
            self.prev5 = None
            return frame_rgb, False

        # 取最大脸(排除背景小脸/误检)
        def area(lm):
            a = np.asarray(lm)
            return float((a[:, 0].max() - a[:, 0].min()) * (a[:, 1].max() - a[:, 1].min()))

        lm = max(lms, key=area)
        pts5 = lm68_to_5(lm)
        if self.prev5 is not None:  # EMA: 平滑检测抖动 -> 对齐矩阵稳定 -> 少 shimmer
            pts5 = 0.5 * pts5 + 0.5 * self.prev5
        self.prev5 = pts5

        import cv2
        M, _ = cv2.estimateAffinePartial2D(
            pts5, FFHQ5, method=cv2.RANSAC, ransacReprojThreshold=3.0
        )
        if M is None:
            return frame_rgb, False

        h, w = frame_rgb.shape[:2]
        aligned = _warp(frame_rgb, M, (512, 512))

        t = self.img2tensor(aligned / 255.0, bgr2rgb=False, float32=True)
        normalize(t, (0.5,) * 3, (0.5,) * 3, inplace=True)
        t = t.unsqueeze(0).to(self.device)
        with self.torch.no_grad():
            out = self.model(t, return_rgb=False, weight=self.gw)[0]
        restored512 = self.tensor2img(out.squeeze(0), rgb2bgr=False, min_max=(-1, 1)).astype(np.uint8)

        # 逆仿射贴回 + 椭圆羽化蒙版(蒙版在对齐空间构建再变换回去, 跟随脸的旋转)
        Minv = _invert_affine(M)
        restored = _warp(restored512, Minv, (w, h))
        mask = _warp(_ellipse_mask(512, 512), Minv, (w, h), bilinear=False)
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=feather, sigmaY=feather)
        m = (mask.astype(np.float32) / 255.0 * strength)[..., None]

        blended = frame_rgb.astype(np.float32) * (1.0 - m) + restored.astype(np.float32) * m
        return np.clip(blended, 0, 255).astype(np.uint8), True


def _has_audio(path: Path) -> bool:
    import av
    try:
        with av.open(str(path)) as c:
            return bool(c.streams.audio)
    except Exception:
        return False


def _ffmpeg_mux(video_path: Path, audio_src: Path, out_path: Path):
    import imageio_ffmpeg
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y", "-i", str(video_path), "-i", str(audio_src),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError(f"mux 失败: {r.stderr.decode(errors='ignore')[-500:]}")


def restore_video(
    input_path: Path,
    output_path: Path = None,
    weight_path: Path = WEIGHTS,
    gfpgan_weight: float = 0.5,
    strength: float = 1.0,
    feather: float = 12.0,
) -> Path:
    """流式: 解码一帧 -> 修复 -> 编码, 内存平坦(不整段驻留)。音轨原样 mux。"""
    import av

    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path
    in_place = output_path.resolve() == input_path.resolve()

    restorer = FaceRestorer(weight_path=weight_path, gfpgan_weight=gfpgan_weight)

    # 临时文件放输出同目录: os.replace 不跨盘(C 盘 temp -> E 盘会 OSError)
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".mp4", prefix="restore_", dir=str(output_path.parent))
    os.close(tmp_fd)
    tmp_video = Path(tmp_name)

    restored_n = 0
    total = 0
    try:
        with av.open(str(input_path)) as src:
            vsrc = src.streams.video[0]
            fps = vsrc.average_rate or Fraction(30, 1)
            if not isinstance(fps, (int, Fraction)):
                fps = Fraction(fps)
            with av.open(str(tmp_video), "w") as dst:
                st = dst.add_stream("libx264", rate=fps)
                st.pix_fmt = "yuv420p"
                st.options = {"crf": "17", "preset": "medium"}
                out_w = out_h = None
                for f in src.decode(video=0):
                    arr = f.to_ndarray(format="rgb24")  # RGB
                    arr, did = restorer.restore_rgb(arr, strength=strength, feather=feather)
                    restored_n += int(did)
                    total += 1
                    if out_w is None:
                        out_w = arr.shape[1] - (arr.shape[1] % 2)  # H.264 需偶数尺寸
                        out_h = arr.shape[0] - (arr.shape[0] % 2)
                        st.width, st.height = out_w, out_h
                    if arr.shape[1] != out_w or arr.shape[0] != out_h:
                        arr = arr[:out_h, :out_w]
                    vf = av.VideoFrame.from_ndarray(arr, format="rgb24")
                    for pkt in st.encode(vf):
                        dst.mux(pkt)
                for pkt in st.encode(None):
                    dst.mux(pkt)

        if total == 0:
            raise RuntimeError(f"没有视频帧: {input_path}")

        if _has_audio(input_path):
            if in_place:
                # 原地: 先 mux 到临时文件再原子替换, 避免 ffmpeg 边读边写同一路径
                fd2, name2 = tempfile.mkstemp(suffix=".mp4", prefix="restore_out_", dir=str(output_path.parent))
                os.close(fd2)
                mux_dst = Path(name2)
                _ffmpeg_mux(tmp_video, input_path, mux_dst)
                os.replace(mux_dst, output_path)
            else:
                _ffmpeg_mux(tmp_video, input_path, output_path)
            tmp_video.unlink(missing_ok=True)
        else:
            os.replace(tmp_video, output_path)
            tmp_video = None
    finally:
        if tmp_video is not None:
            tmp_video.unlink(missing_ok=True)

    print(f"脸部修复完成: {restored_n}/{total} 帧已增强 -> {output_path}", flush=True)
    return output_path


def main(argv=None):
    p = argparse.ArgumentParser(description="视频脸部修复(GFPGAN, 防闪烁羽化贴回)")
    p.add_argument("--input", required=True, help="输入视频(会被读取音轨)")
    p.add_argument("--output", default=None, help="输出视频; 省略则原地替换")
    p.add_argument("--weights", default=str(WEIGHTS), help="GFPGANv1.4.pth 路径")
    p.add_argument("--gfpgan-weight", type=float, default=0.5,
                   help="GFPGAN 内部 weight(官方默认 0.5, 越高修复越强)")
    p.add_argument("--strength", type=float, default=1.0,
                   help="贴回混合强度 0-1(降低可减少闪烁, 默认 1.0)")
    p.add_argument("--feather", type=float, default=12.0, help="蒙版羽化 sigma(px)")
    args = p.parse_args(argv)

    restore_video(
        input_path=Path(args.input),
        output_path=Path(args.output) if args.output else None,
        weight_path=Path(args.weights),
        gfpgan_weight=args.gfpgan_weight,
        strength=args.strength,
        feather=args.feather,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
