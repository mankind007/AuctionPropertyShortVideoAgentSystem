"""API 路由聚合。"""
from __future__ import annotations

from fastapi import APIRouter

from app.web.api import auth, listings, tasks, materials, pipeline, skills


api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(listings.router)
api_router.include_router(tasks.router)
api_router.include_router(materials.router)
api_router.include_router(pipeline.router)
api_router.include_router(skills.router)