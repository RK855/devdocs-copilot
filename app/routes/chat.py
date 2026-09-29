"""问答接口：基于知识库回答用户问题
- POST /query：一次性 JSON（RAG 直答，Day 3 起，契约保持不变）
- POST /stream：SSE 流式（F9 Day 12，协议见设计文档 7.2）
"""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse
from app.services import chat_service, stream_service

router = APIRouter()


@router.post("/query", response_model=ChatResponse, summary="文档问答")
async def query_chat(req: ChatRequest):
    """检索知识库 Top-5 相关片段，交给 Agnes 生成带引用的回答；无相关内容则拒答。

    req.doc_ids 非空时只在指定文档范围内检索（Day 13++ 文档级圈选）。
    """
    return await chat_service.answer_question(req.query, doc_ids=req.doc_ids)


def _format_sse(event: stream_service.SSEEvent) -> str:
    """SSE 单帧编码：event 行 + JSON data 行 + 空行分隔（不转义中文）"""
    payload = json.dumps(event.data, ensure_ascii=False)
    return f"event: {event.event}\ndata: {payload}\n\n"


@router.post("/stream", summary="文档问答（SSE 流式）")
async def stream_chat(req: ChatRequest):
    """检索完成先发 meta/sources，正文逐块 delta；拒答与故障时序见设计文档 7.3"""
    async def event_generator():
        async for event in stream_service.stream_answer(
            req.query, doc_ids=req.doc_ids
        ):
            yield _format_sse(event).encode("utf-8")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
