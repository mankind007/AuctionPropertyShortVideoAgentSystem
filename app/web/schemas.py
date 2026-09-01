"""Web API Pydantic 模型：请求/响应结构。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, List

from pydantic import BaseModel, Field, EmailStr, ConfigDict


# ─── 认证 ───
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: Optional[EmailStr] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(UserBase):
    id: int
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── 房源 ───
class ListingQuery(BaseModel):
    source: Optional[str] = None
    status: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    start_time_from: Optional[datetime] = None
    start_time_to: Optional[datetime] = None
    keyword: Optional[str] = None
    sort_by: Optional[str] = None  # created_at / start_time / start_price
    sort_order: Optional[str] = None  # asc / desc


class ListingBase(BaseModel):
    source: str
    item_id: str
    title: Optional[str] = None
    category: Optional[str] = None
    start_price: float = 0
    ref_price: Optional[float] = None
    ref_price_type: Optional[str] = None
    start_time: Optional[datetime] = None
    status: Optional[str] = None
    crawled_at: Optional[datetime] = None


class ListingOut(ListingBase):
    id: int
    has_script: bool = False
    has_images: bool = False
    has_posters: bool = False
    has_videos: bool = False
    has_voice: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ListingDetail(ListingOut):
    """详情：含完整 data 字段。"""
    data: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class PaginatedListings(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ListingOut]


# ─── 任务 ───
class TaskType(str):
    CRAWL_GPAI = "crawl_gpai"
    CRAWL_ALI = "crawl_ali"
    CRAWL_ALL = "crawl_all"
    GENERATE_SCRIPT = "generate_script"
    GENERATE_TTS = "generate_tts"
    GENERATE_POSTER = "generate_poster"
    GENERATE_VIDEO = "generate_video"
    MUX_VIDEO = "mux_video"
    FULL_PIPELINE = "full_pipeline"


class TaskStatus(str):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)


class TaskProgress(BaseModel):
    progress: int = 0
    current_step: str = ""
    error_message: Optional[str] = None


class TaskOut(BaseModel):
    id: int
    owner_id: int
    type: str
    status: str
    params: dict
    result: dict
    progress: int
    current_step: str
    error_message: Optional[str]
    max_retries: int
    retry_count: int
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class PaginatedTasks(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[TaskOut]


# ─── 素材 ───
class MaterialType(str):
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"


class MaterialBase(BaseModel):
    name: str
    type: str
    tags: List[str] = Field(default_factory=list)
    is_public: bool = False


class MaterialCreate(MaterialBase):
    pass


class MaterialOut(MaterialBase):
    id: int
    file_path: str
    file_size: int
    mime_type: Optional[str] = None
    meta: dict
    uploader_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaterialDistribute(BaseModel):
    user_ids: List[int]
    permission: str = "view"  # view, edit, admin


class PaginatedMaterials(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[MaterialOut]


# ─── 管线/技能 ───
class PipelineStage(BaseModel):
    stage: str
    gpai: int
    ali: int


class PipelineStatus(BaseModel):
    total_listings: int
    stages: List[PipelineStage]


class SkillInfo(BaseModel):
    name: str
    description: str


class SkillRunRequest(BaseModel):
    params: dict = Field(default_factory=dict)


# ─── 资产文件（assets/ 目录扫描） ───
class AssetFile(BaseModel):
    id: int  # 负数 ID，避免与 materials 表冲突
    name: str
    type: str  # image / audio / video / document
    source: str  # "gpai" / "ali"
    listing_id: str
    stage: str  # imgs / posters / videos / voice
    file_path: str  # 相对于 assets/ 的路径
    file_size: int
    mime_type: str
    tags: List[str] = Field(default_factory=list)
    is_public: bool = True
    meta: dict = Field(default_factory=dict)
    uploader_id: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


# ─── 单房源工作流 ───
class WorkflowPreview(BaseModel):
    url: str
    label: str
    type: str  # image / video / audio / text
    file: str  # 文件名
    content: Optional[str] = None  # text 类型时携带全文


class WorkflowStage(BaseModel):
    key: str  # script / poster / voice / video / mux
    name: str
    status: str  # done / pending / running / failed
    progress: int = 0
    current_step: str = ""
    can_run: bool = True
    task_id: Optional[int] = None
    error_message: Optional[str] = None
    previews: List[WorkflowPreview] = Field(default_factory=list)


class ListingWorkflow(BaseModel):
    listing_id: int
    source: str
    item_id: str
    title: Optional[str] = None
    voiceover_enabled: bool = True
    stages: List[WorkflowStage] = Field(default_factory=list)


class WorkflowRunRequest(BaseModel):
    stage: str  # script / poster / voice / video / mux