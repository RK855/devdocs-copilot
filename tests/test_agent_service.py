"""agent_service 测试：脚本化 Fake LLM + 桩证据管线，全程零网络"""
import json
import logging
from types import SimpleNamespace

import pytest
from openai import AuthenticationError
from pydantic import ValidationError

from app.schemas import AgentChatResponse, AgentStep
from app.services import agent_service
from app.services.evidence_service import Evidence
from app.services.llm_client import AUTH_ERROR_MESSAGE, ChatTurn, ToolCall


def _auth_error():
    return AuthenticationError(
        "401",
        response=SimpleNamespace(status_code=401, request=None, headers={}),
        body=None,
    )


def _hit(chunk_id, *, score=0.9, filename="fastapi.md",
         content="FastAPI 使用 uvicorn main:app 启动"):
    return {
        "chunk_id": chunk_id, "filename": filename, "chunk_index": 0,
        "content": content, "score": score, "page": None,
    }


def _turn(*calls, content=""):
    return ChatTurn(content=content, tool_calls=list(calls))


def _call(call_id, name, arguments):
    return ToolCall(id=call_id, name=name, arguments=arguments)


class FakeAgentLLM:
    """chat() 按脚本依次返回（元素为异常则抛出），末个结果持续生效"""

    def __init__(self, outcomes, final_text="【部分回答】基于已有资料整理如下。",
                 generate_exc=None):
        self._outcomes = outcomes
        self.chat_log = []
        self.generate_log = []
        self._final_text = final_text
        self._generate_exc = generate_exc

    def chat(self, messages, *, tools=None):
        self.chat_log.append({"messages": list(messages), "tools": tools})
        outcome = self._outcomes[min(len(self.chat_log) - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def generate(self, messages):
        self.generate_log.append(list(messages))
        if self._generate_exc is not None:
            raise self._generate_exc
        return self._final_text


class FakePlainLLM:
    """只服务 _generate_general_answer：脚本化 generate 返回值"""

    def __init__(self, text="通用知识答案正文"):
        self.text = text
        self.log = []

    def generate(self, messages):
        self.log.append(list(messages))
        return self.text


class TestGeneralKnowledgeHelper:
    async def test_prepends_disclaimer_and_switches_system_prompt(self):
        llm = FakePlainLLM("Celery 是分布式任务队列。")

        text, exc = await agent_service._generate_general_answer(llm, "Celery 是什么")

        assert exc is None
        assert text.startswith(agent_service.GENERAL_DISCLAIMER)
        assert "Celery 是分布式任务队列" in text
        # 提示词已切换为通用知识模式，用户原问题原样保留
        assert llm.log[0][0]["role"] == "system"
        assert llm.log[0][0]["content"] == agent_service.GENERAL_KNOWLEDGE_PROMPT
        assert llm.log[0][1]["role"] == "user"
        assert llm.log[0][1]["content"] == "Celery 是什么"

    async def test_keeps_disclaimer_when_model_emits_it(self):
        full = agent_service.GENERAL_DISCLAIMER + "\n\n正文内容"
        llm = FakePlainLLM(full)

        text, exc = await agent_service._generate_general_answer(llm, "q")

        assert exc is None
        assert text == full  # 模型已带声明则不重复拼接

    async def test_empty_text_returns_exception(self):
        llm = FakePlainLLM("   ")

        text, exc = await agent_service._generate_general_answer(llm, "q")

        assert text == ""
        assert isinstance(exc, Exception)

    async def test_generate_exception_propagated_as_tuple(self):
        class BoomLLM:
            def generate(self, messages):
                raise RuntimeError("上游 500")

        text, exc = await agent_service._generate_general_answer(BoomLLM(), "q")

        assert text == ""
        assert isinstance(exc, RuntimeError)


@pytest.fixture
def stub_evidence(monkeypatch):
    """桩掉 gather_evidence：按 query 精确返回预设 Evidence，记录每次入参"""

    class Stub:
        def __init__(self):
            self.map = {}
            self.calls = []

        async def __call__(self, query, *, top_k=None, **kwargs):
            self.calls.append({"query": query, "top_k": top_k, "kwargs": kwargs})
            return self.map[query]

    stub = Stub()
    monkeypatch.setattr(agent_service, "gather_evidence", stub)
    return stub


class TestSearchDocsTool:
    async def test_hit_returns_numbered_text_and_passes_top_k(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}
        tool = agent_service.SearchDocsTool()

        result = await tool.arun(
            agent_service.SearchDocsArgs(query="q", top_k=3),
            agent_service.AgentContext(),
        )

        assert result.ok is True
        assert "[1] (来源: fastapi.md)" in result.text
        assert result.hits[0]["chunk_id"] == "c1"
        assert stub_evidence.calls[0]["top_k"] == 3

    async def test_scope_doc_ids_passed_to_evidence(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}

        result = await agent_service.SearchDocsTool().arun(
            agent_service.SearchDocsArgs(query="q"),
            agent_service.AgentContext(doc_ids=["d1", "d2"]),
        )

        assert result.ok is True
        assert stub_evidence.calls[0]["kwargs"]["doc_ids"] == ["d1", "d2"]

    async def test_no_evidence_returns_retry_hint(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[], ok=False, scored=False)}

        result = await agent_service.SearchDocsTool().arun(
            agent_service.SearchDocsArgs(query="q"),
            agent_service.AgentContext(),
        )
        assert result.ok is False
        assert result.hits == []
        assert "更换关键词" in result.text

    def test_args_constraints(self):
        assert agent_service.SearchDocsArgs(query="q").top_k == 5
        with pytest.raises(ValidationError):
            agent_service.SearchDocsArgs(query="")
        with pytest.raises(ValidationError):
            agent_service.SearchDocsArgs(query="q", top_k=0)
        with pytest.raises(ValidationError):
            agent_service.SearchDocsArgs(query="q", top_k=11)

    def test_spec_openai_function_shape(self):
        spec = agent_service.SearchDocsTool().spec()

        assert spec["type"] == "function"
        assert spec["function"]["name"] == "search_docs"
        assert "query" in spec["function"]["parameters"]["properties"]
        assert "top_k" in spec["function"]["parameters"]["properties"]


class TestToolRegistry:
    def test_openai_schema_lists_registered_tools(self):
        registry = agent_service.ToolRegistry()
        registry.register(agent_service.SearchDocsTool())

        schemas = registry.openai_schema()

        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "search_docs"

    async def test_unknown_tool_returns_invalid_result(self):
        registry = agent_service.ToolRegistry()

        result = await registry.arun("nope", {}, agent_service.AgentContext())

        assert result.ok is False
        assert result.invalid_args is True
        assert "未知工具" in result.text

    async def test_validation_failure_feedback_without_running_tool(
        self, stub_evidence
    ):
        registry = agent_service.ToolRegistry()
        registry.register(agent_service.SearchDocsTool())

        result = await registry.arun(
            "search_docs", {"query": ""}, agent_service.AgentContext()
        )

        assert result.invalid_args is True
        assert "参数校验失败" in result.text
        assert stub_evidence.calls == []


class TestReactLoopCore:
    async def test_model_answers_without_searching_gets_rejected(self, stub_evidence):
        llm = FakeAgentLLM([_turn(content="我不检索直接编一个")])

        resp = await agent_service.run_agent("随便问", llm=llm)

        assert resp.mode == "reject"
        assert resp.answer == agent_service.REJECT_MESSAGE
        # Agent 已穷尽多轮换词，拒答文案不得再引导"切换 Agent"
        assert "AGENT" not in resp.answer
        assert resp.sources == []
        assert resp.steps == []

    async def test_single_search_then_final_answer(self, stub_evidence):
        stub_evidence.map = {
            "怎么启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("call_1", "search_docs",
                        {"query": "怎么启动", "top_k": 5})),
            _turn(content="用 `uvicorn main:app` 启动。"),
        ])

        resp = await agent_service.run_agent("怎么启动", llm=llm)

        assert resp.mode == "agent"
        assert "uvicorn main:app" in resp.answer
        assert len(resp.steps) == 1
        assert resp.steps[0].step == 1
        assert resp.steps[0].tool == "search_docs"
        assert resp.steps[0].result_count == 1
        assert resp.steps[0].cached is False
        assert resp.sources[0].filename == "fastapi.md"
        assert resp.response_time >= 0

    async def test_multi_round_refetch_accumulates_sources(self, stub_evidence):
        stub_evidence.map = {
            "启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
            "热重载": Evidence(hits=[_hit("c2", filename="reload.md")],
                               ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "启动"})),
            _turn(_call("c2", "search_docs", {"query": "热重载"})),
            _turn(content="开发时加 --reload。"),
        ])

        resp = await agent_service.run_agent("启动和热重载", llm=llm)

        assert resp.mode == "agent"
        assert [s.step for s in resp.steps] == [1, 2]
        assert [s.result_count for s in resp.steps] == [1, 1]
        assert [s.filename for s in resp.sources] == ["fastapi.md", "reload.md"]

    async def test_all_searches_empty_unified_reject(self, stub_evidence):
        stub_evidence.map = {
            "红烧肉": Evidence(hits=[], ok=False, scored=False),
            "糖醋排骨": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "红烧肉"})),
            _turn(_call("c2", "search_docs", {"query": "糖醋排骨"})),
            _turn(content="文档里确实没有，我不该编。"),
        ])

        resp = await agent_service.run_agent("红烧肉怎么做", llm=llm)

        assert resp.mode == "reject"
        assert resp.answer == agent_service.REJECT_MESSAGE
        assert resp.sources == []
        assert len(resp.steps) == 2


