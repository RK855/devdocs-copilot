"""Agent 问答接口：ReAct 循环自主多轮检索知识库作答（F8 Day 9）

- POST /query：一次性 JSON（契约保持不变）
- POST /stream：SSE 流式进度（Day 16），phase/tool_start/tool_end 实时推送，
  终态整包 done（与 /query 的 AgentChatResponse 完全同构）
"""
import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest
from app.services import agent_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query", summary="Agent 文档问答")
async def query_agent(req: ChatRequest):
    """Agent 通过 function calling 自主检索（可多轮换词）后作答；全程无证据则拒答。

    req.doc_ids 非空时每一步检索都限制在指定文档范围内（Day 13++ 文档级圈选）。
    req.allow_general=True 时，库内确无内容后用模型通用知识兜底，mode="general"（Day 14）。
    """
    return await agent_service.run_agent(
        req.query,
        doc_ids=req.doc_ids,
        allow_general=req.allow_general,
    )


def _format_sse(event: str, data: dict) -> bytes:
    """SSE 单帧编码：event 行 + JSON data 行 + 空行分隔（不转义中文）"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


# 业务管线故障（含工具全失败）已由 run_agent 收敛为 done.mode=error；
# 仅编排层逃逸的意外异常才走 error 事件，code 沿用既有枚举不新增
_STREAM_INTERRUPTED = {"code": "stream_interrupted", "message": "回答中断，请重试。"}


@router.post("/stream", summary="Agent 文档问答（SSE 流式进度）")
async def stream_agent(req: ChatRequest):
    """边执行边推执行轨迹（当前轮次/工具名/查询词/成败），终态整包 done。

    事件序列：phase(thinking) → [tool_start → tool_end → phase(thinking)]*
              → [phase(answering)]? → done；done.data 即完整 AgentChatResponse。
    """

    async def event_generator():
        # run_agent 在独立任务里跑，进度经队列桥接给 SSE 生成器；
        # 客户端断连时 finally 取消任务，及时停止后续轮次的上游调用
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        async def on_event(event: dict) -> None:
            await queue.put(("event", event))

        async def drive() -> None:
            try:
                resp = await agent_service.run_agent(
                    req.query,
                    doc_ids=req.doc_ids,
                    allow_general=req.allow_general,
                    on_event=on_event,
                )
                await queue.put(("done", resp.model_dump()))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Agent SSE 编排异常")
                await queue.put(("fatal", None))
            finally:
                await queue.put(sentinel)

        task = asyncio.create_task(drive())
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                kind, payload = item
                if kind == "done":
                    yield _format_sse("done", payload)
                elif kind == "fatal":
                    yield _format_sse("error", _STREAM_INTERRUPTED)
                elif payload["type"] == "round_start":
                    yield _format_sse(
                        "phase", {"phase": "thinking", "round": payload["round"]}
                    )
                elif payload["type"] == "tool_start":
                    yield _format_sse("tool_start", {
                        "step": payload["step"],
                        "tool": payload["tool"],
                        "arguments": payload["arguments"],
                        "cached": payload["cached"],
                    })
                elif payload["type"] == "tool_end":
                    yield _format_sse("tool_end", payload["step"])
                elif payload["type"] == "phase":
                    yield _format_sse("phase", {"phase": payload["phase"]})
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
