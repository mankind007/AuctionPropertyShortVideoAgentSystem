"""
极简版 Qwen3-TTS 声音克隆测试。

运行：
    .venv\Scripts\python.exe tests\test_qwen3_tts_clone_simple.py

模式一（默认，效果较好）：
  提供一段 5~10 秒的参考音频，以及这段音频里实际说的文字。

模式二（懒人模式）：
  把 X_VECTOR_ONLY = True
  这样不需要写 REF_TEXT，但克隆质量会下降。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import soundfile as sf
import torch

# ---------------------------------------------------------------------------
# 用户只需要改这里
# ---------------------------------------------------------------------------
REF_AUDIO = Path("assets/汲总.mp3")          # 参考音频cctv_audio_segment.mp3
REF_TEXT = (
    #"今年以来，房地产市场备受关注，一系列政策效果怎么样，"
    #"如何看待房地产市场，如何重构房地产发展模式？"
    #"这里是深圳市特资投资集团公司，关注我，带你购房不迷路"
    #"还没签，正在审他的合同和谈条件呢啊"
    "承担6000万就完了，对不对啊？因为各付各税嘛。但现实情况不是这样。现实情况，那个债务人，债务人是所有权人，债务人是这个房子的拥有者。对不对，我买的是。"
)                                                           # 参考音频里实际说的话（不需要完整，但要对齐）
TARGET_TEXT = "这里是深圳市特资投资集团公司。法拍房购买有风险，这条视频帮你把账算明白。"  # 要合成的话术

X_VECTOR_ONLY = False                                       # True=不需要 REF_TEXT，但效果会变差

# ---------------------------------------------------------------------------
# 模型和输出路径
# ---------------------------------------------------------------------------
MODEL_DIR = Path(r"models/tts/Qwen3-TTS-12Hz-0.6B-Base")
if not MODEL_DIR.is_dir():
    MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "tts" / "Qwen3-TTS-12Hz-0.6B-Base"
OUTPUT_DIR = Path("assets/tts_test_output")
OUTPUT_WAV = OUTPUT_DIR / "tts_clone_simple_output.wav"


def main() -> int:
    if not MODEL_DIR.exists():
        print(f"ERROR: 模型目录不存在: {MODEL_DIR}", file=sys.stderr)
        return 1
    if not REF_AUDIO.exists():
        print(f"ERROR: 参考音频不存在: {REF_AUDIO}", file=sys.stderr)
        return 1

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    print(f"使用设备: {device}, dtype: {dtype}")
    print(f"参考音频: {REF_AUDIO}")
    print(f"目标话术: {TARGET_TEXT}")

    print("\n正在加载 qwen_tts...")
    from qwen_tts import Qwen3TTSModel

    print(f"正在加载模型: {MODEL_DIR}")
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL_DIR),
        device_map=device,
        dtype=dtype,
        attn_implementation="eager",
    )

    print("\n正在克隆声音并生成音频...")
    kwargs = {
        "text": TARGET_TEXT,
        "language": "Chinese",
        "ref_audio": str(REF_AUDIO),
    }
    if X_VECTOR_ONLY:
        kwargs["x_vector_only_mode"] = True
        print("模式: x_vector_only（无需 ref_text，效果较弱）")
    else:
        kwargs["ref_text"] = REF_TEXT
        print(f"模式: 精确克隆\n参考文本: {REF_TEXT}")

    wavs, sr = model.generate_voice_clone(**kwargs)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(str(OUTPUT_WAV), wavs[0], sr)

    print(f"\n完成！输出文件: {OUTPUT_WAV}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    sys.exit(main())
