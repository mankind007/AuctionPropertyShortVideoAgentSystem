---
name: avatar-video
description: 数字人视频端到端生成——静态人物图 + 语音生成口播视频(ComfyUI InfiniteTalk 后端)并自动烧中文字幕。三阶段：generate_video 生成视频(自动按图片比例选分辨率,人物不被裁切) / whisper_srt 语音转写字幕 / burn_subtitle ffmpeg 烧字幕。何时触发：需要完整的数字人讲解视频、人物开口讲话视频、带字幕的宣传片时；关键词：数字人、avatar、口播、讲解视频、生成视频、字幕、烧字幕、转写字幕、InfiniteTalk、公司介绍视频。不适用：只要图片不动嘴的场合(用 lip-sync 的 MuseTalk/IMTalker 更快)、纯房源海报拼接(用 video-compose)、视频剪辑拼接(用 video-compose)。
params: [{"name":"image","type":"string","label":"人物图片路径","required":true},{"name":"audio","type":"string","label":"驱动音频路径","required":true},{"name":"name","type":"string","label":"输出名(可选,默认取音频名)"},{"name":"area","type":"number","label":"像素预算(越小越快)","default":256000},{"name":"model","type":"string","label":"Whisper 模型 tiny|base|small|medium|large-v3","default":"medium"},{"name":"style","type":"string","label":"字幕样式 corporate|bottom","default":"corporate"},{"name":"prompt","type":"string","label":"英文正向提示词(可选)"},{"name":"force","type":"boolean","label":"强制重跑","default":false}]
---

# avatar-video（数字人讲解视频）

静态人物图 + 语音 → 口播视频 + 中文字幕。三阶段流水线，也可以单独跑某一阶段。

| 阶段 | 脚本 | 产物 |
|------|------|------|
| 1 生成视频 | `generate_video.py` | `assets/avatar_video/<name>.mp4` |
| 2 转写字幕 | `whisper_srt.py` | `assets/avatar_video/<name>.srt` |
| 3 烧字幕 | `burn_subtitle.py` | `assets/avatar_video/<name>_sub.mp4` |

## 何时用

- 需要**完整**的数字人讲解视频：人物开口 + 中文字幕
- 公司介绍、房源讲解、知识分享等口播场景
- 用户说：数字人视频、生成视频、带字幕的口播、InfiniteTalk

**不用**：
- 只要嘴动、不要字幕 → `lip-sync`（MuseTalk/IMTalker 更快，本项目已装依赖）
- 海报拼视频 → `video-compose`

## 与 lip-sync 的取舍

| | avatar-video（本 skill） | lip-sync |
|---|---|---|
| 后端 | ComfyUI InfiniteTalk (14B) | MuseTalk V1.5 / IMTalker |
| 显存 | 8GB 极限，需 block swap | 6GB 可跑 |
| 速度 | 约 3.5 分钟/10秒 | 数十秒/10秒 |
| 质量 | 更高，人物动作自然 | 快，适合批量 |
| 字幕 | 内置 Whisper + 烧制 | 无 |

## 依赖

- **ComfyUI**：`D:\Program\ComfyUI`，必须带 `--disable-async-offload --disable-cuda-malloc` 启动（脚本会自动拉起，用错参数会导致 GPU 映射崩溃）
- **模型**：`Wan2_1-I2V-14B-480P_fp8_e5m2.safetensors`、`infinite_talk.safetensors`、`Wan2_1_VAE_fp32.safetensors`、`clip_vision_h.safetensors`
- **Whisper**：`faster-whisper` 已装于项目 `.venv`；模型放 `models/avatar-video/whisper/<model>/`（与其他 skill 权重同布局，不用 C 盘 HF 缓存）
- **ffmpeg**：`imageio-ffmpeg` 捆绑（项目 venv 已有）

## 怎么跑

仓库根执行，**全程用项目 venv**：

```powershell
# 体检
.venv\Scripts\python.exe skills\avatar-video\scripts\generate_video.py --check

# 一条命令跑完三阶段
.venv\Scripts\python.exe skills\avatar-video\scripts\run_pipeline.py --image man.png --audio speech.wav

# 分阶段
.venv\Scripts\python.exe skills\avatar-video\scripts\generate_video.py --image man.png --audio speech.wav
.venv\Scripts\python.exe skills\avatar-video\scripts\whisper_srt.py speech.wav --model medium
.venv\Scripts\python.exe skills\avatar-video\scripts\burn_subtitle.py out.mp4 speech.srt --style corporate

# 更快（像素预算调小，约 2.5 分钟/段）
... --area 180000

# 首次使用先下载 Whisper 模型
.venv\Scripts\python.exe skills\avatar-video\scripts\whisper_srt.py --download medium
```

## 任意图片自动适配

`generate_video.py` 读图片真实尺寸，按比例算一个 `/16` 对齐的分辨率（VAE 8× 下采样 × patch 2 的硬约束），并把缩放方式设为等比（`pillarbox_blur` 模糊填充），**不会裁切人物**。

- 像素预算 `area` 决定速度：序列长度 = `(宽/16)×(高/16)×21`
  - `180000` → 约 2.5 分钟/段（快）
  - `256000` → 约 3.5 分钟/段（默认）
  - `400000` → 约 5 分钟/段（清晰）
- 横版、竖版、方图都保持原比例，误差 <1.5%

## 约定

- **输出契约**：`assets/avatar_video/<name>.mp4`（无字幕）+ `<name>_sub.mp4`（带字幕），音轨来自输入音频
- **幂等**：`run_pipeline.py` 检测到已存在的阶段产物会跳过，`--force` 重跑
- **字幕模型**：默认 `medium`（中文准确率高）。实测 31.7 秒音频耗时 18.3 秒，仅占视频生成的 0.7%，比 `small` 多花 11 秒换来明显更准的结果。`tiny` 错字多，仅供冒烟测试
- **字幕样式**：`corporate`（浅色字 + 半透明深色底条，适合正式场合）/ `bottom`（白字描边，通用）
- **失败不静默**：ComfyUI 未启动、模型缺失、显存不足都会明确 exit 1

## 踩坑与调参

详见 `references/部署与调参.md`，包含：
- 为什么必须关 Edge/迅雷（吃 10GB 内存导致加载崩溃）
- `--disable-cuda-malloc` 的原因（expandable_segments 在 WDDM 上会崩）
- HF 镜像下载大模型的正确姿势（走 curl 而非 xet）

## 测试

`tests/test_avatar_video.py`（契约：路径常量、`--check`/`--help`、分辨率吸附、whisper 模型列表）。
