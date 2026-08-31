"""单房源工作流契约测试。

验证 GET /api/listings/{id}/workflow 与 POST /api/listings/{id}/workflow/run
的结构与行为。依赖已有 DB 数据（与 test_web_api.py 一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.web.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_headers(client):
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin666"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _first_listing_id(client):
    resp = client.get("/api/listings?page_size=1")
    items = resp.json()["items"]
    if not items:
        pytest.skip("无房源数据")
    return items[0]["id"]


class TestWorkflowStatus:
    def test_workflow_requires_auth(self, client):
        lid = _first_listing_id(client)
        resp = client.get(f"/api/listings/{lid}/workflow")
        assert resp.status_code in (401, 403)

    def test_workflow_schema(self, client, auth_headers):
        lid = _first_listing_id(client)
        resp = client.get(f"/api/listings/{lid}/workflow", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["listing_id"] == lid
        assert "source" in data
        assert "item_id" in data
        assert "stages" in data
        keys = [s["key"] for s in data["stages"]]
        # 必须包含全部 5 个阶段
        for expected in ["script", "poster", "voice", "video", "mux"]:
            assert expected in keys, f"缺少阶段 {expected}"

    def test_workflow_stage_schema(self, client, auth_headers):
        lid = _first_listing_id(client)
        resp = client.get(f"/api/listings/{lid}/workflow", headers=auth_headers)
        for stage in resp.json()["stages"]:
            for field in ["key", "name", "status", "progress", "current_step",
                          "can_run", "previews"]:
                assert field in stage, f"阶段缺少字段 {field}"
            assert stage["status"] in ("done", "pending", "waiting", "running", "failed")

    def test_workflow_not_found(self, client, auth_headers):
        resp = client.get("/api/listings/999999999/workflow", headers=auth_headers)
        assert resp.status_code == 404

    def test_workflow_stage_consistency(self, client, auth_headers):
        """done 阶段 can_run=False，且 previews 类型正确。"""
        lid = _first_listing_id(client)
        resp = client.get(f"/api/listings/{lid}/workflow", headers=auth_headers)
        for stage in resp.json()["stages"]:
            if stage["status"] == "done":
                assert stage["can_run"] is False
            for p in stage["previews"]:
                assert p["type"] in ("image", "video", "audio", "text")
                assert "url" in p
                assert "label" in p
                if p["type"] == "text":
                    assert p.get("content"), "text 预览应携带 content"


class TestWorkflowRun:
    def test_run_unknown_stage(self, client, auth_headers):
        lid = _first_listing_id(client)
        resp = client.post(
            f"/api/listings/{lid}/workflow/run",
            json={"stage": "nope"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_run_missing_body(self, client, auth_headers):
        lid = _first_listing_id(client)
        resp = client.post(
            f"/api/listings/{lid}/workflow/run",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_run_requires_auth(self, client):
        lid = _first_listing_id(client)
        resp = client.post(f"/api/listings/{lid}/workflow/run", json={"stage": "video"})
        assert resp.status_code in (401, 403)

    def test_run_not_found(self, client, auth_headers):
        resp = client.post(
            "/api/listings/999999999/workflow/run",
            json={"stage": "video"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_run_done_stage_rejected(self, client, auth_headers):
        """已完成阶段不应再触发（避免误生成）。"""
        lid = _first_listing_id(client)
        resp = client.get(f"/api/listings/{lid}/workflow", headers=auth_headers)
        done_stage = next((s for s in resp.json()["stages"] if s["status"] == "done"), None)
        if not done_stage:
            pytest.skip("无已完成阶段")
        r = client.post(
            f"/api/listings/{lid}/workflow/run",
            json={"stage": done_stage["key"]},
            headers=auth_headers,
        )
        assert r.status_code == 400


class TestWorkflowRunAll:
    def test_run_all_requires_auth(self, client):
        lid = _first_listing_id(client)
        resp = client.post(f"/api/listings/{lid}/workflow/run-all")
        assert resp.status_code in (401, 403)

    def test_run_all_not_found(self, client, auth_headers):
        resp = client.post("/api/listings/999999999/workflow/run-all", headers=auth_headers)
        assert resp.status_code == 404

    def test_run_all_creates_serial_chain(self, client, auth_headers):
        """对完整房源触发：应返回任务链且顺序合法，且已完成阶段被跳过。"""
        lid = _first_listing_id(client)
        resp = client.post(f"/api/listings/{lid}/workflow/run-all", headers=auth_headers)
        if resp.status_code == 400:
            # 全部已完成（合理分支）
            assert "已完成" in resp.json()["detail"]
            return
        assert resp.status_code == 201
        data = resp.json()
        assert "tasks" in data
        assert "message" in data
        tasks = data["tasks"]
        assert tasks, "应至少创建一个任务"
        # 校验任务顺序遵循依赖拓扑
        order = ["script", "poster", "voice", "video", "mux"]
        stages = [t["stage"] for t in tasks]
        assert stages == [s for s in order if s in stages], f"任务顺序非法: {stages}"

    def test_run_all_all_done_rejected(self, client, auth_headers):
        """寻找一个全部完成的房源，run-all 应返回 400。"""
        resp = client.get("/api/listings?page_size=100", headers=auth_headers)
        for item in resp.json()["items"]:
            wf = client.get(f"/api/listings/{item['id']}/workflow", headers=auth_headers).json()
            if all(s["status"] == "done" for s in wf["stages"]):
                r = client.post(
                    f"/api/listings/{item['id']}/workflow/run-all",
                    headers=auth_headers,
                )
                assert r.status_code == 400
                assert "已完成" in r.json()["detail"]
                return
        pytest.skip("无全部完成的房源")
