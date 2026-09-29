"""evidence_service 测试：粗排门 / 二次门 / fail-open / top_k 透传"""
import pytest

from app.services import evidence_service, rerank_service
from app.services.evidence_service import gather_evidence
from app.services.rerank_service import RerankResult
from app.services.retrieval_service import RetrievalResult


def _hit(chunk_id="c1", score=0.9, content="uvicorn main:app"):
    return {
        "chunk_id": chunk_id, "filename": "a.md", "chunk_index": 0,
        "content": content, "score": score, "page": None,
    }


def _patch_pipeline(monkeypatch, retrieval, rerank_fn=None):
    async def fake_retrieve(query, **kwargs):
        return retrieval

    monkeypatch.setattr(evidence_service, "retrieve", fake_retrieve)
    if rerank_fn is not None:
        monkeypatch.setattr(rerank_service, "rerank", rerank_fn)


class TestGatherEvidence:
    async def test_coarse_gate_rejects_and_skips_rerank(self, monkeypatch):
        rerank_calls = []

        def fake_rerank(query, hits, top_k, *, client=None):
            rerank_calls.append(1)
            return RerankResult(hits, True)

        _patch_pipeline(monkeypatch, RetrievalResult(hits=[], has_evidence=False),
                        fake_rerank)

        ev = await gather_evidence("随便什么")

        assert ev.ok is False
        assert ev.hits == []
        assert ev.scored is False
        assert rerank_calls == []

    async def test_second_gate_rejects_when_rerank_top1_below_threshold(
        self, monkeypatch
    ):
        _patch_pipeline(
            monkeypatch,
            RetrievalResult(hits=[_hit(score=0.02)], has_evidence=True),
            lambda q, hits, top_k, *, client=None: RerankResult(
                [_hit(score=0.001)], True
            ),
        )

        ev = await gather_evidence("量子纠缠与区块链")

        assert ev.ok is False
        assert ev.scored is True

    async def test_fail_open_degradation_does_not_reject(self, monkeypatch):
        _patch_pipeline(
            monkeypatch,
            RetrievalResult(hits=[_hit(score=0.02)], has_evidence=True),
            lambda q, hits, top_k, *, client=None: RerankResult(hits, False),
        )

        ev = await gather_evidence("怎么启动")

        assert ev.ok is True
        assert ev.scored is False
        assert ev.hits[0]["score"] == 0.02

    async def test_disabled_rerank_returns_coarse_hits_sliced(self, monkeypatch):
        monkeypatch.setattr(evidence_service.settings, "RERANK_ENABLED", False)
        calls = []
        _patch_pipeline(
            monkeypatch,
            RetrievalResult(hits=[_hit("c1"), _hit("c2"), _hit("c3")],
                            has_evidence=True),
            lambda *a, **k: calls.append(1),
        )

        ev = await gather_evidence("q", top_k=2)

        assert ev.ok is True
        assert [h["chunk_id"] for h in ev.hits] == ["c1", "c2"]
        assert calls == []

    async def test_top_k_is_passed_to_rerank(self, monkeypatch):
        seen = {}

        def fake_rerank(query, hits, top_k, *, client=None):
            seen["top_k"] = top_k
            return RerankResult(hits, True)

        _patch_pipeline(
            monkeypatch,
            RetrievalResult(hits=[_hit()], has_evidence=True),
            fake_rerank,
        )

        await gather_evidence("q", top_k=8)

        assert seen["top_k"] == 8

    async def test_doc_ids_are_passed_to_retrieve(self, monkeypatch):
        seen = {}

        async def fake_retrieve(query, **kwargs):
            seen.update(kwargs)
            return RetrievalResult(hits=[_hit()], has_evidence=True)

        monkeypatch.setattr(evidence_service, "retrieve", fake_retrieve)

        await gather_evidence("q", doc_ids=["d1", "d2"])

        assert seen["doc_ids"] == ["d1", "d2"]