class TestReactCacheAndDedup:
    async def test_same_args_second_call_is_cached(self, stub_evidence):
        stub_evidence.map = {
            "启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "启动", "top_k": 5})),
            _turn(_call("c2", "search_docs", {"query": "启动", "top_k": 5})),
            _turn(content="ok"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert len(stub_evidence.calls) == 1
        assert resp.steps[0].cached is False
        assert resp.steps[1].cached is True
        assert resp.steps[1].result_count == 1

    async def test_different_args_are_not_cached(self, stub_evidence):
        stub_evidence.map = {
            "启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "启动", "top_k": 5})),
            _turn(_call("c2", "search_docs", {"query": "启动", "top_k": 3})),
            _turn(content="ok"),
        ])

        await agent_service.run_agent("q", llm=llm)

        assert [c["top_k"] for c in stub_evidence.calls] == [5, 3]

    async def test_sources_deduped_by_chunk_id_score_max_preserve_order(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "a": Evidence(hits=[
                _hit("c1", score=0.50, content="片段一内容"),
                _hit("c2", score=0.80, content="片段二内容"),
            ], ok=True, scored=True),
            "b": Evidence(hits=[
                _hit("c2", score=0.95, content="片段二内容"),
                _hit("c3", score=0.70, filename="x.md", content="片段三内容"),
            ], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "a"})),
            _turn(_call("c2", "search_docs", {"query": "b"})),
            _turn(content="ok"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        # c1、c2、c3 首次出现顺序保留；c2 跨步骤取最高分 0.95
        assert [s.snippet for s in resp.sources] == [
            "片段一内容", "片段二内容", "片段三内容",
        ]
        assert len(resp.sources) == 3
        c2 = [s for s in resp.sources if s.snippet == "片段二内容"][0]
        assert c2.score == 0.95

    async def test_parallel_tool_calls_share_step_and_pair_messages(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "a": Evidence(hits=[_hit("c1")], ok=True, scored=True),
            "b": Evidence(hits=[_hit("c2", filename="x.md")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(
                _call("c1", "search_docs", {"query": "a"}),
                _call("c2", "search_docs", {"query": "b"}),
            ),
            _turn(content="ok"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert [s.step for s in resp.steps] == [1, 1]
        # 第二轮对话里：assistant tool_calls 与两条 tool 消息配对、id 对应
        next_round_msgs = llm.chat_log[1]["messages"]
        assistant_msg = [m for m in next_round_msgs if m["role"] == "assistant"][0]
        tool_msgs = [m for m in next_round_msgs if m["role"] == "tool"]
        assert {tc["id"] for tc in assistant_msg["tool_calls"]} == {"c1", "c2"}
        assert {m["tool_call_id"] for m in tool_msgs} == {"c1", "c2"}
        # 每轮 chat 都收到 tools schema
        assert all(log["tools"] and log["tools"][0]["function"]["name"]
                   == "search_docs" for log in llm.chat_log)

    async def test_context_dependencies_are_passed_through(self, stub_evidence):
        sentinel_store, sentinel_bm25, sentinel_reranker = object(), object(), object()
        stub_evidence.map = {
            "q": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="ok"),
        ])

        await agent_service.run_agent(
            "q", llm=llm, store=sentinel_store, bm25=sentinel_bm25,
            reranker=sentinel_reranker, mode="hybrid",
        )

        kwargs = stub_evidence.calls[0]["kwargs"]
        assert kwargs["store"] is sentinel_store
        assert kwargs["bm25"] is sentinel_bm25
        assert kwargs["reranker"] is sentinel_reranker
        assert kwargs["mode"] == "hybrid"

    async def test_doc_ids_are_carried_into_agent_context(self, stub_evidence):
        stub_evidence.map = {
            "q": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="ok"),
        ])

        await agent_service.run_agent("q", llm=llm, doc_ids=["d7", "d8"])

        assert stub_evidence.calls[0]["kwargs"]["doc_ids"] == ["d7", "d8"]


class TestReactGuards:
    async def test_pydantic_validation_error_fed_back_then_self_correct(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("bad", "search_docs", {"query": ""})),
            _turn(_call("good", "search_docs", {"query": "启动"})),
            _turn(content="答案"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert [c["query"] for c in stub_evidence.calls] == ["启动"]
        tool_msgs = [m for m in llm.chat_log[1]["messages"]
                     if m["role"] == "tool"]
        assert "参数校验失败" in tool_msgs[0]["content"]
        assert tool_msgs[0]["tool_call_id"] == "bad"
        assert resp.steps[0].result_count == 0
        assert resp.steps[0].cached is False

    async def test_unparseable_json_fed_back_and_loop_continues(self, stub_evidence):
        from app.services.llm_client import ToolArgumentsParseError

        stub_evidence.map = {
            "启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            ToolArgumentsParseError("工具 search_docs 的参数不是合法 JSON"),
            _turn(_call("good", "search_docs", {"query": "启动"})),
            _turn(content="答案"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "agent"
        user_msgs = [m for m in llm.chat_log[1]["messages"]
                     if m["role"] == "user"]
        assert "无法被解析" in user_msgs[-1]["content"]

    async def test_tool_exception_fed_back_without_crashing(self, monkeypatch):
        class FlakyEvidence:
            def __init__(self):
                self.calls = []

            async def __call__(self, query, *, top_k=None, **kwargs):
                self.calls.append(query)
                if query == "炸":
                    raise RuntimeError("检索服务炸了")
                return Evidence(hits=[_hit("c1")], ok=True, scored=True)

        flaky = FlakyEvidence()
        monkeypatch.setattr(agent_service, "gather_evidence", flaky)
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "炸"})),
            _turn(_call("c2", "search_docs", {"query": "启动"})),
            _turn(content="答案"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "agent"
        tool_msgs = [m for m in llm.chat_log[1]["messages"]
                     if m["role"] == "tool"]
        assert "执行异常" in tool_msgs[0]["content"]
        assert flaky.calls == ["炸", "启动"]

    async def test_max_steps_forces_tool_free_finalization(self, stub_evidence,
                                                           monkeypatch):
        monkeypatch.setattr(agent_service.settings, "AGENT_MAX_STEPS", 2)
        stub_evidence.map = {
            "q": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(_call("c2", "search_docs", {"query": "q"})),  # 第二轮仍要调
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert len(llm.chat_log) == 2          # 第三轮不再带 tools 询问
        assert len(llm.generate_log) == 1      # 改为无工具收尾调用
        hint_msgs = [m for m in llm.generate_log[0] if m["role"] == "user"]
        assert "最大次数" in hint_msgs[-1]["content"]
        assert resp.mode == "agent"
        assert resp.answer.startswith("【部分回答】")

    async def test_max_steps_without_evidence_rejects_without_generate(
        self, stub_evidence, monkeypatch
    ):
        monkeypatch.setattr(agent_service.settings, "AGENT_MAX_STEPS", 1)
        stub_evidence.map = {
            "q": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "reject"
        assert llm.generate_log == []

    async def test_blank_final_content_triggers_fallback_generation(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "q": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="   "),  # 模型有证据却吐空正文
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "agent"
        assert len(llm.generate_log) == 1
        assert resp.answer.startswith("【部分回答】")


class TestAgentContextAndToolResult:
    def test_add_hits_dedups_by_chunk_id_and_preserves_order(self):
        ctx = agent_service.AgentContext()
        ctx.add_hits([_hit("c1"), _hit("c2", score=0.5)])
        ctx.add_hits([_hit("c2", score=0.99), _hit("c3")])

        assert [h["chunk_id"] for h in ctx.hits_seen] == ["c1", "c2", "c3"]
        # 首次出现优先：重复 chunk_id 保留第一次的 score
        assert ctx.hits_seen[1]["score"] == 0.5

    def test_tool_result_new_fields_default(self):
        result = agent_service.ToolResult(ok=True, text="x")

        assert result.cacheable is True
        assert result.produces_answer is False


class TestGenerateCodeExampleTool:
    def test_args_constraints(self):
        args = agent_service.GenerateCodeExampleArgs(task="写个健康检查接口")
        assert args.framework == "fastapi"
        with pytest.raises(ValidationError):
            agent_service.GenerateCodeExampleArgs(task="")
        with pytest.raises(ValidationError):
            agent_service.GenerateCodeExampleArgs(task="x", framework="flask")

    async def test_refuses_without_prior_search_and_not_cacheable(self):
        class _LLM:
            def __init__(self):
                self.generate_log = []

            def generate(self, messages):
                self.generate_log.append(messages)
                return "不应被调用"

        llm = _LLM()
        result = await agent_service.GenerateCodeExampleTool().arun(
            agent_service.GenerateCodeExampleArgs(task="写个启动示例"),
            agent_service.AgentContext(llm=llm),
        )

        assert result.ok is False
        assert result.cacheable is False
        assert "search_docs" in result.text
        assert llm.generate_log == []  # 接地不满足时绝不调 LLM

    async def test_generates_grounded_code_from_accumulated_hits(self):
        class _LLM:
            def __init__(self):
                self.generate_log = []

            def generate(self, messages):
                self.generate_log.append(messages)
                return "```python\nimport uvicorn\n```"

        llm = _LLM()
        ctx = agent_service.AgentContext(llm=llm)
        ctx.add_hits([_hit("c1", content="用 uvicorn main:app 启动服务")])

        result = await agent_service.GenerateCodeExampleTool().arun(
            agent_service.GenerateCodeExampleArgs(task="写个启动示例"), ctx
        )

        assert result.ok is True
        assert "uvicorn" in result.text
        sent = llm.generate_log[0]
        assert sent[0]["role"] == "system"
        assert "fastapi" in sent[0]["content"]
        user_content = sent[1]["content"]
        assert "[1] (来源: fastapi.md)" in user_content
        assert "写个启动示例" in user_content

    def test_spec_openai_function_shape(self):
        spec = agent_service.GenerateCodeExampleTool().spec()

        assert spec["type"] == "function"
        assert spec["function"]["name"] == "generate_code_example"
        assert "task" in spec["function"]["parameters"]["properties"]
        assert "framework" in spec["function"]["parameters"]["properties"]


class TestExplainErrorTool:
    def test_args_requires_non_empty_error(self):
        with pytest.raises(ValidationError):
            agent_service.ExplainErrorArgs(error_message="")

    async def test_analyzes_without_hits_and_marks_produces_answer(self):
        class _LLM:
            def __init__(self):
                self.generate_log = []

            def generate(self, messages):
                self.generate_log.append(messages)
                return "原因：端口被占用。"

        llm = _LLM()
        result = await agent_service.ExplainErrorTool().arun(
            agent_service.ExplainErrorArgs(error_message="Address already in use"),
            agent_service.AgentContext(llm=llm),
        )

        assert result.ok is True
        assert result.produces_answer is True
        assert "端口被占用" in result.text
        user_content = llm.generate_log[0][1]["content"]
        assert "Address already in use" in user_content
        assert "知识库相关资料" not in user_content  # 零资料时不注入资料区块

    async def test_includes_evidence_when_hits_seen(self):
        class _LLM:
            def __init__(self):
                self.generate_log = []

            def generate(self, messages):
                self.generate_log.append(messages)
                return "依据资料：用 --port 换端口。"

        llm = _LLM()
        ctx = agent_service.AgentContext(llm=llm)
        ctx.add_hits([_hit("c1", content="用 --port 8080 指定其他端口")])

        await agent_service.ExplainErrorTool().arun(
            agent_service.ExplainErrorArgs(error_message="端口占用"), ctx
        )

        assert "[1] (来源: fastapi.md)" in llm.generate_log[0][1]["content"]


class TestReactWithContentTools:
    def test_default_registry_lists_three_tools_in_order(self):
        names = [
            t["function"]["name"]
            for t in agent_service._default_registry().openai_schema()
        ]
        assert names == ["search_docs", "generate_code_example", "explain_error"]

    async def test_search_then_code_tool_full_loop(self, stub_evidence):
        stub_evidence.map = {
            "q": Evidence(
                hits=[_hit("c1", content="用 Query(default=...) 声明查询参数")],
                ok=True, scored=True,
            ),
        }
        llm = FakeAgentLLM([
            _turn(_call("s1", "search_docs", {"query": "q"})),
            _turn(_call("g1", "generate_code_example",
                        {"task": "写个查询参数示例"})),
            _turn(content="```python\n@app.get('/')\n```"),
        ])

        resp = await agent_service.run_agent("查询参数", llm=llm)

        assert resp.mode == "agent"
        assert [s.tool for s in resp.steps] == [
            "search_docs", "generate_code_example",
        ]
        assert [s.result_count for s in resp.steps] == [1, 0]
        assert len(llm.generate_log) == 1  # 仅代码工具内部一次 LLM 调用
        assert "写个查询参数示例" in llm.generate_log[0][1]["content"]
        assert resp.sources[0].filename == "fastapi.md"
        assert resp.answer == "```python\n@app.get('/')\n```"

    async def test_grounding_refusal_not_cached_runs_after_search(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "q": Evidence(hits=[_hit("c1", content="Query 用法")],
                          ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("g1", "generate_code_example", {"task": "示例"})),
            _turn(_call("s1", "search_docs", {"query": "q"})),
            _turn(_call("g2", "generate_code_example", {"task": "示例"})),
            _turn(content="最终代码答案"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert [s.tool for s in resp.steps] == [
            "generate_code_example", "search_docs", "generate_code_example",
        ]
        assert [s.cached for s in resp.steps] == [False, False, False]
        assert len(llm.generate_log) == 1  # 第一次拒绝不执行；检索后同参真执行一次
        assert resp.answer == "最终代码答案"

    async def test_explain_error_with_zero_hits_allows_answer(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "e": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("s1", "search_docs", {"query": "e"})),
            _turn(_call("x1", "explain_error",
                        {"error_message": "ValueError: x"})),
            _turn(content="通用排查：先检查入参类型。"),
        ])

        resp = await agent_service.run_agent("报错", llm=llm)

        assert resp.mode == "agent"
        assert resp.sources == []
        assert resp.answer == "通用排查：先检查入参类型。"
        assert [s.result_count for s in resp.steps] == [0, 0]
        assert len(llm.generate_log) == 1  # 仅 explain 工具内部一次；终答走 chat

    async def test_max_steps_with_content_tool_forces_finalization(
        self, stub_evidence, monkeypatch
    ):
        monkeypatch.setattr(agent_service.settings, "AGENT_MAX_STEPS", 1)
        stub_evidence.map = {
            "e": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("x1", "explain_error",
                        {"error_message": "ValueError: x"})),
        ])

        resp = await agent_service.run_agent("报错", llm=llm)

        assert resp.mode == "agent"
        # explain 内部 1 次 + 超步无工具收尾 1 次
        assert len(llm.generate_log) == 2
        assert "最大次数" in llm.generate_log[1][-1]["content"]
        assert resp.answer.startswith("【部分回答】")

    async def test_blank_final_without_hits_falls_back_on_history(
        self, stub_evidence
    ):
        stub_evidence.map = {
            "e": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("s1", "search_docs", {"query": "e"})),
            _turn(_call("x1", "explain_error",
                        {"error_message": "ValueError"})),
            _turn(content="   "),
        ])

        resp = await agent_service.run_agent("报错", llm=llm)

        assert resp.mode == "agent"
        assert len(llm.generate_log) == 2  # explain 1 次 + 空正文兜底 1 次
        # 兜底沿用 ReAct 历史（含 tool 观察），不构造空资料 Prompt
        assert any(m["role"] == "tool" for m in llm.generate_log[1])


