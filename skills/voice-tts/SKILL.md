---
name: voice-tts
description: 法拍房话术 TTS 配音——用 edge-tts(免费, 微软 Edge 在线神经语音, 无需 key)把 data.script 每个角度合成 mp3, 写 assets/<source>/<item_id>/voice/, 并记录 DB data.voice。何时触发: 需要话术转语音、TTS 配音、生成口播音频时,触发关键词包括"配音"、"语音"、"TTS"、"音频"。
---

# voice-tts 法拍房话术配音

把 script-writer 生成的 8 角度话术转成 mp3 音频,供后续视频合成(声画对齐)使用。

## 依赖

- `edge-tts`(已装): 免费, 无需 API key, 走微软 Edge 在线接口, 需联网

## 使用方式

```bash
# 单套
python skills/voice-tts/scripts/tts_voice.py --source gpai --item-id 52946

# 批量(幂等,已有 voice 则跳过)
python skills/voice-tts/scripts/tts_voice.py --source ali --all --limit 50

# 换音色 / 强制重做
python skills/voice-tts/scripts/tts_voice.py --source gpai --item-id 52946 --voice zh-CN-XiaoxiaoNeural --force
```

### Agent 调用

```python
import sys; sys.path.insert(0, ".")
# importlib 加载 skills/voice-tts/scripts/tts_voice.py 的 run(source, item_id)
```

## 数据契约

- 输入: DB `data.script`(8 角度口播稿)
- 输出:
  - 磁盘: `assets/<source>/<item_id>/voice/<角度>.mp3`(逐角度) + `<item_id>_full.mp3`(整篇)
  - DB: `data.voice` = `[{angle, file, duration}, ...]` + combined
- 音色: `--voice`(默认 zh-CN-YunxiNeural), 见 `edge-tts --list-voices`

## 注意事项

- edge-tts 对并发有限制(过快会 403), 批量默认 workers=1 并加小延时; 必要时手动调
- 需联网; 失败时对应文件跳过并在 DB 记录, 不中断整批
