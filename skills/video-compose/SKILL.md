---
name: video-compose
description: 法拍房宣传短视频合成——把 promo-image 生成的海报(poster_*_v.png/_h.png)按序拼接为竖版/横版 MP4,写 assets/<source>/<item_id>/video/,并记录 DB data.video。TTS 配音暂不参与(静音视频)。何时触发: 需要把海报拼成视频、生成房源短视频、出视频素材时,触发关键词包括"视频"、"拼接"、"合成视频"、"短视频"。
---

# video-compose 法拍房短视频合成

把房源海报拼接成静音短视频(竖版 9:16 + 横版 16:9),供后续 TTS 配音/发布使用。

## 依赖

- ffmpeg: 由 `imageio-ffmpeg` 捆绑(已装),脚本自动定位,无需系统安装

## 使用方式

```bash
# 单套
python skills/video-compose/scripts/make_video.py --source gpai --item-id 52946

# 批量(幂等,已有 video 则跳过)
python skills/video-compose/scripts/make_video.py --source ali --all --limit 50

# 强制重做 / 每张海报时长
python skills/video-compose/scripts/make_video.py --source gpai --all --force --duration 5
```

### Agent 调用

```python
import sys; sys.path.insert(0, ".")
from skills.promo_image.scripts.compose import run  # 海报
# 视频: 待海报就绪后 importlib 加载 make_video.py 的 run(source, item_id)
```

## 数据契约

- 输入: `assets/<source>/<item_id>/posters/poster_*_v.png` + `poster_*_h.png`(promo-image 产物)
- 输出:
  - 磁盘: `assets/<source>/<item_id>/videos/<item_id>_v.mp4`(竖版)、`<item_id>_h.mp4`(横版)
  - DB: `data.video` = `{vertical: relpath, horizontal: relpath}`
- 无音轨(`-an`), TTS 后续叠加

## 合成逻辑

- 竖版/横版各自按海报文件名顺序拼接(`concat` filter), 每张停留 `--duration` 秒(默认4)
- 同一房源同向海报画布一致; 编码 libx264 + yuv420p(奇数尺寸自动偶数化, 长边限 1920 防超 libx264 宏块上限)
- 静音(`-an`), 分辨率/帧率由海报与 `--fps`(默认25)决定

## 视频+配音(mux_voice.py)

```bash
# 前置: 该房源已有 voice(voice-tts)
python skills/video-compose/scripts/mux_voice.py --source gpai --item-id 52946
python skills/video-compose/scripts/mux_voice.py --source ali --all --limit 1000
```

- 每张海报段的展示时长 = 该角度音频时长(**声画对齐**, 解决"视频固定 4s/张 vs 音频长短不一")
- 音轨 = 逐角度 mp3 按海报顺序 concat; 输出 `<id>_{v,h}_voiced.mp4`
- DB: `data.video_voiced` = `{vertical, horizontal}`; 幂等(已有则跳过, `--force` 重做)