class TestDay11Contract:
    """Day 11：steps 三态 + mode 三态 + degraded（设计 6.6.2）"""

    def test_agent_step_new_fields_default(self):
        step = AgentStep(
            step=1, tool="search_docs", arguments={},
            result_count=0, cached=False,
        )

        assert step.status == "ok"      # 旧响应形状的默认值
        assert step.error is None

    def test_agent_response_mode_error_and_degraded_default(self):
        resp = AgentChatResponse(
            answer="检索服务暂时异常，请稍后重试。",
            sources=[], mode="error", response_time=0.2, steps=[],
        )

        assert resp.mode == "error"
        assert resp.degraded is False

        ok = AgentChatResponse(
            answer="x", sources=[], mode="agent",
            response_time=0.1, steps=[], degraded=True,
        )
        assert ok.degraded is True


class TestDay11ToolStatus:
    """Day 11：工具结果三态 ok/empty/error（设计 6.6.3）"""

    async def test_search_zero_hit_is_empty_not_error(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[], ok=False, scored=False)}

        result = await agent_service.SearchDocsTool().arun(
            agent_service.SearchDocsArgs(query="q"),
            agent_service.AgentContext(),
        )

        assert result.ok is False
        assert result.status == "empty"
        assert result.error is None

    async def test_search_hit_is_ok(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}

        result = await agent_service.SearchDocsTool().arun(
            agent_service.SearchDocsArgs(query="q"),
            agent_service.AgentContext(),
        )

        assert result.status == "ok"

    async def test_unknown_tool_is_error_with_short_reason(self):
        registry = agent_service.ToolRegistry()

        result = await registry.arun("nope", {}, agent_service.AgentContext())

        assert result.status == "error"
        assert result.invalid_args is True
        assert "nope" in result.error

    async def test_validation_failure_is_error(self):
        registry = agent_service.ToolRegistry()
        registry.register(agent_service.SearchDocsTool())

        result = await registry.arun(
            "search_docs", {"query": ""}, agent_service.AgentContext()
        )

        assert result.status == "error"
        assert result.error  # 有短因

    async def test_grounding_refusal_is_error_not_cacheable(self):
        result = await agent_service.GenerateCodeExampleTool().arun(
            agent_service.GenerateCodeExampleArgs(task="写个示例"),
            agent_service.AgentContext(),
        )

        assert result.status == "error"
        assert result.cacheable is False
        assert result.error


