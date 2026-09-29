"""混合检索编排测试：Fake 向量库 + Fake BM25 注入，零网络验证 RRF 与三模式"""
import pytest

from app.config import settings
from app.services import retrieval_service


def _hit(chunk_id, score, *, doc_id=None, filename=None, idx=None, content="内容"):
    doc_id = doc_id or chunk_id.split(":")[0]
    return {
        "chunk_id": chunk_id,
        "content": content,
        "doc_id": doc_id,
        "filename": filename or f"{doc_id}.md",
        "chunk_index": idx if idx is not None else int(chunk_id.rsplit("-", 1)[1]),
        "page": None,
        "score": score,
    }


class FakeVectorStore:
    def __init__(self, hits):
        self._hits = hits
        self.calls = []

    def query_similar(self, query_text, top_k=5, doc_ids=None):
        self.calls.append((query_text, top_k, doc_ids))
        return list(self._hits)


class FakeBM25:
    def __init__(self, hits):
        self._hits = hits
        self.calls = []

    def search(self, query_text, top_k=20, doc_ids=None):
        self.calls.append((query_text, top_k, doc_ids))
        return list(self._hits)


@pytest.fixture(autouse=True)
def reset_global_bm25():
    from app.db.bm25_store import bm25_store
    bm25_store.clear()
    yield
    bm25_store.clear()


class TestRRF:
    async def test_both_channels_empty_no_evidence(self):
        result = await retrieval_service.retrieve(
            "问题", vector_store=FakeVectorStore([]), bm25=FakeBM25([])
        )

        assert result.hits == []
        assert result.has_evidence is False

    async def test_each_channel_fetches_candidate_k(self):
        vs, bm = FakeVectorStore([_hit("d:chunk-0", 0.9)]), FakeBM25([])

        await retrieval_service.retrieve("问题", vector_store=vs, bm25=bm)

        assert vs.calls == [("问题", settings.CANDIDATE_K, None)]
        assert bm.calls == [("问题", settings.CANDIDATE_K, None)]

    async def test_duplicate_chunk_fuses_rrf_scores(self):
        # 同一 chunk 在两路分别排第 1：RRF = 1/61 + 1/61
        vs = FakeVectorStore([_hit("d:chunk-0", 0.8, content="向量原文")])
        bm = FakeBM25([_hit("d:chunk-0", 3.2)])

        result = await retrieval_service.retrieve("问题", vector_store=vs, bm25=bm)

        assert len(result.hits) == 1
        assert result.hits[0]["score"] == pytest.approx(2 / 61)
        # 原文/元数据以先出现的向量路为准
        assert result.hits[0]["content"] == "向量原文"

    async def test_rrf_order_and_tie_break_prefers_vector(self):
        # A：向量第1 + BM25第2；B：向量第2 + BM25第1 → 总分相同，稳定排序向量路在前
        vs = FakeVectorStore([_hit("a:chunk-0", 0.9), _hit("b:chunk-0", 0.8)])
        bm = FakeBM25([_hit("b:chunk-0", 5.0), _hit("a:chunk-0", 4.0)])

        result = await retrieval_service.retrieve("问题", vector_store=vs, bm25=bm)

        assert [h["chunk_id"] for h in result.hits] == ["a:chunk-0", "b:chunk-0"]
        assert result.hits[0]["score"] == pytest.approx(1 / 61 + 1 / 62)

    async def test_chunk_only_in_bm25_still_ranked(self):
        vs = FakeVectorStore([_hit("a:chunk-0", 0.5)])
        bm = FakeBM25([_hit("b:chunk-0", 6.0), _hit("c:chunk-0", 5.0)])

        result = await retrieval_service.retrieve("@app.get", vector_store=vs, bm25=bm)

        ids = [h["chunk_id"] for h in result.hits]
        assert set(ids) == {"a:chunk-0", "b:chunk-0", "c:chunk-0"}
        # b 在 BM25 排第 1（1/61）高于 c 排第 2（1/62）；a 与 b 同分，平局向量路优先
        assert ids[1] == "b:chunk-0"
        assert ids[2] == "c:chunk-0"

    async def test_fused_list_capped_at_fused_k(self):
        vs = FakeVectorStore([_hit(f"v:chunk-{i}", 0.9 - i * 0.01) for i in range(8)])
        bm = FakeBM25([_hit(f"b:chunk-{i}", 5.0 - i * 0.1) for i in range(8)])

        result = await retrieval_service.retrieve("问题", vector_store=vs, bm25=bm)

        assert len(result.hits) == settings.FUSED_K


