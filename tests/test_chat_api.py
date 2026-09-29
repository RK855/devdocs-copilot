"""问答 HTTP API 测试：真实 bge-m3 检索 + StubLLM/StubReranker，临时目录"""
import json

import pytest
from fastapi.testclient import TestClient

from conftest import requires_embedding_api

from app.config import settings
from app.services import llm_client, rerank_service
from main import app

# LLM / Reranker 均为 Stub，仅上传入库与检索真实调用 bge-m3
pytestmark = requires_embedding_api


class StubLLM:
    """替换真实 AgnesChatClient：无参可构造，固定返回，零网络"""
    def __init__(self, *args, **kwargs):
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        return "根据文档：使用 `uvicorn main:app` 启动 FastAPI。"

    def stream_generate(self, messages):
        self.calls.append(messages)
        for char in "根据文档：使用 `uvicorn main:app` 启动 FastAPI。":
            yield char


class StubReranker:
    """替换真实 RerankClient：无参可构造，给唯一候选固定 relevance 0.91"""
    def __init__(self, *args, **kwargs):
        self.calls = []

    def score(self, query, documents, top_n):
        self.calls.append((query, list(documents), top_n))
        return [(i, 0.91 - 0.01 * i) for i in range(min(top_n, len(documents)))]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "CHROMA_DATA_DIR", tmp_path / "chroma")
    # create_chat_client 在 llm_client 模块内解析 AgnesChatClient：patch 一处，
    # chat_service 与 stream_service 两条链路同时换成零网络桩
    monkeypatch.setattr(llm_client, "AgnesChatClient", StubLLM)
    monkeypatch.setattr(rerank_service, "RerankClient", StubReranker)
    with TestClient(app) as c:
        yield c


def _upload_fastapi_doc(client):
    content = "FastAPI 启动方式：使用 uvicorn main:app 命令运行开发服务器，加上 --reload 参数支持热重载。".encode()
    return client.post(
        "/api/documents/upload",
        files={"file": ("fastapi.md", content, "text/markdown")},
    ).json()


def _upload_doc(client, filename, text):
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, text.encode("utf-8"), "text/markdown")},
    ).json()


class TestChatQuery:
    def test_answer_with_sources_after_upload(self, client):
        _upload_fastapi_doc(client)

        r = client.post("/api/chat/query", json={"query": "FastAPI 怎么启动？"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "rag"
        assert "uvicorn main:app" in body["answer"]
        assert len(body["sources"]) == 1
        assert body["sources"][0]["filename"] == "fastapi.md"
        # F7 起精排开启（StubReranker）：来源分数为 relevance_score 0.91
        assert body["sources"][0]["score"] == pytest.approx(0.91)
        assert body["response_time"] >= 0

    def test_query_empty_knowledge_base_rejects(self, client):
        r = client.post("/api/chat/query", json={"query": "随便什么问题"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "reject"
        assert body["sources"] == []
        assert "未在知识库中检索" in body["answer"]

    def test_blank_query_returns_422(self, client):
        r = client.post("/api/chat/query", json={"query": "   "})

        assert r.status_code == 422

    def test_missing_field_returns_422(self, client):
        r = client.post("/api/chat/query", json={})

        assert r.status_code == 422

    def test_query_too_long_returns_422(self, client):
        r = client.post("/api/chat/query", json={"query": "怎" * 2001})

        assert r.status_code == 422


class TestDocScopeApi:
    def test_query_scope_filters_retrieval(self, client):
        fastapi = _upload_fastapi_doc(client)
        secret = _upload_doc(
            client, "secret.md", "麒麟阁密令字为风起陇西，持令者可入阁查阅密档。"
        )

        # 范围只圈 FastAPI 文档，问密令 → 范围外 → 拒答
        r = client.post("/api/chat/query", json={
            "query": "麒麟阁的密令字是什么？",
            "doc_ids": [fastapi["doc_id"]],
        })
        assert r.json()["mode"] == "reject"

        # 范围只圈密令文档 → 作答，且来源只能来自 secret.md
        r2 = client.post("/api/chat/query", json={
            "query": "麒麟阁的密令字是什么？",
            "doc_ids": [secret["doc_id"]],
        })
        body = r2.json()
        assert body["mode"] == "rag"
        assert {s["filename"] for s in body["sources"]} == {"secret.md"}

    def test_empty_doc_ids_list_means_full_library(self, client):
        _upload_fastapi_doc(client)

        r = client.post("/api/chat/query", json={
            "query": "FastAPI 怎么启动？", "doc_ids": [],
        })

        assert r.json()["mode"] == "rag"

    def test_more_than_100_doc_ids_returns_422(self, client):
        r = client.post("/api/chat/query", json={
            "query": "问题", "doc_ids": [f"doc-{i}" for i in range(101)],
        })

        assert r.status_code == 422


def _parse_sse_frames(text):
    """把 SSE 响应体解析成 [(event, data), ...]"""
    frames = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        frames.append((event, data))
    return frames


class TestChatStream:
    def test_stream_answer_is_sse_with_frames(self, client):
        _upload_fastapi_doc(client)

        r = client.post("/api/chat/stream", json={"query": "FastAPI 怎么启动？"})

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers.get("cache-control") == "no-cache"

        frames = _parse_sse_frames(r.text)
        names = [name for name, _ in frames]
        assert names[0] == "meta"
        assert names[1] == "sources"
        assert names[-1] == "done"
        assert all(name == "delta" for name in names[2:-1])

        meta = frames[0][1]
        assert meta["mode"] == "rag"
        assert len(meta["response_id"]) == 12
        assert frames[1][1][0]["filename"] == "fastapi.md"

        answer = "".join(data["text"] for _, data in frames[2:-1])
        assert "uvicorn main:app" in answer
        assert frames[-1][1]["response_time"] >= 0

    def test_stream_reject_on_empty_knowledge_base(self, client):
        r = client.post("/api/chat/stream", json={"query": "随便什么问题"})

        frames = _parse_sse_frames(r.text)
        names = [name for name, _ in frames]
        assert names == ["meta", "delta", "done"]
        assert frames[0][1]["mode"] == "reject"
        assert "未在知识库中检索" in frames[1][1]["text"]

    def test_stream_blank_query_returns_422(self, client):
        r = client.post("/api/chat/stream", json={"query": "   "})

        assert r.status_code == 422

    def test_stream_too_long_returns_422(self, client):
        r = client.post("/api/chat/stream", json={"query": "怎" * 2001})

        assert r.status_code == 422

    def test_stream_scoped_out_of_range_rejects(self, client):
        fastapi = _upload_fastapi_doc(client)
        _upload_doc(
            client, "secret.md", "麒麟阁密令字为风起陇西，持令者可入阁查阅密档。"
        )

        r = client.post("/api/chat/stream", json={
            "query": "麒麟阁的密令字是什么？",
            "doc_ids": [fastapi["doc_id"]],
        })

        frames = _parse_sse_frames(r.text)
        assert [name for name, _ in frames] == ["meta", "delta", "done"]
        assert frames[0][1]["mode"] == "reject"

    def test_query_endpoint_contract_unchanged(self, client):
        _upload_fastapi_doc(client)

        r = client.post("/api/chat/query", json={"query": "FastAPI 怎么启动？"})

        assert r.status_code == 200
        assert set(r.json().keys()) == {"answer", "sources", "mode", "response_time"}
