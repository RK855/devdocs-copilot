"""Chat 相关 Pydantic 数据契约测试"""
import pytest
from pydantic import ValidationError

from app.schemas import (
    AgentChatResponse, AgentStep, ChatRequest, ChatResponse, SourceOut,
)


class TestChatRequest:
    def test_normal_query_ok(self):
        req = ChatRequest(query="怎么启动 FastAPI？")
        assert req.query == "怎么启动 FastAPI？"

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="")

    def test_whitespace_only_query_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="   \n\t ")

    def test_doc_ids_defaults_to_none(self):
        assert ChatRequest(query="问题").doc_ids is None

    def test_doc_ids_accepts_string_list_and_empty_list(self):
        req = ChatRequest(query="问题", doc_ids=["abc-1", "def-2"])
        assert req.doc_ids == ["abc-1", "def-2"]
        # 空列表合法：语义为"不圈选 = 全库"，由服务层归一
        assert ChatRequest(query="问题", doc_ids=[]).doc_ids == []

    def test_doc_ids_rejects_more_than_100(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="问题", doc_ids=[f"doc-{i}" for i in range(101)])

    def test_doc_ids_rejects_oversized_single_id(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="问题", doc_ids=["x" * 65])

    def test_doc_ids_rejects_non_string_elements(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="问题", doc_ids=["ok", 123])

    def test_allow_general_defaults_false(self):
        assert ChatRequest(query="问题").allow_general is False

    def test_allow_general_accepts_true(self):
        req = ChatRequest(query="问题", allow_general=True)
        assert req.allow_general is True


class TestSourceOut:
    def test_page_optional(self):
        s1 = SourceOut(filename="a.md", chunk_index=0, snippet="x", score=0.9)
        s2 = SourceOut(filename="b.pdf", chunk_index=2, snippet="y", score=0.8, page=3)
        assert s1.page is None
        assert s2.page == 3


class TestChatResponse:
    def test_build_full_response(self):
        resp = ChatResponse(
            answer="用 uvicorn 启动",
            sources=[SourceOut(filename="a.md", chunk_index=0, snippet="...", score=0.91)],
            mode="rag",
            response_time=1.23,
        )
        dumped = resp.model_dump()
        assert dumped["mode"] == "rag"
        assert dumped["sources"][0]["score"] == 0.91
        assert len(dumped["sources"]) == 1


class TestAgentChatResponse:
    def test_build_full_agent_response(self):
        step = AgentStep(
            step=1, tool="search_docs",
            arguments={"query": "怎么启动", "top_k": 5},
            result_count=2, cached=False,
        )
        resp = AgentChatResponse(
            answer="用 uvicorn 启动", sources=[], mode="agent",
            response_time=1.23, steps=[step],
        )

        dumped = resp.model_dump()
        assert dumped["mode"] == "agent"
        assert dumped["steps"][0]["tool"] == "search_docs"
        assert dumped["steps"][0]["cached"] is False

    def test_reject_mode_allowed(self):
        resp = AgentChatResponse(
            answer="未找到", sources=[], mode="reject",
            response_time=0.1, steps=[],
        )
        assert resp.mode == "reject"

    def test_other_mode_rejected(self):
        with pytest.raises(ValidationError):
            AgentChatResponse(
                answer="x", sources=[], mode="rag",
                response_time=0.1, steps=[],
            )

    def test_general_mode_allowed(self):
        resp = AgentChatResponse(
            answer="通用知识答案", sources=[], mode="general",
            response_time=0.1, steps=[],
        )
        assert resp.mode == "general"
