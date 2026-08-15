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