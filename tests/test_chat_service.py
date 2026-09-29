"""chat_service 编排测试：FakeStore + FakeBM25 + FakeLLM 注入，零网络"""
from types import SimpleNamespace

import pytest
from openai import AuthenticationError

from app.config import settings
from app.db.bm25_store import bm25_store
from app.services import chat_service
from app.services.evidence_service import ERROR_MESSAGE
from app.services.llm_client import AUTH_ERROR_MESSAGE, LLM_UNAVAILABLE_MESSAGE


def _auth_error():
    return AuthenticationError(
        "401",
        response=SimpleNamespace(status_code=401, request=None, headers={}),
        body=None,
    )


def _hit(score=0.85, content="FastAPI 使用 uvicorn 启动开发服务器",
         filename="guide.md", page=None, idx=0, doc_id="doc"):
    return {
        "chunk_id": f"{doc_id}:chunk-{idx}",
        "content": content,
        "doc_id": doc_id,
        "filename": filename,
        "chunk_index": idx,
        "page": page,
        "score": score,
    }


class FakeStore:
    def __init__(self, hits):
        self._hits = hits
        self.queries = []

    def query_similar(self, query_text, top_k=5, doc_ids=None):
        self.queries.append((query_text, top_k, doc_ids))
        return list(self._hits)


class FakeBM25:
    def __init__(self, hits=None):
        self._hits = hits or []
        self.calls = []

    def search(self, query_text, top_k=20, doc_ids=None):
        self.calls.append((query_text, top_k, doc_ids))
        return list(self._hits)


class FakeLLM:
    def __init__(self, answer="运行 uvicorn main:app 即可启动", raise_exc=None):
        self._answer = answer
        self._raise_exc = raise_exc
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._answer


class FakeReranker:
    """F7：记录入参，按预置 pairs 重排；raise_exc 模拟精排故障"""

    def __init__(self, pairs=None, raise_exc=None):
        self._pairs = pairs
        self._raise_exc = raise_exc
        self.calls = []

    def score(self, query, documents, top_n):
        self.calls.append((query, list(documents), top_n))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._pairs if self._pairs is not None else []


class ExplodingReranker:
    """一旦被调用就炸：用于断言"开关关闭/拒答"时精排绝不触发"""

    def score(self, query, documents, top_n):
        raise AssertionError("这个测试里 rerank 不该被调用")


@pytest.fixture(autouse=True)
def reset_global_bm25_and_disable_rerank(monkeypatch):
    # 默认关闭精排：旧测保持 F6 RRF 契约零网络；TestRerank 内单独打开
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    bm25_store.clear()
    yield
    bm25_store.clear()


class TestRagAnswer:
    async def test_hit_returns_rag_response_with_answer(self):
        store, llm, bm = FakeStore([_hit()]), FakeLLM(), FakeBM25()

        resp = await chat_service.answer_question("怎么启动", store=store, llm=llm, bm25=bm)

        assert resp.mode == "rag"
        assert resp.answer == "运行 uvicorn main:app 即可启动"
        assert len(resp.sources) == 1
        assert resp.sources[0].filename == "guide.md"
        # 精排关闭（本文件 autouse）：保持 F6 RRF 契约，单路第 1 = 1/61
        assert resp.sources[0].score == pytest.approx(1 / 61)
        assert resp.response_time >= 0

    async def test_both_channels_called_with_candidate_k(self):
        store, bm = FakeStore([_hit()]), FakeBM25()

        await chat_service.answer_question("问题", store=store, llm=FakeLLM(), bm25=bm)

        assert store.queries == [("问题", settings.CANDIDATE_K, None)]
        assert bm.calls == [("问题", settings.CANDIDATE_K, None)]

    async def test_doc_ids_scoped_retrieval(self):
        store, bm = FakeStore([_hit()]), FakeBM25()

        resp = await chat_service.answer_question(
            "问题", store=store, llm=FakeLLM(), bm25=bm, doc_ids=["d1", "d2"]
        )

        assert resp.mode == "rag"
        assert store.queries[0][2] == ["d1", "d2"]
        assert bm.calls[0][2] == ["d1", "d2"]

    async def test_llm_receives_built_messages_with_query(self):
        store, llm, bm = FakeStore([_hit()]), FakeLLM(), FakeBM25()

        await chat_service.answer_question("怎么启动", store=store, llm=llm, bm25=bm)

        messages = llm.calls[0]
        assert messages[0]["role"] == "system"
        assert "guide.md" in messages[0]["content"]
        assert messages[1] == {"role": "user", "content": "怎么启动"}

    async def test_snippet_is_first_150_chars(self):
        long_content = "甲" * 200
        resp = await chat_service.answer_question(
            "q", store=FakeStore([_hit(content=long_content)]), llm=FakeLLM(), bm25=FakeBM25()
        )

        assert resp.sources[0].snippet == "甲" * 150

    async def test_page_passed_to_source(self):
        resp = await chat_service.answer_question(
            "q", store=FakeStore([_hit(page=3)]), llm=FakeLLM(), bm25=FakeBM25()
        )

        assert resp.sources[0].page == 3

    async def test_threshold_boundary_score_equal_passes(self):
        # 等于阈值不算"过低"，应正常作答
        resp = await chat_service.answer_question(
            "q",
            store=FakeStore([_hit(score=settings.RELEVANCE_THRESHOLD)]),
            llm=FakeLLM(),
            bm25=FakeBM25(),
        )

        assert resp.mode == "rag"

    async def test_only_top_k_chunks_become_sources(self):
        # 融合结果 7 条，喂给 LLM 与来源只取 TOP_K
        hits = [_hit(idx=i, doc_id=f"doc{i}") for i in range(7)]
        resp = await chat_service.answer_question(
            "q", store=FakeStore(hits), llm=FakeLLM(), bm25=FakeBM25()
        )

        assert len(resp.sources) == settings.TOP_K


