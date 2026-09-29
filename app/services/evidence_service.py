"""
证据采集服务（F8 Day 9 从 chat_service 抽取，RAG 与 Agent 共用）

管线：混合检索（粗排证据门）→ Rerank 精排（可关；故障 fail-open）→ 二次证据门。
任一证据门不过即 ok=False，调用方据此拒答；降级（scored=False）时不启用二次门，
供应商故障绝不造成误拒——语义与原 chat_service 内联逻辑逐行等价。
"""
import asyncio
from dataclasses import dataclass

from app.config import settings
from app.services import rerank_service
from app.services.retrieval_service import retrieve

REJECT_MESSAGE = "未在知识库中检索到与您问题相关的内容，建议更换关键词，或上传相关文档后再试。"

# RAG 单轮检索未命中专用：在统一拒答文案后引导切换 Agent 多轮自主检索。
# Agent 自身拒答沿用 REJECT_MESSAGE——它已穷尽换词多查，再引导切换就是糊弄。
REJECT_MESSAGE_RAG = (
    REJECT_MESSAGE
    + "您也可以切换到 AGENT 模式，让助手自主更换关键词、多角度检索后再试一次。"
)

# Agent 取证管线全程故障（区别于 REJECT_MESSAGE 的"库里确无内容"）
ERROR_MESSAGE = "检索服务暂时异常，请稍后重试。"


@dataclass
class Evidence:
    """一次证据采集的产物。

    hits：通过两道门后的最终片段（score 为真实 relevance，或关闭/降级时的粗排原分）
    ok：粗排门 + 二次门均通过，才可作为作答依据
    scored：hits 的 score 是否为 rerank 真实分；False 时不可与 RERANK_THRESHOLD 比较
    """

    hits: list[dict]
    ok: bool
    scored: bool


async def gather_evidence(
    query: str,
    *,
    top_k: int | None = None,
    mode: str | None = None,
    store=None,
    bm25=None,
    reranker=None,
    doc_ids: list[str] | None = None,
) -> Evidence:
    final_k = settings.TOP_K if top_k is None else top_k

    # 1. 混合检索粗排 + 粗排证据门（语义证据或关键词证据任一成立）
    retrieval = await retrieve(
        query, mode=mode, vector_store=store, bm25=bm25, doc_ids=doc_ids
    )
    if not retrieval.has_evidence:
        return Evidence(hits=[], ok=False, scored=False)

    # 2. 精排 + 二次证据门（F7 语义原样保留）
    if settings.RERANK_ENABLED:
        reranked = await asyncio.to_thread(
            rerank_service.rerank, query, retrieval.hits, final_k, client=reranker,
        )
        if (
            reranked.scored
            and reranked.hits
            and reranked.hits[0]["score"] < settings.RERANK_THRESHOLD
        ):
            return Evidence(hits=[], ok=False, scored=True)
        return Evidence(hits=reranked.hits, ok=True, scored=reranked.scored)

    return Evidence(hits=retrieval.hits[:final_k], ok=True, scored=False)
