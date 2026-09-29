"""混合检索编排（F6）

两路粗排 → RRF 融合：
  向量路（懂语义）top-CANDIDATE_K ┐
                                  ├─ RRF: score(d) = Σ 1/(rank + 60) → 去重取 FUSED_K
  BM25 路（精词面）top-CANDIDATE_K ┘

三模式：vector / bm25 / hybrid，供问答链路与 F7 评测脚本对比使用。
证据门槛（has_evidence）：任一检索路给出可信信号即答，两路皆弱才拒答。
"""
import asyncio
from dataclasses import dataclass

from app.config import settings
from app.db.bm25_store import bm25_store
from app.db.vector_store import VectorStore

RRF_K = 60  # RRF 平滑常数，业界默认值；越大则排名差距影响越小

VALID_MODES = ("vector", "bm25", "hybrid")


@dataclass
class RetrievalResult:
    """一次检索的产物：融合排序结果 + 是否存在足以作答的证据"""

    hits: list[dict]
    has_evidence: bool


def rrf_fuse(vector_hits: list[dict], bm25_hits: list[dict], fused_k: int) -> list[dict]:
    """按 chunk_id 合并去重，RRF 分数相加；同分稳定排序偏向先入的向量路。

    输出 hit 的 score 字段被替换为 RRF 融合分，其余字段取该 chunk 第一次出现时的内容。
    """
    merged: dict[str, dict] = {}

    # 向量路先入，保证平局时（如同为单路第 1）排序确定性偏向向量路
    for rank, hit in enumerate(vector_hits, start=1):
        entry = dict(hit)
        entry["score"] = 1 / (RRF_K + rank)
        merged[hit["chunk_id"]] = entry

    for rank, hit in enumerate(bm25_hits, start=1):
        contribution = 1 / (RRF_K + rank)
        if hit["chunk_id"] in merged:
            merged[hit["chunk_id"]]["score"] += contribution
        else:
            entry = dict(hit)
            entry["score"] = contribution
            merged[hit["chunk_id"]] = entry

    # Python sorted 稳定：分数相同保持插入顺序（向量路在前）
    return sorted(merged.values(), key=lambda h: h["score"], reverse=True)[:fused_k]


async def retrieve(
    query: str,
    *,
    mode: str | None = None,
    vector_store=None,
    bm25=None,
    doc_ids: list[str] | None = None,
) -> RetrievalResult:
    """按指定模式检索；store/bm25 可注入替身，缺省接全局真实实现。

    doc_ids 非空时把检索限制在指定文档内（文档级圈选，两路通道都生效）。
    """
    selected_mode = mode or settings.RETRIEVAL_MODE
    if selected_mode not in VALID_MODES:
        raise ValueError(f"未知检索模式: {selected_mode}，可选 {VALID_MODES}")

    bm25_index = bm25 if bm25 is not None else bm25_store

    async def vector_search() -> list[dict]:
        store = vector_store or await asyncio.to_thread(VectorStore)
        return await asyncio.to_thread(
            store.query_similar, query, settings.CANDIDATE_K, doc_ids
        )

    async def bm25_search() -> list[dict]:
        return await asyncio.to_thread(
            bm25_index.search, query, settings.CANDIDATE_K, doc_ids
        )

    threshold = settings.RELEVANCE_THRESHOLD

    if selected_mode == "vector":
        vector_hits = await vector_search()
        has_evidence = bool(vector_hits) and vector_hits[0]["score"] >= threshold
        return RetrievalResult(hits=vector_hits[: settings.FUSED_K], has_evidence=has_evidence)

    if selected_mode == "bm25":
        bm25_hits = await bm25_search()
        # BM25 的 search 已保证零词面交集不返回，非空即证据
        return RetrievalResult(hits=bm25_hits[: settings.FUSED_K], has_evidence=bool(bm25_hits))

    # hybrid：两路并发粗排，语义证据或关键词证据任一成立即可作答
    vector_hits, bm25_hits = await asyncio.gather(vector_search(), bm25_search())
    vector_evidence = bool(vector_hits) and vector_hits[0]["score"] >= threshold
    has_evidence = vector_evidence or bool(bm25_hits)
    fused = rrf_fuse(vector_hits, bm25_hits, settings.FUSED_K)
    return RetrievalResult(hits=fused, has_evidence=has_evidence)