class TestReject:
    async def test_empty_hits_rejects_and_skips_llm(self):
        llm = FakeLLM()

        resp = await chat_service.answer_question(
            "红烧肉做法", store=FakeStore([]), llm=llm, bm25=FakeBM25()
        )

        assert resp.mode == "reject"
        assert resp.sources == []
        assert "未在知识库中检索" in resp.answer
        # RAG 单轮未命中：引导用户切换 Agent 多轮自主检索
        assert "AGENT" in resp.answer
        assert llm.calls == []   # 拒答不花一次模型调用

    async def test_low_score_and_no_bm25_rejects(self):
        resp = await chat_service.answer_question(
            "无关问题",
            store=FakeStore([_hit(score=0.15)]),
            llm=FakeLLM(),
            bm25=FakeBM25(),
        )

        assert resp.mode == "reject"


class TestHybridEvidence:
    async def test_bm25_hit_rescues_weak_vector_score(self):
        # 代码标识符问题：向量分 0.15 低于门槛，但 BM25 精确命中 → hybrid 作答
        resp = await chat_service.answer_question(
            "@app.get 怎么用",
            store=FakeStore([_hit(score=0.15)]),
            llm=FakeLLM(),
            bm25=FakeBM25([_hit(score=4.0, idx=1, content="用 @app.get 定义 GET 路由")]),
        )

        assert resp.mode == "rag"
        assert len(resp.sources) >= 1

    async def test_vector_mode_threshold_not_bypassed_by_bm25(self):
        # 模式隔离：显式 vector 模式，BM25 再强也不许救场
        resp = await chat_service.answer_question(
            "@app.get 怎么用",
            store=FakeStore([_hit(score=0.15)]),
            llm=FakeLLM(),
            bm25=FakeBM25([_hit(score=4.0)]),
            mode="vector",
        )

        assert resp.mode == "reject"


