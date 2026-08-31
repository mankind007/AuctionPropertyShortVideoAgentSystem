"""Web API 契约测试。

验证所有端点存在、响应 schema 稳定、认证流程正确。
不做真实业务操作（DB 操作用内存 SQLite mock 或依赖已有数据）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保项目根在 sys.path
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ── Fixtures ──

@pytest.fixture(scope="module")
def client():
    """创建 TestClient（使用真实 app，不启动服务器）。"""
    from fastapi.testclient import TestClient
    from app.web.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client):
    """登录获取 token。"""
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin666"},
    )
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# ── 健康检查 ──

class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_docs(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


# ── 认证 ──

class TestAuth:
    def test_login_success(self, client):
        resp = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin666"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        resp = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_me_unauthenticated(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code in (401, 403)

    def test_me_authenticated(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert "id" in data

    def test_refresh_token(self, client, auth_headers):
        resp = client.post("/api/auth/refresh", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_token_via_query_param(self, client, auth_token):
        resp = client.get(f"/api/auth/me?token={auth_token}")
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_user_list_requires_admin(self, client, auth_headers):
        resp = client.get("/api/auth/users", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1


# ── 用户管理（admin） ──

class TestUserManagement:
    def test_create_user(self, client, auth_headers):
        resp = client.post(
            "/api/auth/users",
            headers=auth_headers,
            json={
                "username": "test_user_api",
                "password": "test123456",
                "email": "test@example.com",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "test_user_api"
        assert data["role"] == "user"
        assert data["is_active"] is True
        return data["id"]

    def test_update_user(self, client, auth_headers):
        # 先获取用户列表
        users = client.get("/api/auth/users", headers=auth_headers).json()
        test_user = next((u for u in users if u["username"] == "test_user_api"), None)
        if not test_user:
            pytest.skip("test_user_api 未创建")
        resp = client.patch(
            f"/api/auth/users/{test_user['id']}",
            headers=auth_headers,
            json={"email": "new@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "new@example.com"

    def test_delete_user(self, client, auth_headers):
        users = client.get("/api/auth/users", headers=auth_headers).json()
        test_user = next((u for u in users if u["username"] == "test_user_api"), None)
        if not test_user:
            pytest.skip("test_user_api 未创建")
        resp = client.delete(
            f"/api/auth/users/{test_user['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 204


# ── 房源 ──

class TestListings:
    def test_list_listings(self, client):
        resp = client.get("/api/listings")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)

    def test_listing_item_schema(self, client):
        resp = client.get("/api/listings?page_size=1")
        data = resp.json()
        if not data["items"]:
            pytest.skip("无房源数据")
        item = data["items"][0]
        required_fields = [
            "id", "source", "item_id", "start_price", "status",
            "has_script", "has_images", "has_posters", "has_videos", "has_voice",
            "created_at", "updated_at",
        ]
        for f in required_fields:
            assert f in item, f"缺少字段: {f}"

    def test_listings_filter_source(self, client):
        resp = client.get("/api/listings?source=gpai&page_size=5")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["source"] == "gpai"

    def test_listings_filter_status(self, client):
        resp = client.get("/api/listings?status=即将开始&page_size=5")
        assert resp.status_code == 200

    def test_listings_filter_keyword(self, client):
        resp = client.get("/api/listings?keyword=test&page_size=5")
        assert resp.status_code == 200

    def test_listing_detail(self, client):
        resp = client.get("/api/listings?page_size=1")
        items = resp.json()["items"]
        if not items:
            pytest.skip("无房源数据")
        listing_id = items[0]["id"]
        detail_resp = client.get(f"/api/listings/{listing_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert "data" in detail
        assert detail["id"] == listing_id

    def test_listing_images_endpoint(self, client):
        resp = client.get("/api/listings?page_size=1")
        items = resp.json()["items"]
        if not items:
            pytest.skip("无房源数据")
        listing_id = items[0]["id"]
        img_resp = client.get(f"/api/listings/{listing_id}/images")
        assert img_resp.status_code == 200
        assert "images" in img_resp.json()

    def test_listing_posters_endpoint(self, client):
        resp = client.get("/api/listings?page_size=1")
        items = resp.json()["items"]
        if not items:
            pytest.skip("无房源数据")
        listing_id = items[0]["id"]
        r = client.get(f"/api/listings/{listing_id}/posters")
        assert r.status_code == 200
        assert "posters" in r.json()

    def test_listing_videos_endpoint(self, client):
        resp = client.get("/api/listings?page_size=1")
        items = resp.json()["items"]
        if not items:
            pytest.skip("无房源数据")
        listing_id = items[0]["id"]
        r = client.get(f"/api/listings/{listing_id}/videos")
        assert r.status_code == 200
        assert "videos" in r.json()

    def test_listing_voice_endpoint(self, client):
        resp = client.get("/api/listings?page_size=1")
        items = resp.json()["items"]
        if not items:
            pytest.skip("无房源数据")
        listing_id = items[0]["id"]
        r = client.get(f"/api/listings/{listing_id}/voice")
        assert r.status_code == 200
        assert "voice" in r.json()

    def test_export_csv(self, client):
        resp = client.get("/api/listings/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")


# ── 任务 ──

class TestTasks:
    def test_list_tasks(self, client, auth_headers):
        resp = client.get("/api/tasks", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_task_item_schema(self, client, auth_headers):
        resp = client.get("/api/tasks?page_size=1", headers=auth_headers)
        data = resp.json()
        if not data["items"]:
            pytest.skip("无任务数据")
        item = data["items"][0]
        required_fields = [
            "id", "owner_id", "type", "status", "params", "result",
            "progress", "current_step", "max_retries", "retry_count",
            "created_at",
        ]
        for f in required_fields:
            assert f in item, f"缺少字段: {f}"

    def test_task_status_filter(self, client, auth_headers):
        resp = client.get("/api/tasks?status=pending", headers=auth_headers)
        assert resp.status_code == 200

    def test_task_type_filter(self, client, auth_headers):
        resp = client.get("/api/tasks?type=crawl_gpai", headers=auth_headers)
        assert resp.status_code == 200

    def test_create_task(self, client, auth_headers):
        resp = client.post(
            "/api/tasks",
            headers=auth_headers,
            json={"type": "crawl_gpai", "params": {"pages": 1, "db": False}},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "crawl_gpai"
        assert data["status"] in ("pending", "running")
        assert "id" in data
        return data["id"]

    def test_get_task(self, client, auth_headers):
        # 创建一个任务来查询
        create_resp = client.post(
            "/api/tasks",
            headers=auth_headers,
            json={"type": "crawl_gpai", "params": {"pages": 1, "db": False}},
        )
        if create_resp.status_code != 201:
            pytest.skip("无法创建任务")
        task_id = create_resp.json()["id"]
        resp = client.get(f"/api/tasks/{task_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    def test_task_progress(self, client, auth_headers):
        create_resp = client.post(
            "/api/tasks",
            headers=auth_headers,
            json={"type": "crawl_gpai", "params": {"pages": 1, "db": False}},
        )
        if create_resp.status_code != 201:
            pytest.skip("无法创建任务")
        task_id = create_resp.json()["id"]
        resp = client.get(f"/api/tasks/{task_id}/progress", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "progress" in data
        assert "current_step" in data

    def test_cancel_task(self, client, auth_headers):
        # 创建一个可能正在运行的任务
        create_resp = client.post(
            "/api/tasks",
            headers=auth_headers,
            json={"type": "crawl_gpai", "params": {"pages": 1, "db": False}},
        )
        if create_resp.status_code != 201:
            pytest.skip("无法创建任务")
        task_id = create_resp.json()["id"]
        resp = client.delete(f"/api/tasks/{task_id}", headers=auth_headers)
        # 可能是 204（成功取消）或 400（已结束）
        assert resp.status_code in (204, 400)

    def test_retry_task(self, client, auth_headers):
        # 重试仅对失败任务有效，创建后直接重试（如果还没结束会 400）
        create_resp = client.post(
            "/api/tasks",
            headers=auth_headers,
            json={"type": "crawl_gpai", "params": {"pages": 1, "db": False}},
        )
        if create_resp.status_code != 201:
            pytest.skip("无法创建任务")
        task_id = create_resp.json()["id"]
        resp = client.post(f"/api/tasks/{task_id}/retry", headers=auth_headers)
        # 可能是 200（重试成功）或 400（非失败状态）
        assert resp.status_code in (200, 400)

    def test_tasks_unauthenticated(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code in (401, 403)


# ── 素材 ──

class TestMaterials:
    def test_list_materials(self, client, auth_headers):
        resp = client.get("/api/materials", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_material_item_schema(self, client, auth_headers):
        resp = client.get("/api/materials?page_size=1", headers=auth_headers)
        data = resp.json()
        if not data["items"]:
            pytest.skip("无素材数据")
        item = data["items"][0]
        required_fields = [
            "id", "name", "type", "file_path", "file_size",
            "uploader_id", "is_public", "tags", "created_at",
        ]
        for f in required_fields:
            assert f in item, f"缺少字段: {f}"

    def test_material_type_filter(self, client, auth_headers):
        resp = client.get("/api/materials?type=image", headers=auth_headers)
        assert resp.status_code == 200

    def test_materials_unauthenticated(self, client):
        resp = client.get("/api/materials")
        assert resp.status_code in (401, 403)


# ── 管线 ──

class TestPipeline:
    def test_pipeline_status(self, client, auth_headers):
        resp = client.get("/api/pipeline", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_listings" in data
        assert "stages" in data
        assert isinstance(data["stages"], list)

    def test_pipeline_stages_schema(self, client, auth_headers):
        resp = client.get("/api/pipeline", headers=auth_headers)
        stages = resp.json()["stages"]
        for s in stages:
            assert "stage" in s
            assert "gpai" in s
            assert "ali" in s

    def test_pipeline_unauthenticated(self, client):
        resp = client.get("/api/pipeline")
        assert resp.status_code in (401, 403)


# ── 技能 ──

class TestSkills:
    def test_list_skills(self, client, auth_headers):
        resp = client.get("/api/skills", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_skill_schema(self, client, auth_headers):
        resp = client.get("/api/skills", headers=auth_headers)
        skills = resp.json()
        for s in skills:
            assert "name" in s
            assert "description" in s

    def test_skills_unauthenticated(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code in (401, 403)


# ── 页面路由 ──

class TestPageRoutes:
    def test_dashboard(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_login_page(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_listings_page(self, client):
        resp = client.get("/listings")
        assert resp.status_code == 200

    def test_tasks_page(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200

    def test_materials_page(self, client):
        resp = client.get("/materials")
        assert resp.status_code == 200

    def test_skills_page(self, client):
        resp = client.get("/skills")
        assert resp.status_code == 200

    def test_pipeline_page(self, client):
        resp = client.get("/pipeline")
        assert resp.status_code == 200
