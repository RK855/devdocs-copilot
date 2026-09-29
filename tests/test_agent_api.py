"""Agent HTTP API 测试：真实 bge-m3 入库 + StubAgentLLM/StubReranker，临时目录"""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import agent_service, llm_client, rerank_service
from app.services.llm_client import ChatTurn, ToolCall
from conftest import requires_embedding_api
from main import app

# LLM / Reranker 均为 Stub，仅上传入库与检索真实调用 bge-m3
pytestmark = requires_embedding_api


class StubAgentLLM:
    """第一轮强制调 search_docs；看到 tool 结果后给最终答案"""

    def __init__(self, *args, **kwargs):
        self.chat_calls = []

    def chat(self, messages, *, tools=None):
        self.chat_calls.append(list(messages))
        if not any(m.get("role") == "tool" for m in messages):
            return ChatTurn(
                content="",
                tool_calls=[ToolCall(
                    id="call_1",
                    name="search_docs",
                    arguments={"query": "FastAPI 怎么启动"},
                )],
            )
        return ChatTurn(
            content="根据文档：使用 `uvicorn main:app` 启动 FastAPI。",
            tool_calls=[],
        )

    def generate(self, messages):
        return "部分回答：资料不足。"


class StubRagLLM:
    """回归用：老 RAG 端点的 Fake"""

    def __init__(self, *args, **kwargs):
        pass

    def generate(self, messages):
        return "根据文档：使用 `uvicorn main:app` 启动 FastAPI。"


class StubReranker:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def score(self, query, documents, top_n):
        self.calls.append((query, list(documents), top_n))
        return [(i, 0.91 - 0.01 * i) for i in range(min(top_n, len(documents)))]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "CHROMA_DATA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(agent_service, "AgnesChatClient", StubAgentLLM)
    # /api/chat/query 回归用例：chat_service 经 create_chat_client 在 llm_client
    # 模块内解析 AgnesChatClient（与 Agent 自己的模块级构造缝互不影响）
    monkeypatch.setattr(llm_client, "AgnesChatClient", StubRagLLM)
    monkeypatch.setattr(rerank_service, "RerankClient", StubReranker)
    with TestClient(app) as c:
        yield c


def _upload_fastapi_doc(client):
    content = (
        "FastAPI 启动方式：使用 uvicorn main:app 命令运行开发服务器，"
        "加上 --reload 参数支持热重载。"
    ).encode()
    return client.post(
        "/api/documents/upload",
        files={"file": ("fastapi.md", content, "text/markdown")},
    ).json()