class TestDay11Terminal:
    """Day 11：终局三判（reject / error）与 degraded（设计 6.6.3）"""

    async def test_all_search_errors_returns_error_mode(self, monkeypatch):
        class BoomEvidence:
            async def __call__(self, query, *, top_k=None, **kwargs):
                raise RuntimeError("检索服务炸了")

        monkeypatch.setattr(agent_service, "gather_evidence", BoomEvidence())
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "a"})),
            _turn(_call("c2", "search_docs", {"query": "b"})),
            _turn(content="我试着硬答一下"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "error"
        assert resp.answer == agent_service.ERROR_MESSAGE
        assert resp.sources == []
        assert resp.degraded is False
        assert [s.status for s in resp.steps] == ["error", "error"]
        assert all(s.error for s in resp.steps)

    async def test_empty_then_error_mix_still_rejects(self, stub_evidence):
        # 第一次检索零命中（empty）；第二次 query 未配置，桩抛 KeyError（error）
        stub_evidence.map = {"a": Evidence(hits=[], ok=False, scored=False)}
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "a"})),
            _turn(_call("c2", "search_docs", {"query": "b"})),
            _turn(content="确实查不到，不编了"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "reject"
        assert resp.answer == agent_service.REJECT_MESSAGE
        assert [s.status for s in resp.steps] == ["empty", "error"]

    async def test_partial_error_with_evidence_is_degraded(self, monkeypatch):
        class FlakyEvidence:
            async def __call__(self, query, *, top_k=None, **kwargs):
                if query == "炸":
                    raise RuntimeError("检索服务炸了")
                return Evidence(hits=[_hit("c1")], ok=True, scored=True)

        monkeypatch.setattr(agent_service, "gather_evidence", FlakyEvidence())
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "炸"})),
            _turn(_call("c2", "search_docs", {"query": "启动"})),
            _turn(content="用 uvicorn main:app 启动。"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "agent"
        assert resp.degraded is True
        assert [s.status for s in resp.steps] == ["error", "ok"]
        assert "uvicorn main:app" in resp.answer

    async def test_zero_tool_direct_reject_unchanged(self, stub_evidence):
        llm = FakeAgentLLM([_turn(content="我不检索直接拒了")])

        resp = await agent_service.run_agent("随便问", llm=llm)

        assert resp.mode == "reject"
        assert resp.degraded is False
        assert resp.steps == []

    async def test_success_path_degraded_false_and_status_ok(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="答案"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "agent"
        assert resp.degraded is False
        assert resp.steps[0].status == "ok"
        assert resp.steps[0].error is None


class TestDay11LlmFatal:
    """Day 11：主 LLM 非解析类异常不再 500（设计 6.6.3）"""

    async def test_chat_fatal_without_evidence_returns_error(self, stub_evidence):
        llm = FakeAgentLLM([RuntimeError("chat 服务挂了")])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "error"
        assert resp.answer == agent_service.ERROR_MESSAGE
        assert resp.sources == []

    async def test_chat_fatal_auth_error_returns_auth_message(self):
        # F9 Day 13：主 chat 401 且零证据：mode 仍 error，文案换成认证提示
        llm = FakeAgentLLM([_auth_error()])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "error"
        assert resp.answer == AUTH_ERROR_MESSAGE
        assert resp.sources == []

    async def test_chat_fatal_with_evidence_finalizes_degraded(
        self, stub_evidence
    ):
        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            RuntimeError("第二轮 chat 挂了"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "agent"
        assert resp.degraded is True
        assert resp.answer.startswith("【部分回答】")  # 走 generate 兜底终答

    async def test_fallback_generate_fatal_returns_error(self, stub_evidence):
        class HalfDeadLLM(FakeAgentLLM):
            def generate(self, messages):
                raise RuntimeError("generate 也挂了")

        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}
        llm = HalfDeadLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="   "),  # 有证据却吐空 → 触发 generate 兜底
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.mode == "error"
        assert resp.answer == agent_service.ERROR_MESSAGE


class TestDay11Truncation:
    """Day 11：tool 输出 1500 字符限长（含缓存重放）；error_message 4000 上限"""

    async def test_tool_output_clipped_when_fed_back(self, stub_evidence):
        long_text = "甲" * 2000
        stub_evidence.map = {
            "q": Evidence(
                hits=[_hit("c1", content=long_text)], ok=True, scored=True,
            ),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="答案"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        tool_msg = [m for m in llm.chat_log[1]["messages"]
                    if m["role"] == "tool"][0]
        notice = agent_service.TOOL_OUTPUT_CLIPPED_NOTICE
        assert tool_msg["content"].endswith(notice)
        assert len(tool_msg["content"]) == 1500 + len(notice)
        # steps 只记元数据，不受截断影响
        assert resp.steps[0].result_count == 1
        assert resp.steps[0].status == "ok"

    async def test_cached_replay_uses_same_clip(self, stub_evidence):
        long_text = "乙" * 2200
        stub_evidence.map = {
            "q": Evidence(
                hits=[_hit("c1", content=long_text)], ok=True, scored=True,
            ),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(_call("c2", "search_docs", {"query": "q"})),  # 同参 → 缓存重放
            _turn(content="答案"),
        ])

        await agent_service.run_agent("q", llm=llm)

        # 第三轮 messages 含两轮 tool 消息（首轮 + 本轮缓存重放），都必须是截断态
        tool_msgs = [m for m in llm.chat_log[2]["messages"]
                     if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert all(
            m["content"].endswith(agent_service.TOOL_OUTPUT_CLIPPED_NOTICE)
            for m in tool_msgs
        )
        assert len(stub_evidence.calls) == 1

    async def test_short_tool_output_not_clipped(self, stub_evidence):
        stub_evidence.map = {"q": Evidence(hits=[_hit("c1")], ok=True, scored=True)}
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="答案"),
        ])

        await agent_service.run_agent("q", llm=llm)

        tool_msg = [m for m in llm.chat_log[1]["messages"]
                    if m["role"] == "tool"][0]
        assert "已截断" not in tool_msg["content"]

    def test_error_message_max_length_4000(self):
        agent_service.ExplainErrorArgs(error_message="x" * 4000)  # 边界不抛
        with pytest.raises(ValidationError):
            agent_service.ExplainErrorArgs(error_message="x" * 4001)

    async def test_step_error_reason_capped_120(self, monkeypatch):
        class BoomEvidence:
            async def __call__(self, query, *, top_k=None, **kwargs):
                raise RuntimeError("炸" * 500)

        monkeypatch.setattr(agent_service, "gather_evidence", BoomEvidence())
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="答"),
        ])

        resp = await agent_service.run_agent("q", llm=llm)

        assert resp.steps[0].status == "error"
        assert len(resp.steps[0].error) <= 120


