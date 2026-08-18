---
name: gpai-crawler
description: 爬取公拍网司法拍卖房产列表与详情(图片/描述/标的物介绍 property_info 面积等,固定"即将开始"批次)。何时使用: 需要获取法拍房源(名称/起拍价/参考价/开始时间/图片链接/标的物属性/面积)时,触发关键词包括"公拍网"、"gpai"、"法拍房"、"爬取房源"、"拍卖列表"、"房源采集"、"Web_Item_ID"。
---

# gpai-crawler 公拍网房产爬虫

抓取公拍网房产拍卖数据,不登录即可访问。

## 触发场景

- 用户要求采集公拍网法拍房源数据
- 需要某批次房源的列表信息(名称、链接、起拍价、参考价、开始时间)
- 需要某个房源详情页的图片链接

## 使用方式

### 人工直接运行(CLI)

```bash
# 默认采集"即将开始"(restate=1,自动全部页)
python skills/gpai-crawler/scripts/crawler.py

# 带详情图片链接 + 保存 JSON
python skills/gpai-crawler/scripts/crawler.py --with-images --save-json assets/gpai_result.json

# 抓取并下载详情页图片到 assets/{listing_id}/imgs/
python skills/gpai-crawler/scripts/crawler.py --download

# 只爬前 2 页
python skills/gpai-crawler/scripts/crawler.py --pages=2
```

### Agent 编程调用

```python
import sys; sys.path.insert(0, ".")
from skills.gpai-crawler.scripts.crawler import fetch_listings, fetch_detail, enrich_with_images_download
from pathlib import Path

result = fetch_listings()                     # GpaiCrawlResult,自动爬全部页(仅即将开始)
enrich_with_images_download(result, Path("assets"))  # 抓取链接并下载图片到 assets/{id}/imgs/
result.to_dict()                              # 序列化为 dict
```

### 详情采集接口(职责分离)

详情采集已拆为**单一职责接口**(均接收已打开的 `page`) + 编排:

| 接口 | 作用 |
|------|------|
| `_open_detail_page(url, page)` | 打开子页并注入隐身脚本,等待主图可用 |
| `_fetch_images(page)` | 仅抓主图链接(rev 属性,补 `https:` 前缀) |
| `_fetch_description(page)` | 仅抓标的物描述(`//div[@class='d-article']`) |
| `_fetch_property_info(page)` | 抓「标的物介绍」tab 调查情况表/审批表(`d-article2`),结构化表格拍扁为扁平 dict(见下) |
| `fetch_detail(url)` | 组合编排: 图片 + 描述 + 属性,返回 `GpaiDetail`(同步封装) |

## 标的物介绍 property_info(重要)

- **面积/用途等结构化字段只在「标的物介绍」tab**(`div.d-article.d-article2`)的调查情况表/审批表里,竞买公告(`d-article`)通常没有 → `_fetch_description` 抓不到面积是正常现象
- `_fetch_property_info(page)`: 遍历 `d-article2` 块,排除「竞买公告/竞买须知/重要提示/竞买记录」,命中「调查情况表/审批表/具体描述/面积」的块取 innerHTML + innerText
- 拍扁规则(`utils/description.extract_gpai_property_info`):
  - 两列 label/value: 键=左格,值=右格(值列 colspan 多格合一)
  - rowspan 分组(组名列跨多行): 组名丢弃,保留 子键/值;组+单值无子键 → 保留 `{组名: 值}`
  - 多列多行权证表(多套房产): 行首标识列做前缀键,如 `建筑面积_779弄53号301室`,互不覆盖
  - 单格说明行(如 colspan 铺满的备注)跳过
- **面积优先级**: 结构化表内键(建筑总面积/建筑面积/房屋建筑面积/套内面积/总面积)→ 竞买公告段落 regex → 标的物介绍段落 regex;结果写入 `out[面积键]`
- 空页面返回 `{}`,不进 `data.property_info`(写库时 non-empty 才覆盖)

## 单页上限与防爬错

- 列表页**第一个** `ul.main-col-list` 为真实列表,页面还有第二个同名推荐区块(资产交易)必须排除
- 单页条目数受 `PAGE_CAP`(默认 20)约束;超过上限即判定爬错(混入推荐区块),写入 `errors` 提醒人工核对
- 实测第一页 20 条(docs 记录的 16 条为旧版页面)

## 翻页与反爬(重要)

- 使用 URL 翻页(`?Page=N`),避免点击触发检测
- **反检测措施**:
  - `addInitScript` 注入 JS 补丁:patch `navigator.webdriver`、`navigator.plugins`、`window.chrome`、WebGL 等 L1-L4 检测点
  - 翻页延时:每页 0.5-2.5s,每 5 页额外等待 3-4s,模拟人类行为
- 每次请求间隔默认 0.3s,建议不要调低

## 时间字段(start_time / crawled_at)

- 仅采集"即将开始"(restate=1)的标的,时间字段固定为 `start_time`(开始时间)
- `start_time`: 页面 `开始时间` 行的日期时间串,格式 `YYYY-M-D HH:MM:SS`(提取函数 `_extract_time` 仅取时间串)
- `crawled_at`: 采集时间戳(ISO 格式,本地时区),每条房源抓取时写入,用于入库排重/审计
- 不再区分结束时间: 方案B确定只采集即将开始的房源,`end_time` 字段已删除

