"""API 兜底路由：未匹配 /api/* 一律 JSON 404，不落到 StaticFiles（POST 会变 405）"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "CHROMA_DATA_DIR", tmp_path / "chroma")
    with TestClient(app) as c:
        yield c


class TestApiNotFound:
    def test_unknown_post_api_path_returns_json_404(self, client):
        r = client.post("/api/not-exist", json={"query": "x"})

        assert r.status_code == 404
        assert r.json()["detail"].startswith("接口 /api/")

    def test_unknown_get_api_path_returns_json_404(self, client):
        r = client.get("/api/not-exist")

        assert r.status_code == 404
        assert "detail" in r.json()

    def test_root_still_serves_frontend(self, client):
        r = client.get("/")

        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
