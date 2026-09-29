"""
流式问答编排服务（F9 Day 12）
与 chat_service 并列、互不引用：证据管线复用 gather_evidence，正文经 LLM 流式接口
逐块产出；对外只产 SSEEvent 事件对象，不碰 HTTP 与字节编码。
同步 OpenAI 客户端用单 worker daemon 线程桥接：流在 worker 线程内创建、迭代、关闭。
llm/store/bm25/reranker 构造注入，测试传 Fake 零网络。
"""
import asyncio
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from app.schemas import SourceOut
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

# 流式特有文案；检索管线故障沿用 evidence_service.ERROR_MESSAGE；
# LLM 不可用/认证文案统一由 llm_client 提供（与非流式、Agent 共用）
STREAM_INTERRUPTED_MESSAGE = "回答中断，已保留已接收内容，请重试。"


@dataclass
class SSEEvent:
    """一条 SSE 事件：event 为事件名，data 为可 JSON 序列化的 dict/list"""
    event: str
    data: Any


def _sources_payload(hits: list[dict]) -> list[dict]:
    """hits → sources 事件 payload，字段与非流式 SourceOut 完全一致"""
    return [
        SourceOut(
            filename=hit["filename"],
            chunk_index=hit["chunk_index"],
            snippet=hit["content"][:150],
            score=hit["score"],
            page=hit["page"],
        ).model_dump()
        for hit in hits
    ]


class _SyncToAsync:
    """同步迭代器 → async 迭代器的单 worker 线程桥（命令队列驱动）。

    - 迭代器在 worker 线程内创建与迭代（OpenAI 同步流的创建/关闭需同线程归属）；
    - 双队列：async 侧发 next 命令、worker 回 item/error/end；块间 worker 待命在
      命令队列上，cancel() 发 close 即可在 worker 线程立即关闭（生成器 GeneratorExit
      触发底层流 .close()），取消在"块间等待"态确定性生效；
    - 若 worker 恰好阻塞在某块的网络读取中，close 命令排队，最迟该块返回或读超时后
      执行（daemon 线程，不挂进程）。
    """

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._cmds: queue.Queue = queue.Queue()
        self._outs: queue.Queue = queue.Queue()
        self._close_sent = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            iterator = self._factory()
        except Exception as exc:
            # 工厂阶段失败（生成器函数体内 create() 抛出走下方 next 分支）
            self._outs.put(("error", exc))
            return
        while True:
            command = self._cmds.get()
            if command == "close":
                try:
                    iterator.close()  # 必须在创建它的 worker 线程内执行
                except Exception:
                    pass
                self._outs.put(("closed", None))
                return
            try:
                item = next(iterator)
            except StopIteration:
                self._outs.put(("end", None))
                return
            except Exception as exc:
                self._outs.put(("error", exc))
                return
            self._outs.put(("item", item))

    async def __aiter__(self) -> AsyncIterator[Any]:
        loop = asyncio.get_running_loop()
        while True:
            self._cmds.put("next")
            kind, payload = await loop.run_in_executor(None, self._outs.get)
            if kind == "item":
                yield payload
            elif kind == "error":
                raise payload
            else:  # end / closed
                return

    def cancel(self) -> None:
        if not self._close_sent:
            self._close_sent = True
            self._cmds.put("close")


async def stream_answer(
    query: str, *, store=None, llm=None, bm25=None, reranker=None, mode=None,
    doc_ids=None,
) -> AsyncIterator[SSEEvent]:
    """RAG 流式问答，事件顺序见设计文档 7.3 时序矩阵。

    doc_ids 非空时只在指定文档范围内检索（Day 13++ 文档级圈选）。
    """
    started = time.perf_counter()
    response_id = uuid.uuid4().hex[:12]

    def done_event() -> SSEEvent:
        return SSEEvent(
            "done",
            {"response_time": round(time.perf_counter() - started, 2)},
        )

    # 0. 客户端构造（真实构造失败=缺/错 API Key 等）：在发任何正常 meta 前兜住，
    #    只发 error 态 meta + error 事件；code 沿用 llm_unavailable，靠 message 区分
    try:
        chat_llm = create_chat_client(llm)
    except Exception as exc:
        message = (
            AUTH_ERROR_MESSAGE if is_config_error(exc) else LLM_UNAVAILABLE_MESSAGE
        )
        yield SSEEvent("meta", {"mode": "error", "response_id": response_id})
        yield SSEEvent(
            "error", {"code": "llm_unavailable", "message": message}
        )
        return

    # 1. 证据采集（与 /query、Agent 同一管线）；管线自身炸 → retrieval_failed
    try:
        evidence = await gather_evidence(
            query, store=store, bm25=bm25, reranker=reranker, mode=mode,
            doc_ids=doc_ids,
        )
    except Exception:
        yield SSEEvent("meta", {"mode": "error", "response_id": response_id})
        yield SSEEvent(
            "error", {"code": "retrieval_failed", "message": ERROR_MESSAGE}
        )
        return

    # 2. 证据门不过：拒答话术整一条 delta，不调 LLM
    if not evidence.ok:
        yield SSEEvent("meta", {"mode": "reject", "response_id": response_id})
        yield SSEEvent("delta", {"text": REJECT_MESSAGE_RAG})
        yield done_event()
        return

    # 3. 正常作答：来源严格先于正文
    messages = build_messages(query, evidence.hits)
    yield SSEEvent("meta", {"mode": "rag", "response_id": response_id})
    yield SSEEvent("sources", _sources_payload(evidence.hits))

    bridge = _SyncToAsync(lambda: chat_llm.stream_generate(messages))
    bridge.start()
    delta_count = 0
    try:
        async for piece in bridge:
            delta_count += 1
            yield SSEEvent("delta", {"text": piece})
    except Exception as exc:
        # 零 delta 失败=建连失败；已有 delta 后失败=吐字中途断流（已吐内容不收回）
        if delta_count == 0:
            message = (
                AUTH_ERROR_MESSAGE if is_config_error(exc) else LLM_UNAVAILABLE_MESSAGE
            )
            yield SSEEvent(
                "error",
                {"code": "llm_unavailable", "message": message},
            )
        else:
            yield SSEEvent(
                "error",
                {"code": "stream_interrupted", "message": STREAM_INTERRUPTED_MESSAGE},
            )
        return
    finally:
        # 客户端断连（Starlette 在 yield 点抛 GeneratorExit）/任务取消
        # （CancelledError）/异常/正常收尾，任何退出路径都投递关闭，
        # 由 worker 在创建流的线程内 close 上游 LLM 连接，及时停止计费与读取。
        bridge.cancel()

    yield done_event()
