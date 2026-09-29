"""AgnesChatClient 测试：调用参数、正文提取、超时/5xx 重试"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from openai import APITimeoutError, AuthenticationError, InternalServerError, RateLimitError

from app.config import settings
from app.services.llm_client import AgnesChatClient


# ---------- 轻量 Fake OpenAI 客户端 ----------

class FakeResponse:
    def __init__(self, content):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]


class FakeCompletions:
    """按预设结果依次返回；元素是异常则抛出，最后一个结果会持续生效"""
    def __init__(self, outcomes):
        self._outcomes = outcomes
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes[min(len(self.calls) - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))


def _client(outcomes):
    fake = FakeClient(outcomes)
    return AgnesChatClient(client=fake), fake.chat.completions


class TestGenerate:
    def test_returns_message_content(self):
        client, _ = _client([FakeResponse("用 uvicorn main:app 启动")])

        assert client.generate([{"role": "user", "content": "怎么启动"}]) == "用 uvicorn main:app 启动"

    def test_passes_model_and_generation_params(self):
        client, completions = _client([FakeResponse("ok")])
        messages = [{"role": "user", "content": "q"}]

        client.generate(messages)

        kwargs = completions.calls[0]
        assert kwargs["model"] == "agnes-2.5-flash"
        assert kwargs["messages"] == messages
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_tokens"] == 1024

    def test_retry_once_after_timeout_then_succeed(self):
        client, completions = _client([
            APITimeoutError(request=None),
            FakeResponse("第二次成功"),
        ])

        assert client.generate([{"role": "user", "content": "q"}]) == "第二次成功"
        assert len(completions.calls) == 2

    def test_retry_once_after_5xx_then_succeed(self):
        fake_500 = SimpleNamespace(status_code=500, request=None, headers={})
        client, completions = _client([
            InternalServerError("服务异常", response=fake_500, body=None),
            FakeResponse("恢复了"),
        ])

        assert client.generate([{"role": "user", "content": "q"}]) == "恢复了"
        assert len(completions.calls) == 2

    def test_persistent_failure_raises_after_two_attempts(self):
        client, completions = _client([APITimeoutError(request=None)])

        with pytest.raises(APITimeoutError):
            client.generate([{"role": "user", "content": "q"}])
        assert len(completions.calls) == 2


# ---------- chat() / function calling ----------

from types import SimpleNamespace as _NS

from app.services.llm_client import ChatTurn, ToolArgumentsParseError, ToolCall


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeRawToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeToolResponse:
    def __init__(self, content="", tool_calls=None):
        self.choices = [_NS(message=_NS(content=content, tool_calls=tool_calls))]


class TestChat:
    def test_content_only_turn(self):
        client, _ = _client([FakeResponse("直接答案")])

        turn = client.chat([{"role": "user", "content": "q"}])

        assert isinstance(turn, ChatTurn)
        assert turn.content == "直接答案"
        assert turn.tool_calls == []

    def test_tools_schema_passed_through(self):
        client, completions = _client([FakeToolResponse(tool_calls=[])])
        tools = [{"type": "function", "function": {"name": "search_docs"}}]

        client.chat([{"role": "user", "content": "q"}], tools=tools)

        assert completions.calls[0]["tools"] == tools

    def test_tools_omitted_when_none(self):
        client, completions = _client([FakeResponse("ok")])

        client.chat([{"role": "user", "content": "q"}])

        assert "tools" not in completions.calls[0]

    def test_parses_tool_calls_arguments(self):
        client, _ = _client([FakeToolResponse(
            content="",
            tool_calls=[FakeRawToolCall(
                "call_1", "search_docs", '{"query": "怎么启动", "top_k": 3}'
            )],
        )])

        turn = client.chat([{"role": "user", "content": "q"}], tools=[{"t": 1}])

        assert len(turn.tool_calls) == 1
        call = turn.tool_calls[0]
        assert isinstance(call, ToolCall)
        assert call.id == "call_1"
        assert call.name == "search_docs"
        assert call.arguments == {"query": "怎么启动", "top_k": 3}

    def test_invalid_json_raises_tool_arguments_parse_error(self):
        client, _ = _client([FakeToolResponse(
            tool_calls=[FakeRawToolCall("call_1", "search_docs", "这不是JSON")],
        )])

        with pytest.raises(ToolArgumentsParseError):
            client.chat([{"role": "user", "content": "q"}], tools=[{"t": 1}])

    def test_retry_once_after_timeout_then_tool_call(self):
        client, completions = _client([
            APITimeoutError(request=None),
            FakeToolResponse(
                tool_calls=[FakeRawToolCall("c1", "search_docs", '{"query":"q"}')]
            ),
        ])

        turn = client.chat([{"role": "user", "content": "q"}], tools=[{"t": 1}])

        assert len(completions.calls) == 2
        assert turn.tool_calls[0].name == "search_docs"


# ---------- stream_generate()（F9 Day 12） ----------

class FakeDelta:
    def __init__(self, content):
        self.content = content          # None 用于模拟 reasoning/空块


class FakeChunk:
    def __init__(self, content):
        self.choices = [SimpleNamespace(delta=FakeDelta(content))]


class FakeStream:
    """模拟 openai Stream：可迭代、close() 可计数"""
    def __init__(self, chunks):
        self._it = iter(chunks)
        self.close_count = 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        self.close_count += 1


_QMSG = [{"role": "user", "content": "q"}]


class TestStreamGenerate:
    def test_yields_only_non_empty_delta_content(self):
        client, _ = _client([FakeStream([
            FakeChunk("运"), FakeChunk(None), FakeChunk(""), FakeChunk("行"),
        ])])

        assert list(client.stream_generate(_QMSG)) == ["运", "行"]

    def test_request_uses_stream_flag_and_shared_params(self):
        client, completions = _client([FakeStream([FakeChunk("ok")])])

        list(client.stream_generate(_QMSG))

        kwargs = completions.calls[0]
        assert kwargs["stream"] is True
        assert kwargs["model"] == "agnes-2.5-flash"
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_tokens"] == 1024

    def test_retry_once_on_connect_timeout_then_stream(self):
        ok = FakeStream([FakeChunk("成"), FakeChunk("功")])
        client, completions = _client([APITimeoutError(request=None), ok])

        assert list(client.stream_generate(_QMSG)) == ["成", "功"]
        assert len(completions.calls) == 2
        assert all(c["stream"] is True for c in completions.calls)

    def test_non_retryable_connect_error_not_retried(self):
        client, completions = _client([ValueError("bad key")])

        with pytest.raises(ValueError, match="bad key"):
            list(client.stream_generate(_QMSG))
        assert len(completions.calls) == 1

    def test_early_generator_close_shuts_down_stream(self):
        stream = FakeStream([FakeChunk("a"), FakeChunk("b")])
        client, _ = _client([stream])

        gen = client.stream_generate(_QMSG)
        assert next(gen) == "a"
        gen.close()

        assert stream.close_count == 1

    def test_full_exhaustion_also_closes_stream(self):
        stream = FakeStream([FakeChunk("a"), FakeChunk("b")])
        client, _ = _client([stream])

        assert list(client.stream_generate(_QMSG)) == ["a", "b"]
        assert stream.close_count == 1


# ---------- 429 退避重试 / 认证错误不重试（F9 Day 13） ----------

def _rate_limit_error():
    return RateLimitError(
        "限流",
        response=SimpleNamespace(status_code=429, request=None, headers={}),
        body=None,
    )


class TestRateLimitBackoff:
    def test_rate_limit_retries_twice_with_backoff_then_succeeds(self):
        client, completions = _client([
            _rate_limit_error(),
            _rate_limit_error(),
            FakeResponse("第三次成功"),
        ])

        with patch("app.services.llm_client.time.sleep") as mock_sleep:
            result = client.generate([{"role": "user", "content": "q"}])

        assert result == "第三次成功"
        assert len(completions.calls) == 3
        assert [c.args[0] for c in mock_sleep.call_args_list] == [1.0, 3.0]

    def test_persistent_rate_limit_raises_after_three_attempts(self):
        client, completions = _client([_rate_limit_error()])

        with patch("app.services.llm_client.time.sleep") as mock_sleep:
            with pytest.raises(RateLimitError):
                client.generate([{"role": "user", "content": "q"}])

        assert len(completions.calls) == 3
        assert [c.args[0] for c in mock_sleep.call_args_list] == [1.0, 3.0]


class TestAuthError:
    def test_auth_error_not_retried(self):
        auth_error = AuthenticationError(
            "认证失败",
            response=SimpleNamespace(status_code=401, request=None, headers={}),
            body=None,
        )
        client, completions = _client([auth_error])

        with patch("app.services.llm_client.time.sleep") as mock_sleep:
            with pytest.raises(AuthenticationError):
                client.generate([{"role": "user", "content": "q"}])

        assert len(completions.calls) == 1
        mock_sleep.assert_not_called()


class TestCreateChatClient:
    def test_create_chat_client_wraps_construction_failure(self):
        from app.services.llm_client import LLMConfigError, create_chat_client

        fake = object()
        assert create_chat_client(llm=fake) is fake

        with patch("app.services.llm_client.OpenAI", side_effect=RuntimeError("boom")), \
                patch.object(settings, "AGNES_API_KEY", ""):
            with pytest.raises(LLMConfigError):
                create_chat_client()