class TestRerank:
    """F7：精排接线（本类内显式打开开关）"""

    async def test_enabled_reranks_order_and_replaces_source_score(self, monkeypatch):
        monkeypatch.setattr(settings, "RERANK_ENABLED", True)
        # 粗排 3 条（向量分过证据门；RRF 重排时顺序即插入顺序），精排把 idx=2 翻到第 1
        hits = [_hit(idx=i, score=0.8) for i in range(3)]
        ranker = FakeReranker(pairs=[(2, 0.91), (0, 0.42)])

        resp = await chat_service.answer_question(
            "怎么启动", store=FakeStore(hits), llm=FakeLLM(),
            bm25=FakeBM25(), reranker=ranker,
        )

        assert resp.mode == "rag"
        assert len(ranker.calls) == 1
        query, documents, top_n = ranker.calls[0]
        assert query == "怎么启动"
        assert len(documents) == 3
        assert top_n == 3  # min(TOP_K=5, 候选 3)
        assert [s.chunk_index for s in resp.sources] == [2, 0]
        assert resp.sources[0].score == pytest.approx(0.91)

    async def test_rerank_failure_fails_open_with_coarse_order(self, monkeypatch):
        monkeypatch.setattr(settings, "RERANK_ENABLED", True)
        hits = [_hit(idx=i, score=0.8) for i in range(7)]

        resp = await chat_service.answer_question(
            "q", store=FakeStore(hits), llm=FakeLLM(), bm25=FakeBM25(),
            reranker=FakeReranker(raise_exc=RuntimeError("502 了")),
        )

        # 精排炸了照样作答，来源保持粗排原顺序 Top-K
        assert resp.mode == "rag"
        assert [s.chunk_index for s in resp.sources] == list(range(settings.TOP_K))

    async def test_disabled_switch_skips_rerank_entirely(self, monkeypatch):
        # autouse 已关开关，这里再显式传"会炸"的 ranker 双保险
        resp = await chat_service.answer_question(
            "q", store=FakeStore([_hit()]), llm=FakeLLM(), bm25=FakeBM25(),
            reranker=ExplodingReranker(),
        )

        assert resp.mode == "rag"
        assert resp.sources[0].score == pytest.approx(1 / 61)

    async def test_reject_path_never_calls_rerank(self, monkeypatch):
        monkeypatch.setattr(settings, "RERANK_ENABLED", True)

        resp = await chat_service.answer_question(
            "无关废话", store=FakeStore([_hit(score=0.1)]), llm=FakeLLM(),
            bm25=FakeBM25(), reranker=ExplodingReranker(),
        )

        assert resp.mode == "reject"

    async def test_low_rerank_score_overturns_coarse_pass(self, monkeypatch):
        # 二次证据门：粗排向量分 0.8 过了 F6 门，但精排认为 top1 仅 0.005 → 改判拒答
        monkeypatch.setattr(settings, "RERANK_ENABLED", True)
        llm = FakeLLM()
        ranker = FakeReranker(pairs=[(0, 0.005)])

        resp = await chat_service.answer_question(
            "RAG 为什么要切块", store=FakeStore([_hit(score=0.8)]), llm=llm,
            bm25=FakeBM25(), reranker=ranker,
        )

        assert resp.mode == "reject"
        assert resp.sources == []
        assert llm.calls == []  # 二次门拦下后同样不花模型调用

    async def test_rerank_threshold_boundary_equal_passes(self, monkeypatch):
        # 等于阈值不算过低，正常作答
        monkeypatch.setattr(settings, "RERANK_ENABLED", True)
        ranker = FakeReranker(pairs=[(0, settings.RERANK_THRESHOLD)])

        resp = await chat_service.answer_question(
            "q", store=FakeStore([_hit(score=0.8)]), llm=FakeLLM(),
            bm25=FakeBM25(), reranker=ranker,
        )

        assert resp.mode == "rag"

    async def test_fail_open_does_not_apply_threshold(self, monkeypatch):
        # 精排故障降级时 hits 保留 RRF 小分数（0.016 < 阈值），但 scored=False
        # → 不做二次门判定，粗排门结论（有证据）成立，照常作答
        monkeypatch.setattr(settings, "RERANK_ENABLED", True)
        llm = FakeLLM()

        resp = await chat_service.answer_question(
            "q", store=FakeStore([_hit(score=0.8)]), llm=llm,
            bm25=FakeBM25(),
            reranker=FakeReranker(raise_exc=RuntimeError("502 了")),
        )

        assert resp.mode == "rag"
        assert len(llm.calls) == 1


class TestErrorMode:
    """F9 Day 13：非流式对称兜底——LLM/管线故障不再裸奔 500，统一 mode="error"（HTTP 仍 200）"""

    async def test_llm_runtime_error_returns_error_but_keeps_sources(self):
        llm = FakeLLM(raise_exc=RuntimeError("上游 500"))

        resp = await chat_service.answer_question(
            "怎么启动", store=FakeStore([_hit()]), llm=llm, bm25=FakeBM25()
        )

        assert resp.mode == "error"
        assert resp.answer == LLM_UNAVAILABLE_MESSAGE
        # 证据已取到，错误只发生在生成阶段：sources 仍照常拼装返回
        assert len(resp.sources) == 1
        assert resp.sources[0].filename == "guide.md"
        assert resp.response_time >= 0

    async def test_llm_auth_error_returns_auth_message(self):
        llm = FakeLLM(raise_exc=_auth_error())

        resp = await chat_service.answer_question(
            "怎么启动", store=FakeStore([_hit()]), llm=llm, bm25=FakeBM25()
        )

        assert resp.mode == "error"
        assert resp.answer == AUTH_ERROR_MESSAGE
        assert len(resp.sources) == 1

    async def test_evidence_pipeline_failure_returns_error_without_sources(
        self, monkeypatch
    ):
        async def _boom(*args, **kwargs):
            raise RuntimeError("检索管线炸了")

        monkeypatch.setattr(chat_service, "gather_evidence", _boom)

        resp = await chat_service.answer_question(
            "q", store=FakeStore([]), llm=FakeLLM(), bm25=FakeBM25()
        )

        assert resp.mode == "error"
        assert resp.answer == ERROR_MESSAGE
        assert resp.sources == []