class TestAgentQueryApi:
    def test_agent_searches_and_answers_with_steps(self, client):
        _upload_fastapi_doc(client)

        r = client.post("/api/agent/query", json={"query": "FastAPI 怎么启动？"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "agent"
        assert "uvicorn main:app" in body["answer"]
        assert len(body["steps"]) == 1
        assert body["steps"][0]["tool"] == "search_docs"
        assert body["steps"][0]["cached"] is False
        assert body["steps"][0]["status"] == "ok"
        assert body["degraded"] is False
        assert body["sources"][0]["filename"] == "fastapi.md"
        assert body["response_time"] >= 0

    def test_empty_knowledge_base_unified_reject(self, client):
        r = client.post("/api/agent/query", json={"query": "红烧肉怎么做？"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "reject"
        assert body["sources"] == []
        assert body["steps"][0]["tool"] == "search_docs"
        assert body["steps"][0]["result_count"] == 0
        assert body["steps"][0]["status"] == "empty"

    def test_tool_pipeline_failure_returns_error_mode_200(
        self, client, monkeypatch
    ):
        async def _boom(*args, **kwargs):
            raise RuntimeError("检索管线爆炸")

        monkeypatch.setattr(agent_service, "gather_evidence", _boom)

        r = client.post("/api/agent/query", json={"query": "任意问题"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "error"
        assert body["sources"] == []
        assert body["degraded"] is False
        assert body["steps"][0]["status"] == "error"
        assert body["steps"][0]["error"]
        assert "检索服务暂时异常" in body["answer"]

    def test_blank_query_returns_422(self, client):
        r = client.post("/api/agent/query", json={"query": "   "})
        assert r.status_code == 422

    def test_missing_field_returns_422(self, client):
        r = client.post("/api/agent/query", json={})
        assert r.status_code == 422

    def test_rag_endpoint_behavior_unchanged(self, client):
        _upload_fastapi_doc(client)

        r = client.post("/api/chat/query", json={"query": "FastAPI 怎么启动？"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "rag"
        assert "uvicorn main:app" in body["answer"]
        assert "steps" not in body
        assert "degraded" not in body

    def test_agent_scope_restricts_search_to_selected_docs(self, client):
        # StubAgentLLM 固定用 "FastAPI 怎么启动" 调 search_docs；
        # 范围只圈密令文档时该检索零命中 → reject + empty 步骤
        _upload_fastapi_doc(client)
        secret = client.post(
            "/api/documents/upload",
            files={"file": (
                "secret.md",
                "麒麟阁密令字为风起陇西，持令者可入阁查阅密档。".encode("utf-8"),
                "text/markdown",
            )},
        ).json()

        r = client.post("/api/agent/query", json={
            "query": "任意问题",
            "doc_ids": [secret["doc_id"]],
        })

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "reject"
        assert body["steps"][0]["tool"] == "search_docs"
        assert body["steps"][0]["status"] == "empty"
        assert body["steps"][0]["result_count"] == 0

    def test_agent_general_fallback_via_http(self, client):
        # 空库：StubAgentLLM 首轮检索零命中后给终答 → reject 支；
        # allow_general=true → 其 generate() 输出经服务端补免责声明 → general
        r = client.post("/api/agent/query", json={
            "query": "红烧肉怎么做？", "allow_general": True,
        })

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "general"
        assert body["sources"] == []
        assert body["degraded"] is False
        assert body["answer"].startswith("⚠️")
        # 库内检索轨迹保留：用户看得到"先努力查过一遍"
        assert body["steps"][0]["tool"] == "search_docs"
        assert body["steps"][0]["status"] == "empty"

    def test_rag_endpoint_ignores_allow_general(self, client):
        # RAG 端点收到开关必须忽略：空库仍走 REJECT_MESSAGE_RAG 引导，不产生 general
        r = client.post("/api/chat/query", json={
            "query": "红烧肉怎么做？", "allow_general": True,
        })

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "reject"
        assert "AGENT" in body["answer"]
        assert "⚠️" not in body["answer"]


def _parse_sse(body: str):
    """SSE 文本 → [(event, data), ...]，与前端 createSSEParser 同协议解析"""
    events = []
    for frame in body.split("\n\n"):
        name = None
        data_lines = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if name:
            events.append((name, json.loads("".join(data_lines))))
    return events


class TestAgentStreamApi:
    """POST /api/agent/stream：边执行边推 phase/tool_start/tool_end，终态整包 done"""

    def test_stream_progress_events_then_done(self, client):
        _upload_fastapi_doc(client)

        with client.stream(
            "POST", "/api/agent/stream", json={"query": "FastAPI 怎么启动？"}
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = _parse_sse(r.read().decode("utf-8"))

        names = [n for n, _ in events]
        assert names == ["phase", "tool_start", "tool_end", "phase", "done"]
        assert events[0][1] == {"phase": "thinking", "round": 1}
        start = events[1][1]
        assert start["step"] == 1
        assert start["tool"] == "search_docs"
        assert start["arguments"]["query"] == "FastAPI 怎么启动"
        assert start["cached"] is False
        assert events[2][1]["status"] == "ok"
        assert events[2][1]["result_count"] == 1
        # 末轮思考（模型组织终答）后 done 承载完整 AgentChatResponse
        assert events[3][1] == {"phase": "thinking", "round": 2}
        done = events[4][1]
        assert done["mode"] == "agent"
        assert "uvicorn main:app" in done["answer"]
        assert done["steps"][0]["tool"] == "search_docs"
        assert done["degraded"] is False

    def test_stream_pipeline_failure_still_done_mode_error(self, client, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("检索管线爆炸")

        monkeypatch.setattr(agent_service, "gather_evidence", _boom)

        with client.stream(
            "POST", "/api/agent/stream", json={"query": "任意问题"}
        ) as r:
            assert r.status_code == 200
            events = _parse_sse(r.read().decode("utf-8"))

        names = [n for n, _ in events]
        assert "error" not in names  # 业务故障走 done.mode=error，不发 SSE error
        assert names[-1] == "done"
        done = dict(events)["done"]
        assert done["mode"] == "error"
        assert done["steps"][0]["status"] == "error"

    def test_stream_blank_query_returns_422(self, client):
        with client.stream(
            "POST", "/api/agent/stream", json={"query": "   "}
        ) as r:
            assert r.status_code == 422


class StubCodeAgentLLM:
    """search_docs → generate_code_example → 终答；generate 返回代码片段"""

    def __init__(self, *args, **kwargs):
        self.chat_calls = []

    def chat(self, messages, *, tools=None):
        self.chat_calls.append(list(messages))
        n_tool_msgs = sum(1 for m in messages if m.get("role") == "tool")
        if n_tool_msgs == 0:
            return ChatTurn(
                content="",
                tool_calls=[ToolCall(
                    id="call_1", name="search_docs",
                    arguments={"query": "FastAPI 怎么启动"},
                )],
            )
        if n_tool_msgs == 1:
            return ChatTurn(
                content="",
                tool_calls=[ToolCall(
                    id="call_2", name="generate_code_example",
                    arguments={"task": "写一个 FastAPI 启动示例"},
                )],
            )
        return ChatTurn(content="下面是启动示例代码。", tool_calls=[])

    def generate(self, messages):
        return "```python\nimport uvicorn\nuvicorn.run('main:app')\n```"


class TestAgentCodeToolApi:
    def test_code_generation_flow_via_http(self, client, monkeypatch):
        monkeypatch.setattr(agent_service, "AgnesChatClient", StubCodeAgentLLM)
        _upload_fastapi_doc(client)

        r = client.post("/api/agent/query", json={"query": "给个启动示例"})

        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "agent"
        assert [s["tool"] for s in body["steps"]] == [
            "search_docs", "generate_code_example",
        ]
        assert body["steps"][1]["result_count"] == 0
        assert body["answer"] == "下面是启动示例代码。"
        assert body["sources"][0]["filename"] == "fastapi.md"
