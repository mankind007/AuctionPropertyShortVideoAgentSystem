# 公拍网 XPath 规则(实测基准)

来源: `docs/初步信息.txt` 提供初版,以下为 `2026-08-12` 实测确认/修正后的版本。

## 列表页

URL: `https://s.gpai.net/sf/Search.do?at=376&restate=1`(固定"即将开始")

| 数据 | XPath | 备注 |
|------|-------|------|
| 总数 | `//div[@class='filtbar-l fl']/span/label` | 页面声明总条数 |
| 房源项 | `(//ul[contains(@class,'main-col-list')])[1]//div[contains(@class,'list-item')]` | **仅第一个** main-col-list;页面另有第二个同名推荐区块 |
| 名称 | `.//div[contains(@class,'item-tit')]/a` | 内联文本即标题,同元素取 `href` |
| 链接 | 名称元素 `.get_attribute('href')` | 片段如 `//www.gpai.net/sf/item2.do?Web_Item_ID=52886`,需加 `https:` |
| 数据行 | `.//div[@class='gpai-infos']/p` | 逐 `<p>` 取文本,按标签关键词分发 |
| 起拍价 | 数据行含 起拍价/变卖价/最新价 | 正则解析数字+单位(任意 十百千万亿 组合)归一为元 |
| 参考价 | 数值取整行 `<p>` innerText;标签取 `p[4]/span[1]`(去 `：`) | 标签不固定(评估价/市场价/参考价...),存 `ref_price_type`;数值可能为 百元/千元/万元/十万元/百万元/亿元/十亿元 等,须归一为元 |
| 时间 | 数据行标签含 开始时间 | 提取日期时间串 → `start_time`;另有 `crawled_at` 采集时间戳(每次抓取自动写入) |

### 与 docs 初版差异(实测修正)

- 名称/链接不在 `//div[@class='list-item']/div/a`(那是封面 `<a>`,无文本),实际在 `item-tit` 内
- **页面有 2 个 `ul.main-col-list`**:第一个为真实列表,第二个是资产交易推荐区块,必须用 `(//ul...)[1]` 限定
- 价格标签因阶段而异: `起拍价`(一拍/二拍) / `变卖价`(变卖)(仅采集"即将开始"批次,无"最新价"行情)
- 时间标签: 固定为 `开始时间`(restate=1),提取到 `start_time`;`crawled_at` 为采集时间戳
- 参考价(即当年文档的"评估价")标签不固定: `评估价` / `市场价` 等;标签取自 `p[4]/span[1]`(去 `：`),值取 `p[4]` 整行(单位可能在 span 外)
- 参考价单位不固定(百元/千元/万元/十万元/百万元/亿元/十亿元...),须正则归一为元,解析函数已支持任意 `十百千万亿` 组合
- 每页条数: docs 记录最多 16,实测第一页为 20(页面改版),用 `PAGE_CAP=20` 做单页校验

## 分页与反爬(实测)

- 分页链接: `.page-nav a[href*="Page=N"]`,当前页 `Page` 为 1 但 URL 带 `Page=1` 且 class=`on`(从 0 计)
- **点击翻页触发滑块验证**(Slide jigsaw to complete verification),直接改 URL 访问 `Page>=1` 返回空页
- 结论: 目前仅能稳定爬第 1 页;批量翻页需人工/打码

## 详情页

URL: `https://www.gpai.net/sf/item2.do?Web_Item_ID={id}`

| 数据 | XPath | 备注 |
|------|-------|------|
| 图片 | `//ul[@class='small-pics clearfix']/li/a` | 元素 `.getAttribute('rev')` 为图片片段,需加 `https:` 前缀 |

## 反爬注意

- 不登录可访问列表与详情(仅第 1 页;翻页触发滑块)
- 建议请求间隔 ≥0.3s;必要时设置真实 UA(代码已内置)
