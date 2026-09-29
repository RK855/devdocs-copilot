"""stream_service 事件流测试：FakeStore/FakeBM25/FakeStreamLLM 注入，零网络"""
import asyncio
from types import SimpleNamespace

import pytest
from openai import AuthenticationError

from app.config import settings
from app.db.bm25_store import bm25_store
from app.services import stream_service
from app.services.evidence_service import REJECT_MESSAGE_RAG
from app.services.llm_client import AUTH_ERROR_MESSAGE


def _hit(score=0.85, content="FastAPI 使用 uvicorn 启动开发服务器",
         filename="guide.md", page=None, idx=0, doc_id="doc"):
    return {
        "chunk_id": f"{doc_id}:chunk-{idx}",
        "content": content,
        "doc_id": doc_id,
        "filename": filename,
        "chunk_index": idx,
        "page": page,
        "score": score,
    }


class FakeStore:
    def __init__(self, hits, exc=None):
        self._hits = hits
        self._exc = exc
        self.scopes = []

    def query_similar(self, query_text, top_k=5, doc_ids=None):
        self.scopes.append(doc_ids)
        if self._exc is not None:
            raise self._exc
        return list(self._hits)


class FakeBM25:
    def __init__(self, hits=None):
        self._hits = hits or []
        self.scopes = []

    def search(self, query_text, top_k=20, doc_ids=None):
        self.scopes.append(doc_ids)
        return list(self._hits)


class FakeStreamLLM:
    """chunks 逐块 yield；connect_exc：进入生成器即抛；raise_after：产出 N 块后抛"""
    def __init__(self, chunks=("分段A", "分段B"), connect_exc=None, raise_after=None):
        self._chunks = list(chunks)
        self._connect_exc = connect_exc
        self._raise_after = raise_after
        self.calls = []

    def stream_generate(self, messages):
        self.calls.append(messages)
        if self._connect_exc is not None:
            raise self._connect_exc
        for index, text in enumerate(self._chunks):
            if self._raise_after is not None and index == self._raise_after:
                raise RuntimeError("上游连接中断")
            yield text


class FakeSyncIterator:
    """桥接专用：可观测 close() 的同步迭代器"""
    def __init__(self, items):
        self._items = list(items)
        self.i = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.i >= len(self._items):
            raise StopIteration
        value = self._items[self.i]
        self.i += 1
        return value

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_bm25_and_disable_rerank(monkeypatch):
    # 与 test_chat_service 一致：默认关精排，纯 RRF，零网络
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    bm25_store.clear()
    yield
    bm25_store.clear()


async def _collect(*, llm=None, hits=("hit",), query="怎么启动", store=None, bm25=None):
    if store is None:
        store = FakeStore([_hit()] if hits == ("hit",) else list(hits))
    kwargs = {"query": query, "store": store, "bm25": bm25 or FakeBM25()}
    if llm is not None:
        kwargs["llm"] = llm
    return [e async for e in stream_service.stream_answer(**kwargs)]


class TestSyncBridge:
    async def test_forwards_items_then_ends(self):
        iterator = FakeSyncIterator(["a", "b"])
        bridge = stream_service._SyncToAsync(lambda: iterator)
        bridge.start()

        assert [x async for x in bridge] == ["a", "b"]

    async def test_iteration_error_raised_to_async_side(self):
        class Boom(FakeSyncIterator):
            def __next__(self):
                if self.i == 1:
                    raise RuntimeError("boom")
                return super().__next__()

        bridge = stream_service._SyncToAsync(lambda: Boom(["a"]))
        bridge.start()

        with pytest.raises(RuntimeError, match="boom"):
            _ = [x async for x in bridge]

    async def test_cancel_closes_iterator_in_worker_thread(self):
        iterator = FakeSyncIterator(["a", "b", "c"])
        bridge = stream_service._SyncToAsync(lambda: iterator)
        bridge.start()
        agen = bridge.__aiter__()

        assert await agen.__anext__() == "a"
        bridge.cancel()
        bridge._thread.join(timeout=2)

        assert not bridge._thread.is_alive()
        assert iterator.closed is True


