"""FastAPI 应用入口：路由注册、静态文件、模板、中间件。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware

from app.web.api import api_router
from app.web.config import get_settings


settings = get_settings()
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    yield
    # 关闭时执行


app = FastAPI(
    title="法拍房短视频智能体系统 - Web 仪表盘",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# API 路由
app.include_router(api_router)


# ─── 前端页面路由（服务端渲染） ───

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.get("/listings", response_class=HTMLResponse)
async def listings_page(request: Request):
    return templates.TemplateResponse(request, "listings.html")


@app.get("/listings/{listing_id}", response_class=HTMLResponse)
async def listing_detail_page(request: Request, listing_id: int):
    return templates.TemplateResponse(request, "detail.html", {"listing_id": listing_id})


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html")


@app.get("/materials", response_class=HTMLResponse)
async def materials_page(request: Request):
    return templates.TemplateResponse(request, "materials.html")


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request):
    return templates.TemplateResponse(request, "skills.html")


@app.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    return templates.TemplateResponse(request, "pipeline.html")


# 健康检查
@app.get("/health")
async def health():
    return {"status": "ok"}