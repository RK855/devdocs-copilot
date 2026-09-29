"""Rerank 精排（F7）：两阶段检索管线的第二阶段

粗排候选（RRF top-10）→ 硅基流动 bge-reranker-v2-m3 对 query/chunk 逐对打分 → top-k。
cross-encoder 比向量内积准但更慢，只适合对小候选集精排，不能全库跑。

fail-open：rerank API 重试耗尽时不抛错，退回粗排原顺序——证据门已过，
精排供应商故障不该拖垮问答链路。RerankResult.scored 区分"真实精排分"与降级粗排分，
让调用方决定能否据此做二次证据门（降级时不能拿 RRF 小数当 relevance 比阈值）。
"""
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 网络层"临时性故障"：超时/连接类（5xx 在 score() 内单独判定后走同一重试路径）
_RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


@dataclass
class RerankResult:
    """rerank 产物。

    scored=True：hits 的 score 是 cross-encoder 真实 relevance（0~1）；
    scored=False：空候选短路或调用失败降级，score 仍是粗排原值，不可与 RERANK_THRESHOLD 比较。
    """
    hits: list[dict]
    scored: bool


class RerankClient:
    """硅基流动 POST /v1/rerank 封装。

    transport 可注入 httpx.MockTransport，测试零网络。
    """

    def __init__(self, *, api_key=None, base_url=None, model=None, timeout=None,
                 transport=None):
        self._model = model or settings.RERANK_MODEL
        self._client = httpx.Client(
            base_url=base_url or settings.SILICONFLOW_BASE_URL,
            timeout=timeout if timeout is not None else settings.RERANK_TIMEOUT,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key or settings.SILICONFLOW_API_KEY}"},
        )

    def score(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """逐对打分，返回 [(原 documents 下标, relevance_score)]，服务端已按相关性降序。

        超时/连接失败/5xx 最多尝试 2 次（初次 + 重试 1 次）；4xx 立即抛出不浪费重试。
        """
        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                resp = self._client.post("/rerank", json=payload)
                if resp.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        f"rerank 服务端错误 {resp.status_code}",
                        request=resp.request, response=resp,
                    )
                    continue
                resp.raise_for_status()
                return [
                    (int(item["index"]), float(item["relevance_score"]))
                    for item in resp.json()["results"]
                ]
            except _RETRYABLE as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


def rerank(query: str, hits: list[dict], top_k: int, *, client=None) -> RerankResult:
    """对粗排 hits 精排：score 替换为 relevance_score，其余字段原样保留。

    client 可注入 Fake/MockTransport 版 RerankClient；空候选直接短路（scored=False）。
    任何打分异常都降级为粗排原顺序 top_k（fail-open，scored=False）。
    """
    if not hits:
        return RerankResult([], False)

    ranker = client or RerankClient()
    try:
        pairs = ranker.score(
            query, [h["content"] for h in hits], min(top_k, len(hits))
        )
    except Exception as exc:
        logger.warning("rerank 调用失败，降级为粗排原顺序：%s", exc)
        return RerankResult(hits[:top_k], False)

    return RerankResult(
        [{**hits[idx], "score": score} for idx, score in pairs], True
    )