class TestNormalAnswer:
    async def test_event_sequence_meta_sources_deltas_done(self):
        llm = FakeStreamLLM(chunks=("运行 ", "uvicorn main:app"))
        events = await _collect(llm=llm)

        names = [e.event for e in events]
        assert names == ["meta", "sources", "delta", "delta", "done"]

        meta = events[0].data
        assert meta["mode"] == "rag"
        assert len(meta["response_id"]) == 12

        source = events[1].data[0]
        assert source["filename"] == "guide.md"
        assert source["chunk_index"] == 0
        assert source["snippet"] == "FastAPI 使用 uvicorn 启动开发服务器"
        assert source["page"] is None
        assert source["score"] >= 0

        deltas = "".join(e.data["text"] for e in events[2:-1])
        assert deltas == "运行 uvicorn main:app"
        assert events[-1].data["response_time"] >= 0

    async def test_llm_receives_built_messages(self):
        llm = FakeStreamLLM()
        await _collect(llm=llm)

        assert llm.calls[0][0]["role"] == "system"
        assert llm.calls[0][1] == {"role": "user", "content": "怎么启动"}

    async def test_doc_ids_reach_retrieval_channels(self):
        store, bm = FakeStore([_hit()]), FakeBM25()

        events = [
            e async for e in stream_service.stream_answer(
                "怎么启动", store=store, bm25=bm,
                llm=FakeStreamLLM(), doc_ids=["d1", "d2"],
            )
        ]

        assert events[0].data["mode"] == "rag"
        assert store.scopes == [["d1", "d2"]]
        assert bm.scopes == [["d1", "d2"]]


class TestReject:
    async def test_no_evidence_emits_reject_without_sources_or_llm(self):
        llm = FakeStreamLLM()
        events = await _collect(llm=llm, hits=[], query="红烧肉做法")

        names = [e.event for e in events]
        assert names == ["meta", "delta", "done"]
        assert events[0].data["mode"] == "reject"
        assert events[1].data == {"text": REJECT_MESSAGE_RAG}
        assert llm.calls == []


class _ClosableStream:
    """模拟真实 OpenAI 流：非生成器迭代器，close 可观测（worker 线程内调用）"""

    def __init__(self, items):
        self._it = iter(items)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        self.closed = True


class _ClosableStreamLLM:
    def __init__(self, items):
        self.stream = _ClosableStream(items)

    def stream_generate(self, messages):
        # 真实场景：返回的是 OpenAI Stream 对象（非生成器），close 必须在创建线程执行
        return self.stream


class TestDisconnectCleanup:
    async def test_aclose_after_delta_closes_upstream_in_worker_thread(self):
        """客户端断连：Starlette 在 yield 点向 async generator 抛 GeneratorExit，
        finally 必须投递 close，worker 在自己线程关闭上游 LLM 流"""
        llm = _ClosableStreamLLM(["a", "b", "c"])
        agen = stream_service.stream_answer(
            "怎么启动", store=FakeStore([_hit()]), bm25=FakeBM25(), llm=llm
        )

        assert (await agen.__anext__()).event == "meta"
        assert (await agen.__anext__()).event == "sources"
        assert (await agen.__anext__()).event == "delta"
        await agen.aclose()  # 模拟 StreamingResponse 在客户端断连后关闭迭代器

        # worker 收到 close 命令是异步的：轮询等待最多 1s
        for _ in range(50):
            if llm.stream.closed:
                break
            await asyncio.sleep(0.02)
        assert llm.stream.closed is True


class TestFailures:
    async def test_retrieval_pipeline_failure(self):
        llm = FakeStreamLLM()
        broken_store = FakeStore([_hit()], exc=RuntimeError("向量库炸了"))

        events = await _collect(llm=llm, store=broken_store)

        assert [e.event for e in events] == ["meta", "error"]
        assert events[0].data["mode"] == "error"
        assert events[1].data["code"] == "retrieval_failed"
        assert "message" in events[1].data
        assert llm.calls == []

    async def test_connect_failure_is_llm_unavailable(self):
        llm = FakeStreamLLM(connect_exc=RuntimeError("401 invalid api key"))

        events = await _collect(llm=llm)

        assert [e.event for e in events] == ["meta", "sources", "error"]
        assert events[-1].data["code"] == "llm_unavailable"
        assert "message" in events[-1].data

    async def test_connect_auth_error_uses_auth_message(self):
        # 401 认证错误：code 仍为三枚举之一的 llm_unavailable，message 换成认证文案
        auth_exc = AuthenticationError(
            "401",
            response=SimpleNamespace(status_code=401, request=None, headers={}),
            body=None,
        )
        llm = FakeStreamLLM(connect_exc=auth_exc)

        events = await _collect(llm=llm)

        assert [e.event for e in events] == ["meta", "sources", "error"]
        assert events[-1].data["code"] == "llm_unavailable"
        assert events[-1].data["message"] == AUTH_ERROR_MESSAGE

    async def test_mid_stream_failure_keeps_deltas_and_interrupts(self):
        llm = FakeStreamLLM(chunks=("A", "B", "C"), raise_after=2)

        events = await _collect(llm=llm)

        assert [e.event for e in events] == [
            "meta", "sources", "delta", "delta", "error"
        ]
        deltas = "".join(
            e.data["text"] for e in events if e.event == "delta"
        )
        assert deltas == "AB"
        assert events[-1].data["code"] == "stream_interrupted"
