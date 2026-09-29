"""
问答编排服务（RAG 直答链路）
流程：gather_evidence（粗排门 → 精排 → 二次门，F8 起与 Agent 共用 evidence_service）
      → 构造 Prompt → 调 LLM → 拼装带来源的响应。
store / bm25 / llm / reranker 均通过参数注入，默认接真实实现；测试可传 Fake 对象零网络运行。
F9 Day 13：构造/检索/生成三段故障对称兜底为 mode="error"（HTTP 仍 200，业务错误态），
认证类错误给明确配置提示，其他 LLM 故障给通用不可用文案。
"""
import asyncio
import time

from app.schemas import ChatResponse, SourceOut
from app.services.evidence_service import (
    ERROR_MESSAGE,
    REJECT_MESSAGE_RAG,
    gather_evidence,
)
from app.services.llm_client import (
    AUTH_ERROR_MESSAGE,
    LLM_UNAVAILABLE_MESSAGE,
    create_chat_client,
    is_config_error,
)
from app.services.prompt_builder import build_messages


def _reject_response(started: float) -> ChatResponse:
    return ChatResponse(
        answer=REJECT_MESSAGE_RAG,
        sources=[],
        mode="reject",
        response_time=round(time.perf_counter() - started, 2),
    )


def _error_response(started: float, message: str,
                    sources: list[SourceOut] | None = None) -> ChatResponse:
    """业务错误态：HTTP 仍 200；生成阶段失败时证据来源照常带回"""
    return ChatResponse(
        answer=message,
        sources=sources or [],
        mode="error",
        response_time=round(time.perf_counter() - started, 2),
    )


async def answer_question(query: str, *, store=None, llm=None, bm25=None,
                          reranker=None, mode=None, doc_ids=None) -> ChatResponse:
    """回答单个问题。阻塞调用全部在线程池中处理，避免卡死事件循环。

    doc_ids 非空时只在指定文档范围内检索（Day 13++ 文档级圈选）。
    """
    started = time.perf_counter()

    try:
        # 统一构造入口（注入替身或真实客户端，构造失败归一 LLMConfigError）
        chat_llm = create_chat_client(llm)
    except Exception:
        # 真实客户端构造失败（缺/错 API Key 等）：统一认证配置文案
        return _error_response(started, AUTH_ERROR_MESSAGE)

    try:
        evidence = await gather_evidence(
            query, store=store, bm25=bm25, reranker=reranker, mode=mode,
            doc_ids=doc_ids,
        )
    except Exception:
        return _error_response(started, ERROR_MESSAGE)
    if not evidence.ok:
        return _reject_response(started)

    messages = build_messages(query, evidence.hits)
    sources = [
        SourceOut(
            filename=hit["filename"],
            chunk_index=hit["chunk_index"],
            snippet=hit["content"][:150],
            score=hit["score"],
            page=hit["page"],
        )
        for hit in evidence.hits
    ]

    try:
        answer = await asyncio.to_thread(chat_llm.generate, messages)
    except Exception as exc:
        # 证据已取到：错误只在生成阶段，sources 仍拼装返回
        message = (
            AUTH_ERROR_MESSAGE if is_config_error(exc) else LLM_UNAVAILABLE_MESSAGE
        )
        return _error_response(started, message, sources)

    return ChatResponse(
        answer=answer,
        sources=sources,
        mode="rag",
        response_time=round(time.perf_counter() - started, 2),
    )
