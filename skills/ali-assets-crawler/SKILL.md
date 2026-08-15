---
name: ali-assets-crawler
description: 爬取阿里资产(淘宝司法拍卖 sf.taobao.com)房产列表与缩略图(仅"即将开始")。何时使用: 需要获取阿里资产法拍房源(名称/链接/起拍价/参考价/图片)时,触发关键词包括"阿里资产"、"淘宝法拍"、"sf.taobao.com"、"法拍房(阿里)"、"房源采集(阿里)"。
---

# ali-assets-crawler 阿里资产房产爬虫

抓取阿里资产司法拍卖(淘宝法拍)房产列表。⚠️ **该站强制登录**,首次须有头模式人工登录。

## 触发场景

- 用户要求采集阿里资产法拍房源数据(住宅/商业/工业/其他)
- 需要某分类房源的列表信息(名称、链接、起拍价、参考价、缩略图)
- 多分类批量采集(默认"住宅";可一次选多个)

## 使用方式

### 人工直接运行(CLI)

`--category` 可传一个或多个分类,默认 `住宅`。

```bash
# 第一次:有头模式,弹出窗口人工登录/滑条(登录态自动保存,之后复用)
python skills/ali-assets-crawler/scripts/crawler.py --category 住宅 --pages 2

# 已登录后:多个分类,每类至少 2 页(默认已是 2)
python skills/ali-assets-crawler/scripts/crawler.py --category 住宅 商业 工业 其他 --pages 2

# 爬全部页(0=全部页)
python skills/ali-assets-crawler/scripts/crawler.py --category 住宅 --pages 0

# 无头复用登录态(仅登录成功后)
python scripts/crawl_ali.py --category 住宅 --pages 2 --headless
```

### Agent 编程调用

```python
import sys; sys.path.insert(0, ".")
from skills.ali-assets-crawler.scripts.crawler import fetch_listings

r = fetch_listings("住宅", pages=2, headless=False)   # 首次 False(有头登录)
r.source, r.category                                   # "ali", "住宅"
r.total                                               # 声明总页数
r.listings                                            # 房源列表(AuctionListing)
r.details                                             # 缩略图(AuctionDetail)
r.to_dict()
```

## 登录态说明(重要)

- `sf.taobao.com` 无登录态会被重定向到 `login.taobao.com` 或触发滑块验证
- 首次运行时请用**有头模式**(默认),在弹出窗口完成扫码/登录;脚本检测到列表项后自动继续
- 登录态自动保存到:
  - profile: `assets/ali/chrome_profile/`
  - storage_state: `assets/ali/login_state.json`
- 之后可用 `--headless` 复用登录态;若被再次要求登录,重新有头登录一次即可

## 数据契约

- 输入: `category`(住宅/商业/工业/其他)、`pages`(默认 2,0=全部页)、`headless`(首次 False)
- 输出: `AuctionCrawlResult`(`src/schemas/listing.py`)
  - `source="ali"`, `category` 对应分类
  - `total` = 页面声明的**总页数**(与公拍网的总条数语义不同)
  - `listings[]` 房源(`AuctionListing`, `item_id` 取自 URL `id=` 或 `/item/`)
  - `details[]` 缩略图(`images` 为 `https://` 完整链接,已升级为 `_960x960` 高清)
  - `errors[]` 解析失败条目

## 字段说明

- **起拍价/参考价**: `span.value` 文本,去 `￥` + 中文单位(百/千/万/十万/百万/千万/亿)归一为元(`_to_int_price`)
- 参考价可能缺失 → `ref_price=None`;有值则 `ref_price_type="参考价"`
- `start_time` 预留,列表页当前结构不提供开始时间,保持 `None`
- 缩略图: `src` 加 `https://` 前缀,并把 `_80x80.jpg` 替换为 `_960x960.jpg`
- 单条 `li` 根节点: `//div[@class='sf-item-list']/ul[@class='sf-pai-item-list'][1]/li`;仅 URL `?&page=N` 翻页,总页数 `//em[@class='page-total']`

## 注意事项

- 分页很慢,每页间间隔 1.5s;避免并发翻页触发风控
- 页面结构若变化参考 `references/xpath_rules.md`
- 失败条目不中断整体流程,记录到 `errors`