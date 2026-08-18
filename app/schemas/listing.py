"""法拍房源爬虫数据 DTO(跨技能传输结构)。

统一结构: 公拍网(gpai)/阿里资产(ali) 共用 `Auction*` 类,`source` 区分来源。
字段与 docs/初步信息.txt 及实际页面结构保持一致,货币统一为元。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class AuctionListing:
    """列表页单条房源(结构化字段,货币统一为元)。"""

    # 数据来源: gpai=公拍网 / ali=阿里资产
    source: str = "gpai"
    title: str = ""
    url: str = ""
    item_id: str = ""
    # 分类: ali=住宅/商业/工业/其他;gpai=房产
    category: Optional[str] = None
    start_price: float = 0.0
    # 参考价(可能是评估价/市场价等,类型见 ref_price_type),统一为元
    ref_price: Optional[float] = None
    # 参考价标签(如 评估价/市场价/参考价),取自页面标签
    ref_price_type: str = ""
    # 开始时间(即将开始标的必有)
    start_time: Optional[str] = None
    # 采集时间(ISO 格式,入库/去重/审计用)
    crawled_at: Optional[str] = None
    status: str = ""
    # 页面文本原始值,便于人工核对
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuctionDetail:
    """详情页/列表缩略图数据。"""

    source: str = "gpai"
    item_id: str = ""
    images: List[str] = field(default_factory=list)
    # 与 images 一一对应的本地文件名;未成功下载为 None(断点续传用)
    image_files: List[Optional[str]] = field(default_factory=list)
    # 标的物描述(拍卖标的描述)
    description: str = ""
    # 标的物属性(无拍卖标的描述时,优先抓取此区块的全部信息;仅阿里资产)
    property_info: dict = field(default_factory=dict)
    # 周围情况(标的物位置下方的高德地图iframe数据,仅阿里资产)
    # 交通: {sub_tag: [{name, desc, distance}]}
    transportation: dict = field(default_factory=dict)
    # 教育: {sub_tag: [{name, desc, distance}]}
    education: dict = field(default_factory=dict)
    # 购物: {sub_tag: [{name, desc, distance}]}
    shopping: dict = field(default_factory=dict)
    # 医疗: {sub_tag: [{name, desc, distance}]}
    medical: dict = field(default_factory=dict)
    # 公园: [{name, desc, distance}]
    parks: List[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuctionCrawlResult:
    """一次爬取任务的完整结果(跨来源通用)。

    category: 仅阿里资产使用(住宅/商业/工业/其他);公拍网为 None。
    """

    source: str = "gpai"
    category: Optional[str] = None
    # 页面声明总数(公拍=条数;阿里=总页数)
    total: int = 0
    listings: List[AuctionListing] = field(default_factory=list)
    details: List[AuctionDetail] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "category": self.category,
            "total": self.total,
            "listings": [l.to_dict() for l in self.listings],
            "details": [d.to_dict() for d in self.details],
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# 公拍网兼容别名(Gpai* = Auction*,零引用改动)
# ---------------------------------------------------------------------------
GpaiListing = AuctionListing
GpaiDetail = AuctionDetail


@dataclass
class GpaiCrawlResult(AuctionCrawlResult):
    """公拍网专用结果(带 restate 历史字段)。与旧测试/代码兼容。"""

    restate: int = 1

    def to_dict(self) -> dict:
        return {
            "restate": self.restate,
            "total": self.total,
            "listings": [l.to_dict() for l in self.listings],
            "details": [d.to_dict() for d in self.details],
            "errors": self.errors,
        }