## 数据契约

- 输入: 无(固定采集"即将开始" restate=1);`pages`: 0=自动全部页(默认), >0=最多 N 页
- 输出: `GpaiCrawlResult`(`app/schemas/listing.py`)
  - `total` 页面声明总数
  - `listings[]` 房源列表(字段见 `app/schemas/listing.py`)
  - `details[]` 详情图片:
    - `images` 为 `https:` 完整链接
    - `description` 标的物描述(按 docs/初步信息 + 需求.txt 提取: 首选「第N条」(含拍卖标的标记)到「第N+1条」前的文字,换行转空格; 无此分节则取「拍卖标的…」到最近「X、」之间; 无法分段回退整段; 公共解析 `utils/description.extract_auction_description`)
    - `property_info` 标的物介绍(dict, `utils/description.extract_gpai_property_info`: 「标的物介绍」tab 调查情况表/审批表拍扁,含 建筑面积/用途/产权证号 等;无表返回 `{}`)
  - `errors[]` 解析失败条目

## 参考价(ref_price)说明

- **参考价 ≠ 评估价**:页面标题不定,可能是**评估价、市场价**或其他参考价格,因标的类型而异,故统一命名为"参考价"
- **取值规则**:
  - 价格数值取整行 `<p>` innerText(如 `市场价：496,200 元`),不单独取 `span[2]`,因为市场价行的单位"元"在 span 外
  - 价格标签取 `p[4]/span[1]` 文本去掉冒号(如 `评估价` / `市场价`),存入 `ref_price_type`
  - 若某行解析不出数值则跳过,`ref_price=None`
- **语义提醒**:下游使用前必须结合 `ref_price_type` 判断价格性质(评估价可作价值参考,市场价亦同理,均为参考性质,非成交价)

## 价格单位换算(重要)

所有价格统一换算为**元**,支持任意中文单位组合:

| 单位 | 乘数 | 示例 | 结果(元) |
|------|------|------|----------|
| 元 | ×1 | `750000元` | 750000 |
| 百元 | ×100 | `800百元` | 80000 |
| 千元 | ×1000 | `500千元` | 500000 |
| 万元 | ×10⁴ | `94.43万元` | 944300 |
| 十万元 | ×10⁵ | `3十万元` | 300000 |
| 百万元 | ×10⁶ | `2.5百万元` | 2500000 |
| 亿元 | ×10⁸ | `9.09亿元` | 909000000 |
| 十亿元 | ×10⁹ | `1.5十亿元` | 1500000000 |

**实现原理**(`_to_int_price`):先正则提取数字(容忍千分位逗号 `,`),再把数字后单位字符串中出现的 `十/百/千/万/亿` 汉字各自相乘(亿=1e8, 万=1e4, 千=1e3, 百=1e2, 十=1e1)。因此**单位不必穷举**,任意组合(如 `百亿元`、`十亿`、`万亿`)都能正确换算。

**处理注意事项**:
- 数字可能带千分位逗号(`1,056,669`),已统一去除
- 数字与单位之间可能有空格(`400,392 元`),已容忍
- 可能有小数(`84.40`、`431,998.28`),支持 `\d+\.\d+`
- 起拍价(一拍/二拍)、变卖价(变卖)均归入 `start_price`(仅采集"即将开始"批次,无"最新价"行情)
- 解析失败返回 `None`,不会让整条房源失败

## 注意事项

- 每次翻页/请求间留间隔(`delay`,默认 0.3s),避免触发风控
- 链接片段(`//...` 或 `http...`)需加 `https:` 前缀
- 页面结构若变化,参考 `references/xpath_rules.md` 中的基准 XPath
- 失败条目不中断整体流程,记录到 `errors`

## 入库(可选)

- `--db`: 结果 upsert 进 PostgreSQL `listings` 表(`UNIQUE(source,item_id)` 去重,与阿里共用一表)
- 先建表: `python scripts/init_db.py`(需 `.env` 的 `DATABASE_URL` 已填、库已建)
- 表结构与 ORM 见 `db/listing.py`、`db/db.py`;DB 不可用时自动跳过入库,不影响采集
- **data.images 新结构**: `[{url, file|null}]`;`data.raw` 保留起拍/评估/开始时间审计文本;不存 `assets_dir`(可推导 `assets/gpai/{item_id}/`)
- `data.property_info`(标的物介绍扁平 dict)与 `data.description` 由详情接口写入,非空才覆盖旧值
- `--skip-complete`: 查 DB 已采图清单,本地图齐全跳过、缺文件离线补下(不开浏览器)
- **历史补填**: 描述/属性不进断点续传,存量缺字段用 `python scripts/fill_description_location.py --source gpai` 补齐

## 多源并行采集

- `python scripts/crawl_all.py --pages 1` 以子进程并行启动公拍网 + 阿里两套爬虫,各持独立浏览器
- 参数: `--download`(采图)、`--db`(入库)、`--skip-complete`(断点续传)、`--ali-pages/--gpai-pages` 独立控制页数、`--skip-gpai/--skip-ali` 只跑单源
