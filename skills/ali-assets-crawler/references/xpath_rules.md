# 阿里资产(sf.taobao.com)XPath 规则

来源: `docs/初步信息.txt` 提供初版;以下标注 `(待实测)` 的需首次有头登录后现场核对。

## 列表页(即将开始)

URL 模板: `https://sf.taobao.com/list/{cat_id}__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1`

| 数据 | XPath | 备注 |
|------|-------|------|
| 总页数 | `//em[@class='page-total']` | 文本为总页数(非条数!) |
| 房源项 | `//div[@class='sf-item-list']/ul[@class='sf-pai-item-list'][1]/li` | **仅第一个** sf-pai-item-list |
| 标题 | `.//a/div[contains(concat(' ',@class,' '),' header-section')]/p[contains(@class,'title')]` | 类名 `header-section` 带尾空格,须 contains 匹配 |
| 链接 | `./a` 的 `href` | 需加 `https://` 前缀 |
| 起拍价 | `.//div[contains(@class,'info-section')]/p[contains(@class,'price-todo')]//span[contains(@class,'value')]` | 文本含 `￥`+单位,去头尾归一为元 |
| 参考价 | `.//div[contains(@class,'info-section')]/p[contains(@class,'price-assess')]//span[contains(@class,'value')]` | 可能有值(=参考价),也可能缺失 |
| 开始时间 | `.//div[contains(@class,'info-section')]/p[contains(@class,'time-todo')]//span[contains(@class,'value')]` | 文本如 `08月15日 10:00`,自动补当年;12-31 23:55 后打印临界提醒 |
| 缩略图 | `.//li[contains(@class,'pm-thumb')]//img` 的 `src` | 加 `https://`,`_80x80.jpg→_960x960.jpg` |

### 分类 ID

| 分类 | cat_id | 说明 |
|------|--------|------|
| 住宅 | `50025969` | 即将开始 `50025969__1` |
| 商业 | `200782003` | 即将开始 `200782003__1` |
| 工业 | `200788003` | 即将开始 `200788003__1` |
| 其他 | `200798003` | 即将开始 `200798003__1` |

## 翻页

- 链接通过 `&page={N}` 控制页数(不登录也可?待实测确认是否被滑块/登录拦截)
- 每页间隔 1.5s,避免触发风控

## 登录

- **该站强制登录**,无登录态会重定向 `login.taobao.com` 或出现滑块验证
- 首次有头(person)登录一次,持久化 profile 与 storage_state 后复用

## 图片处理

- 列表缩略图 `src` 形如 `//img.alicdn.com/..._80x80.jpg` → `https://img.alicdn.com/..._960x960.jpg`
- 高清图 `_960x960` 可直接用于成片

## 详情页(标的物描述与周围情况)

### 标的物描述

| 数据 | XPath | 备注 |
|------|-------|------|
| 标的物描述 | `//div[@id='J_NoticeDetail']` | 拍卖标的描述文本 |

### 标的物位置与周围情况

| 数据 | XPath/选择器 | 备注 |
|------|-------|------|
| 标的物位置区块 | `//div[contains(@class,'item-address')]` | 滚动到此区域触发iframe加载 |
| 高德地图iframe | `gaode-map-pc` (URL包含) | iframe加载后可抓取周围情况 |

### 周围情况标签结构

周围情况在高德地图iframe内，包含5个主标签：

| 主标签 | 二级标签 | 数据结构 |
|--------|---------|---------|
| 交通 | 地铁、公交 | `{sub_tag: [{name, desc, distance}]}` |
| 教育 | 幼儿园、小学、中学 | `{sub_tag: [{name, desc, distance}]}` |
| 购物 | 购物中心、超市、农贸市场 | `{sub_tag: [{name, desc, distance}]}` |
| 医疗 | 综合医院、卫生服务站、其他医院、药店 | `{sub_tag: [{name, desc, distance}]}` |
| 公园 | 无子标签 | `[{name, desc, distance}]` |

### 标签DOM结构(实测)

- **主标签行容器**: `div.h-48px`(内含5个 `div.cursor-pointer > p`, 文本=交通/教育/购物/医疗/公园)
- **二级标签行容器**: `div.h-44px`(内含若干个 `p`, 文本=各二级标签)
- **激活主标签**: `<p>` 带 `activePoiName--` 类(同时带 `firstPoiName--`, 但这两个类只在激活时出现!)
- **激活二级标签**: `<p>` 带 `selectedChildPoiName--` 类(未激活的二级标签带 `childPoiName--`)

> ⚠️ 注意: `firstPoiName--`/`childPoiName--` 并非所有标签共有, 仅当前激活/未激活标签才有。
> 点击定位必须用容器选择器 `div.h-48px p`(主) / `div.h-44px p`(二级) + `has_text=标签名`,
> 不能用 `p[class*='firstPoiName--']` 这类(会漏掉未激活标签)。

### 切换验证(防误触/遮挡)

点击主/二级标签后, 等待随机1.5~2.5s, 再用激活类校验:
- 主标签: 检查 `p[class*='activePoiName--']` 文本 == 刚点击的标签
- 二级标签: 检查 `p[class*='selectedChildPoiName--']` 文本 == 刚点击的标签
- 不一致(=上次标签/未切换) → 额外等3s, 最多重试3次; 仍失败则跳过该标签

### 三种结果处理(二级标签)

- A. 切换失败(激活标签≠刚点击) → 等3s重试
- B. 切换成功且有数据 → 记录, 继续下一个
- C. 切换成功但无数据 → 等2s重新抓取确认, 仍无则继续下一个

### 抓取逻辑

1. 滚动到`//div[contains(@class,'item-address')]`触发iframe加载(仅首次, 切换标签不再滚动)
2. 等待gaode iframe出现(最多300秒), 找到后随机等0.5~1.5s
3. `page.set_default_timeout(10000)` 设frame隐式等待最大10s
4. 逐个切换5个主标签: 点击 `div.h-48px p`(has_text), 验证 `activePoiName--` 激活
5. 公园无二级标签, 直接抓取; 其余点击 `div.h-44px p`(has_text)切换, 验证 `selectedChildPoiName--` 激活
6. 每个二级标签抓取后按A/B/C三态处理
7. 如果详情页没有gaode iframe，返回空的poi数据

### 注意事项

- 公拍网没有周围情况数据
- 每个标签独立处理，无数据返回空列表/空字典
- 二级标签不一定有数据
- 购物中心等二级标签偶尔点击不生效(被遮挡/动画), 靠激活类校验+重试兜底