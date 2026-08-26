---
name: script-writer
description: 法拍房话术(口播稿)生成——读取房源数据(DB)+ 话术素材库(CSV),按规则填充/宽松兜底生成 8 角度话术,可选调用 LLM(agent/model.py)润色增强,校验后写回 data.script。何时触发: 需要生成/重生成/润色房源口播稿时,触发关键词包括"话术"、"口播稿"、"文案生成"、"生成话术"、"润色话术"。
---

# script-writer 法拍房话术生成

生成法拍房 8 角度口播稿,写回 DB `data.script`,供 promo-image 海报合成与后续 TTS/视频使用。

## 触发场景

- 为新采集房源生成话术(规则填充)
- 已生成话术的房源重新生成(模板/清洗规则变更后 `--force`)
- 用 LLM 润色增强话术(`--llm`,可选,按 item 开启)

## 使用方式

```bash
# 单套(规则填充)
python skills/script-writer/scripts/generate_scripts.py --source ali --item-id 1064719406791

# 批量(幂等,已有 data.script 则跳过)
python skills/script-writer/scripts/generate_scripts.py --source ali --all --limit 50

# LLM 增强(可选,走 agent/model.py 基座)
python skills/script-writer/scripts/generate_scripts.py --source ali --all --limit 20 --llm --workers 4

# 强制重生成
python skills/script-writer/scripts/generate_scripts.py --source gpai --all --force

# 只打印不写库
python skills/script-writer/scripts/generate_scripts.py --source gpai --item-id 52946 --dry-run
```

### Agent 调用

```python
import sys; sys.path.insert(0, ".")
from skills.promo_image.scripts.compose import run  # 海报: 读 data.script 合成
# 话术由 script-writer 生成后, 再调 promo-image 出海报
```

## 数据契约

- 输入: 房源在 DB(`data.property_info` + 顶层价格列),话术素材库 `assets/短视频宣传话术.csv`
- 输出: DB `data.script` = 8 角度完整口播稿(`【角度】文案` 换行拼接)
- 不含海报/图片信息(那是 promo-image 的职责)

## 生成逻辑

- **主体是纯规则**(`fill_templates`): 每角度按优先级收集候选行,按 `item_id` 种子稳定随机:
  1) 全填行(所有占位符可填)→ 随机取一
  2) 宽松行(过半可填)→ 未填占位符所在**整段按标点切段删除** → 随机取一
  3) 固定兜底行 → 随机取一
  CSV「宽松填充」列 `否` = 断言行只允许全填;无折扣(起拍=评估价)跳过「10折/立省≤0」句式
- **源/断言准入(备注为声明式条件, 规则判定, `_row_allowed`)**: 备注含「仅 ali」→ 要求 source=ali 且至少一项 POI 距离非空; 备注含「步行范围」→ 要求宣称类别(地铁/学校/医院/公园)距离**全部存在且 ≤1200 米**(有 POI 不等于步行范围, 医院 2400 米照拒)
- **话术多样性靠离线补库**: 向 `assets/短视频宣传话术.csv` 追加候选行即可,无需改代码
- **LLM 润色是可选项**(`--llm`, `llm_enhance.py`): 默认关闭,显式开启才调通义千问润色全部角度。把房源事实+规则稿+素材库(子主题/备注)给 LLM,要求"改措辞不改事实";产出经校验(8 角度齐全/无占位符/数字不越界),失败自动重试 3 次后回退规则稿
- **备注列语义**: 记录派生公式/源限制/断言限制,供维护者阅读与源准入判断;派生值由代码计算、规则强制,无需 LLM 复查
- 生成顺序: 先 script-writer 出 `data.script`,再 promo-image 读稿合成海报,两层职责分离

## 字段提取兼容键

见 `FIELD_KEYS`(compose 同源): 建筑面积优先 `建筑面积_合计`;金额统一万元;POI 距离归一为纯米数;超 100 万㎡ / 单价<0.005 置空。

## 注意事项

- LLM 是可选项,**默认不开启**(`--llm` 显式开启);不配置 AliAPIKey 时自动跳过并提示
- `data.script` 是 promo-image 海报的内容源;改话术模板/清洗规则后需 `--force` 重生成
