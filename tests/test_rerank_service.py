"""rerank_service 测试：httpx.MockTransport 零网络单测 + 真实 API smoke"""
import json

import httpx
import pytest

from conftest import requires_embedding_api

from app.config import settings
from app.services.rerank_service import RerankClient, rerank


def _hit(idx=0, score=0.02, content="FastAPI 用 uvicorn 启动",
         filename="guide.md", page=None, doc_id="doc"):
    return {
        "chunk_id": f"{doc_id}:chunk-{idx}",
        "content": content,
        "doc_id": doc_id,
        "filename": filename,
        "chunk_index": idx,
        "page": page,
        "score": score,
    }


class FakeRanker:
    """记录调用入参，返回预置 pairs 或抛预设异常"""

    def __init__(self, pairs=None, raise_exc=None):
        self._pairs = pairs or []
        self._raise_exc = raise_exc
        self.calls = []

    def score(self, query, documents, top_n):
        self.calls.append({"query": query, "documents": list(documents), "top_n": top_n})
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._pairs


# ---------- rerank() 编排层（纯函数式，零网络） ----------

class TestRerankOrchestration:
    def test_empty_hits_short_circuits_without_calling_ranker(self):
        ranker = FakeRanker()

        result = rerank("问题", [], 5, client=ranker)

        assert result.hits == []
        assert result.scored is False  # 短路无真实分，不可进二次门
        assert ranker.calls == []

    def test_reorders_by_pairs_and_replaces_score(self):
        hits = [
            _hit(idx=0, score=0.016, content="粗排第 1"),
            _hit(idx=1, page=3, score=0.033, content="粗排第 2"),
            _hit(idx=2, score=0.017, content="粗排第 3"),
        ]
        # 服务端判定：chunk2 最相关，chunk0 次之，chunk1 出局
        ranker = FakeRanker(pairs=[(2, 0.91), (0, 0.42)])

        out = rerank("怎么启动", hits, 2, client=ranker)

        assert out.scored is True
        assert [h["chunk_index"] for h in out.hits] == [2, 0]
        assert [h["score"] for h in out.hits] == pytest.approx([0.91, 0.42])
        # 原 hit 其余字段保留（content/page/filename），只是 score 被覆盖
        assert out.hits[0]["content"] == "粗排第 3"
        assert out.hits[1]["page"] is None
        assert out.hits[0]["filename"] == "guide.md"

    def test_passes_documents_and_min_of_top_k_and_len(self):
        hits = [_hit(idx=0, content="唯一候选")]
        ranker = FakeRanker(pairs=[(0, 0.5)])

        rerank("问题", hits, 5, client=ranker)

        assert ranker.calls[0]["query"] == "问题"
        assert ranker.calls[0]["documents"] == ["唯一候选"]
        # 候选只有 1 条时不许向上游要 5 条
        assert ranker.calls[0]["top_n"] == 1

    def test_fail_open_keeps_original_order_when_ranker_errors(self):
        hits = [_hit(idx=i, score=0.05 - 0.01 * i) for i in range(7)]
        ranker = FakeRanker(raise_exc=RuntimeError("rerank 服务炸了"))

        out = rerank("问题", hits, 5, client=ranker)

        assert out.scored is False
        # 降级：粗排原顺序取 top_k，分数也保留
        assert [h["chunk_index"] for h in out.hits] == [0, 1, 2, 3, 4]
        assert out.hits[0]["score"] == pytest.approx(0.05)


# ---------- RerankClient HTTP 层（MockTransport 拦截） ----------

class TestRerankClientHttp:
    def test_sends_payload_auth_and_parses_results(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request"] = request
            return httpx.Response(200, json={
                "id": "r1",
                "results": [
                    {"index": 1, "relevance_score": 0.88,
                     "document": {"text": "文档乙"}},
                    {"index": 0, "relevance_score": 0.12,
                     "document": {"text": "文档甲"}},
                ],
            })

        client = RerankClient(api_key="sk-test",
                              transport=httpx.MockTransport(handler))

        pairs = client.score("启动", ["文档甲", "文档乙"], top_n=2)

        assert pairs == [(1, pytest.approx(0.88)), (0, pytest.approx(0.12))]
        req = seen["request"]
        assert req.url.path == "/v1/rerank"
        assert req.headers["Authorization"] == "Bearer sk-test"
        body = json.loads(req.content)
        assert body["model"] == settings.RERANK_MODEL
        assert body["query"] == "启动"
        assert body["documents"] == ["文档甲", "文档乙"]
        assert body["top_n"] == 2
        assert body["return_documents"] is False

    def test_retries_once_after_503_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, json={"message": "overloaded"})
            return httpx.Response(200, json={
                "results": [{"index": 0, "relevance_score": 0.7}]})

        client = RerankClient(api_key="sk", transport=httpx.MockTransport(handler))

        assert client.score("q", ["d"], 1) == [(0, pytest.approx(0.7))]
        assert calls["n"] == 2

    def test_retries_once_after_timeout_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("read timed out", request=request)
            return httpx.Response(200, json={
                "results": [{"index": 0, "relevance_score": 0.7}]})

        client = RerankClient(api_key="sk", transport=httpx.MockTransport(handler))

        assert client.score("q", ["d"], 1) == [(0, pytest.approx(0.7))]
        assert calls["n"] == 2

    def test_4xx_raises_immediately_without_retry(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(400, json={"message": "bad request"})

        client = RerankClient(api_key="sk", transport=httpx.MockTransport(handler))

        with pytest.raises(httpx.HTTPStatusError):
            client.score("q", ["d"], 1)
        assert calls["n"] == 1

    def test_raises_after_two_consecutive_5xx(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(500)

        client = RerankClient(api_key="sk", transport=httpx.MockTransport(handler))

        with pytest.raises(httpx.HTTPStatusError):
            client.score("q", ["d"], 1)
        assert calls["n"] == 2


# ---------- 真实 API smoke（沿用 test_embeddings 真调惯例） ----------

@requires_embedding_api
class TestSiliconFlowRerankSmoke:
    def test_semantically_relevant_doc_ranks_first(self):
        client = RerankClient()

        pairs = client.score(
            "怎么把 web 服务跑起来",
            [
                "运行 uvicorn main:app 即可启动 FastAPI 开发服务器",
                "红烧肉冷水下锅焯水，撇去浮沫后小火慢炖一小时",
                "def add(a, b): return a + b",
            ],
            top_n=3,
        )

        assert pairs[0][0] == 0
        assert pairs[0][1] > pairs[1][1]
