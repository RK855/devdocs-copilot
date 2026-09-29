"""文档管理 HTTP API —— TestClient 全链路测试（真实 bge-m3，临时目录）"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from conftest import requires_embedding_api

from app.config import settings
from app.services import document_service
from main import app

pytestmark = requires_embedding_api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "CHROMA_DATA_DIR", tmp_path / "chroma")
    with TestClient(app) as c:
        yield c


class TestUploadApi:
    def test_upload_markdown_returns_doc_info(self, client):
        r = client.post(
            "/api/documents/upload",
            files={"file": ("guide.md", "FastAPI 使用 uvicorn ASGI 服务器启动".encode(), "text/markdown")},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["filename"] == "guide.md"
        assert body["chunk_count"] == 1
        assert body["source"] == "upload"
        assert len(body["doc_id"]) == 32

    def test_upload_txt_works(self, client):
        r = client.post(
            "/api/documents/upload",
            files={"file": ("notes.txt", b"Python asyncio notes", "text/plain")},
        )
        assert r.status_code == 200
        assert r.json()["chunk_count"] == 1

    def test_unsupported_extension_returns_400(self, client):
        r = client.post(
            "/api/documents/upload",
            files={"file": ("evil.doc", b"x", "application/msword")},
        )
        assert r.status_code == 400
        assert "不支持" in r.json()["detail"]

    def test_empty_file_returns_400(self, client):
        r = client.post(
            "/api/documents/upload",
            files={"file": ("empty.md", b"", "text/markdown")},
        )
        assert r.status_code == 400


class TestListAndDeleteApi:
    def test_full_list_then_delete_flow(self, client):
        # 初始为空
        assert client.get("/api/documents").json() == {"documents": [], "total": 0}

        up = client.post(
            "/api/documents/upload",
            files={"file": ("a.md", "FastAPI 依赖注入的用法".encode(), "text/markdown")},
        ).json()

        listing = client.get("/api/documents").json()
        assert listing["total"] == 1
        assert listing["documents"][0]["filename"] == "a.md"
        assert listing["documents"][0]["chunk_count"] == 1
        assert listing["documents"][0]["source"] == "upload"

        deleted = client.delete(f"/api/documents/{up['doc_id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"success": True}

        assert client.get("/api/documents").json()["total"] == 0


class TestScopeFilter:
    def test_scope_partitions_by_startup_baseline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
        monkeypatch.setattr(settings, "CHROMA_DATA_DIR", tmp_path / "chroma")

        # 服务启动前已在库的文档 = 语料库（lifespan 拍照进会话基线）
        asyncio.run(document_service.ingest_document(
            "seeded.md", "预置教程：FastAPI 启动流程".encode(),
            upload_dir=tmp_path / "uploads", source="seed",
        ))

        with TestClient(app) as c:
            # 服务启动后的网页上传 = 我的上传（仅本次会话可见）
            c.post(
                "/api/documents/upload",
                files={"file": ("mine.md", "我自己上传的笔记".encode(), "text/markdown")},
            )

            library = c.get("/api/documents?scope=library").json()
            assert [d["filename"] for d in library["documents"]] == ["seeded.md"]

            session = c.get("/api/documents?scope=session").json()
            assert [d["filename"] for d in session["documents"]] == ["mine.md"]

            # 不带 scope 仍是全量
            assert c.get("/api/documents").json()["total"] == 2

    def test_post_startup_upload_lands_in_session_scope(self, client):
        # client fixture：启动时库为空 → 本次上传只出现在 session
        client.post(
            "/api/documents/upload",
            files={"file": ("fresh.md", "新文档内容".encode(), "text/markdown")},
        )
        assert client.get("/api/documents?scope=library").json()["total"] == 0
        assert client.get("/api/documents?scope=session").json()["total"] == 1

    def test_invalid_scope_value_returns_400(self, client):
        r = client.get("/api/documents?scope=hacker")
        assert r.status_code == 400
        assert "scope" in r.json()["detail"]