class TestScopePassThrough:
    async def test_doc_ids_reach_both_hybrid_channels(self):
        vs, bm = FakeVectorStore([_hit("a:chunk-0", 0.9)]), FakeBM25([])

        await retrieval_service.retrieve(
            "问题", vector_store=vs, bm25=bm, doc_ids=["d1", "d2"]
        )

        assert vs.calls[0][2] == ["d1", "d2"]
        assert bm.calls[0][2] == ["d1", "d2"]

    async def test_default_scope_is_none(self):
        vs, bm = FakeVectorStore([_hit("a:chunk-0", 0.9)]), FakeBM25([])

        await retrieval_service.retrieve("问题", vector_store=vs, bm25=bm)

        assert vs.calls[0][2] is None
        assert bm.calls[0][2] is None

    async def test_vector_mode_passes_scope_to_vector_only(self):
        bm = FakeBM25([_hit("b:chunk-0", 9.9)])

        await retrieval_service.retrieve(
            "问题", mode="vector",
            vector_store=FakeVectorStore([_hit("a:chunk-0", 0.8)]),
            bm25=bm, doc_ids=["d1"],
        )

        assert bm.calls == []


class TestEvidence:
    async def test_strong_vector_only_is_evidence(self):
        result = await retrieval_service.retrieve(
            "语义问题", vector_store=FakeVectorStore([_hit("d:chunk-0", 0.76)]),
            bm25=FakeBM25([]),
        )
        assert result.has_evidence is True

    async def test_weak_vector_but_bm25_hit_is_evidence(self):
        # 向量低于门槛但关键词精确命中（代码标识符场景）：hybrid 应当答
        result = await retrieval_service.retrieve(
            "@app.get",
            vector_store=FakeVectorStore([_hit("d:chunk-0", 0.35)]),
            bm25=FakeBM25([_hit("d:chunk-1", 4.0)]),
        )
        assert result.has_evidence is True

    async def test_weak_vector_and_empty_bm25_has_no_evidence(self):
        result = await retrieval_service.retrieve(
            "无关问题",
            vector_store=FakeVectorStore([_hit("d:chunk-0", 0.35)]),
            bm25=FakeBM25([]),
        )
        assert result.has_evidence is False

    async def test_threshold_equal_counts_as_evidence(self):
        result = await retrieval_service.retrieve(
            "边界",
            vector_store=FakeVectorStore([_hit("d:chunk-0", settings.RELEVANCE_THRESHOLD)]),
            bm25=FakeBM25([]),
        )
        assert result.has_evidence is True


class TestModes:
    async def test_vector_mode_ignores_bm25(self):
        bm = FakeBM25([_hit("b:chunk-0", 9.9)])

        result = await retrieval_service.retrieve(
            "问题", mode="vector",
            vector_store=FakeVectorStore([_hit("a:chunk-0", 0.8)]), bm25=bm,
        )

        assert [h["chunk_id"] for h in result.hits] == ["a:chunk-0"]
        assert result.hits[0]["score"] == 0.8          # vector 模式保留余弦分
        assert bm.calls == []                            # BM25 通道根本不调用

    async def test_vector_mode_low_score_no_evidence_even_if_bm25_strong(self):
        # 模式隔离：vector 模式下 BM25 再强也不能救场
        result = await retrieval_service.retrieve(
            "问题", mode="vector",
            vector_store=FakeVectorStore([_hit("a:chunk-0", 0.2)]),
            bm25=FakeBM25([_hit("b:chunk-0", 9.9)]),
        )
        assert result.has_evidence is False

    async def test_bm25_mode_ignores_vector(self):
        vs = FakeVectorStore([_hit("a:chunk-0", 0.99)])

        result = await retrieval_service.retrieve(
            "问题", mode="bm25",
            vector_store=vs, bm25=FakeBM25([_hit("b:chunk-0", 4.0)]),
        )

        assert [h["chunk_id"] for h in result.hits] == ["b:chunk-0"]
        assert vs.calls == []

    async def test_bm25_mode_empty_has_no_evidence(self):
        result = await retrieval_service.retrieve(
            "问题", mode="bm25",
            vector_store=FakeVectorStore([_hit("a:chunk-0", 0.99)]),
            bm25=FakeBM25([]),
        )
        assert result.has_evidence is False

    async def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="检索模式"):
            await retrieval_service.retrieve(
                "问题", mode="magic",
                vector_store=FakeVectorStore([]), bm25=FakeBM25([]),
            )