class TestGeneralKnowledgeFallback:
    """Day 14：allow_general 只在"库内确无内容（reject 支）"后生效；接地不可绕过"""

    async def test_zero_tool_reject_with_flag_enters_general_mode(self):
        # 模型零工具直拒 + 开关开 → 通用知识接管，声明由服务端补齐
        llm = FakeAgentLLM(
            [_turn(content="我不检索直接编一个")],
            final_text="Celery 是常用的分布式任务队列。",
        )

        resp = await agent_service.run_agent("随便问", llm=llm, allow_general=True)

        assert resp.mode == "general"
        assert resp.sources == []
        assert resp.steps == []
        assert resp.degraded is False
        assert resp.answer.startswith(agent_service.GENERAL_DISCLAIMER)
        assert "Celery" in resp.answer
        # 兜底调用使用通用知识专用 system prompt，而非 ReAct 主提示词
        last_gen = llm.generate_log[-1]
        assert last_gen[0]["content"] == agent_service.GENERAL_KNOWLEDGE_PROMPT

    async def test_general_fallback_keeps_empty_search_steps(self, stub_evidence):
        # 检索一轮零命中后终答 + 开关开 → general 态保留检索轨迹
        stub_evidence.map = {
            "红烧肉": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("call_1", "search_docs", {"query": "红烧肉", "top_k": 5})),
            _turn(content="查不到，给不了"),
        ], final_text="红烧肉一般先焯水再炒糖色。")

        resp = await agent_service.run_agent("红烧肉", llm=llm, allow_general=True)

        assert resp.mode == "general"
        assert len(resp.steps) == 1
        assert resp.steps[0].tool == "search_docs"
        assert resp.steps[0].status == "empty"
        assert resp.answer.startswith(agent_service.GENERAL_DISCLAIMER)

    async def test_flag_off_keeps_plain_reject(self):
        llm = FakeAgentLLM([_turn(content="不检索")], final_text="不应被使用")

        resp = await agent_service.run_agent("q", llm=llm, allow_general=False)

        assert resp.mode == "reject"
        assert resp.answer == agent_service.REJECT_MESSAGE
        assert llm.generate_log == []

    async def test_pipeline_failure_with_flag_still_error(self):
        # 主 LLM chat 首轮即致命故障：属 error 支，开关无权粉饰，general 不得触发
        llm = FakeAgentLLM(
            [RuntimeError("chat 炸了")], generate_exc=RuntimeError("x")
        )

        resp = await agent_service.run_agent("q", llm=llm, allow_general=True)

        assert resp.mode == "error"
        assert llm.generate_log == []

    async def test_evidence_found_with_flag_stays_agent(self, stub_evidence):
        # 有证据：开关完全不生效，正常 agent 终答且不调 generate
        stub_evidence.map = {
            "怎么启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("call_1", "search_docs", {"query": "怎么启动"})),
            _turn(content="文档里写得很清楚"),
        ])

        resp = await agent_service.run_agent("怎么启动", llm=llm, allow_general=True)

        assert resp.mode == "agent"
        assert resp.answer == "文档里写得很清楚"
        assert llm.generate_log == []

    async def test_general_auth_error_returns_error_with_auth_message(self):
        llm = FakeAgentLLM([_turn(content="不检索")], generate_exc=_auth_error())

        resp = await agent_service.run_agent("q", llm=llm, allow_general=True)

        assert resp.mode == "error"
        assert resp.answer == AUTH_ERROR_MESSAGE

    async def test_general_runtime_error_returns_unavailable_message(self):
        llm = FakeAgentLLM(
            [_turn(content="不检索")], generate_exc=RuntimeError("500 boom")
        )

        resp = await agent_service.run_agent("q", llm=llm, allow_general=True)

        assert resp.mode == "error"
        assert resp.answer == agent_service.LLM_UNAVAILABLE_MESSAGE

    async def test_general_empty_text_returns_error(self):
        llm = FakeAgentLLM([_turn(content="不检索")], final_text="   ")

        resp = await agent_service.run_agent("q", llm=llm, allow_general=True)

        assert resp.mode == "error"
        assert resp.answer == agent_service.LLM_UNAVAILABLE_MESSAGE

    async def test_general_fallback_respects_doc_ids_in_search_phase(
        self, stub_evidence
    ):
        # 圈选 + 开关：库内重检仍在圈定范围内，查无后才降级
        stub_evidence.map = {
            "q": Evidence(hits=[], ok=False, scored=False),
        }
        llm = FakeAgentLLM([
            _turn(_call("call_1", "search_docs", {"query": "q"})),
            _turn(content="没有"),
        ], final_text="通用答案")

        resp = await agent_service.run_agent(
            "q", llm=llm, doc_ids=["d9"], allow_general=True
        )

        assert resp.mode == "general"
        assert stub_evidence.calls[0]["kwargs"]["doc_ids"] == ["d9"]


class TestAgentProgressEvents:
    """on_event 进度回调：Agent SSE 实时轨迹（思考轮次 / 工具起止 / 终答阶段）的数据源。

    不传 on_event 时行为与既有契约完全一致（全部老测试已锁定），这里只测挂载回调。
    """

    @staticmethod
    async def _run(llm, **kwargs):
        events = []

        async def on_event(ev):
            # JSON 往返快照：实现侧若复用/原地改写 dict，快照测试能立刻抓到
            events.append(json.loads(json.dumps(ev, ensure_ascii=False)))

        resp = await agent_service.run_agent(
            "q", llm=llm, on_event=on_event, **kwargs
        )
        return resp, events

    async def test_single_search_emits_round_and_tool_pair(self, stub_evidence):
        stub_evidence.map = {
            "怎么启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("call_1", "search_docs",
                        {"query": "怎么启动", "top_k": 5})),
            _turn(content="用 uvicorn 启动。"),
        ])

        resp, events = await self._run(llm)

        assert resp.mode == "agent"
        kinds = [e["type"] for e in events]
        # 第二轮 round_start = 模型读工具结果后组织终答（终答正文由 chat() 直接产出）
        assert kinds == ["round_start", "tool_start", "tool_end", "round_start"]
        assert events[0] == {"type": "round_start", "round": 1}
        assert events[3] == {"type": "round_start", "round": 2}
        assert events[1]["step"] == 1
        assert events[1]["tool"] == "search_docs"
        assert events[1]["arguments"] == {"query": "怎么启动", "top_k": 5}
        assert events[1]["cached"] is False
        step_payload = events[2]["step"]
        assert step_payload["status"] == "ok"
        assert step_payload["result_count"] == 1
        assert step_payload["tool"] == "search_docs"

    async def test_round_start_fires_each_round_cached_marked(self, stub_evidence):
        stub_evidence.map = {
            "启动": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "启动", "top_k": 5})),
            _turn(_call("c2", "search_docs", {"query": "启动", "top_k": 5})),
            _turn(content="ok"),
        ])

        _, events = await self._run(llm)

        assert [e for e in events if e["type"] == "round_start"] == [
            {"type": "round_start", "round": 1},
            {"type": "round_start", "round": 2},
            {"type": "round_start", "round": 3},
        ]
        starts = [e for e in events if e["type"] == "tool_start"]
        assert [s["cached"] for s in starts] == [False, True]
        assert [s["step"] for s in starts] == [1, 2]

    async def test_zero_tool_direct_reply_only_emits_round_start(self):
        llm = FakeAgentLLM([_turn(content="我不检索直接编一个")])

        resp, events = await self._run(llm)

        assert resp.mode == "reject"
        assert [e["type"] for e in events] == ["round_start"]

    async def test_tool_exception_tool_end_error_and_warning_log(
        self, monkeypatch, caplog
    ):
        async def _boom(*args, **kwargs):
            raise RuntimeError("嵌入接口超时")

        monkeypatch.setattr(agent_service, "gather_evidence", _boom)
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "启动"})),
            _turn(content="部分回答"),
        ])

        caplog.set_level(logging.WARNING)
        resp, events = await self._run(llm)

        assert resp.mode == "error"
        end_events = [e for e in events if e["type"] == "tool_end"]
        assert end_events[0]["step"]["status"] == "error"
        assert "嵌入接口超时" in end_events[0]["step"]["error"]
        # 失败短因必须在服务端留痕，否则"部分工具执行失败"横幅永远无法复盘
        assert any(
            "search_docs" in r.message and "嵌入接口超时" in r.message
            for r in caplog.records
        )

    async def test_answering_phase_before_empty_content_fallback(self, stub_evidence):
        stub_evidence.map = {
            "q": Evidence(hits=[_hit("c1")], ok=True, scored=True),
        }
        llm = FakeAgentLLM([
            _turn(_call("c1", "search_docs", {"query": "q"})),
            _turn(content="   "),   # 主 LLM 吐空正文 → 补呼 generate
        ])

        _, events = await self._run(llm)

        assert events[-1] == {"type": "phase", "phase": "answering"}

    async def test_answering_phase_before_general_answer(self):
        llm = FakeAgentLLM([_turn(content="不检索")], final_text="通用答案")

        resp, events = await self._run(llm, allow_general=True)

        assert resp.mode == "general"
        assert events[-1] == {"type": "phase", "phase": "answering"}
