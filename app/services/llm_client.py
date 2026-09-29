"""
Agnes 聊天客户端
封装 chat/completions 调用：
- generate()：只返回回答正文（reasoning_content 是模型内心独白，丢弃）
- chat()（F8 Day 9）：支持 function calling，返回正文与结构化 tool_calls
重试策略（F9 Day 13）：
- 429 限流：指数退避重试 2 次（重试前等待 1s/3s），共 3 次尝试
- 超时、连接失败、5xx：自动重试 1 次，共 2 次尝试
- 401/403 等认证错误与其他错误：立即抛出，不浪费重试
"""
import json
import time
from dataclasses import dataclass

import openai
from openai import OpenAI

from app.config import settings

# 值得重试的"临时性故障"
RETRYABLE_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class LLMConfigError(Exception):
    """API Key 缺失/无效等配置类问题：不可重试，面向用户给明确配置提示"""


# 认证/权限类（401/403）：不重试
AUTH_ERRORS = (openai.AuthenticationError, openai.PermissionDeniedError)

# 面向用户文案（chat_service / stream_service / agent_service 共用）
AUTH_ERROR_MESSAGE = "模型服务认证失败：API Key 无效或缺失，请检查配置后重试。"
LLM_UNAVAILABLE_MESSAGE = "回答服务暂时不可用，请稍后重试。"

# 429 指数退避：第 1/2 次重试前分别等待 1s、3s
RATE_LIMIT_BACKOFF = (1.0, 3.0)


def is_config_error(exc: BaseException) -> bool:
    return isinstance(exc, (LLMConfigError,) + AUTH_ERRORS)


def create_chat_client(llm=None) -> "AgnesChatClient":
    """构造注入入口：注入了 llm 直接用；否则构造真实客户端，失败统一转 LLMConfigError。
    启动期不构造（settings 已允许空 key），故应用启动永不被 key 问题阻塞。"""
    if llm is not None:
        return llm
    try:
        return AgnesChatClient()
    except Exception as exc:
        if isinstance(exc, LLMConfigError):
            raise
        raise LLMConfigError(f"聊天模型客户端初始化失败：{exc}") from exc


class ToolArgumentsParseError(Exception):
    """模型返回的 tool_call.arguments 不是合法 JSON；交由 Agent 循环回喂模型自纠"""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatTurn:
    content: str
    tool_calls: list[ToolCall]


class AgnesChatClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, *, client=None):
        """client 可注入：测试传入 FakeClient，零网络"""
        self.model = model or settings.CHAT_MODEL
        if client is not None:
            self._client = client
        else:
            self._client = OpenAI(
                api_key=api_key or settings.AGNES_API_KEY,
                base_url=base_url or settings.AGNES_BASE_URL,
                timeout=settings.LLM_TIMEOUT,
            )

    def _create(self, messages: list[dict], *, tools: list[dict] | None = None,
                stream: bool = False):
        """底层请求：429 限流退避重试 2 次（1s/3s）；超时/连接/5xx 重试 1 次；
        401/403 等认证错误立即抛出不重试。generate/chat/stream 共用。"""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": settings.LLM_TEMPERATURE,
                    "max_tokens": settings.LLM_MAX_TOKENS,
                }
                if tools is not None:
                    kwargs["tools"] = tools
                if stream:
                    kwargs["stream"] = True
                return self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError as exc:
                last_error = exc
                if attempt < len(RATE_LIMIT_BACKOFF):
                    time.sleep(RATE_LIMIT_BACKOFF[attempt])
                    continue
            except RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt == 0:
                    continue
            break
        assert last_error is not None
        raise last_error

    def generate(self, messages: list[dict]) -> str:
        """发送 messages，返回正文"""
        response = self._create(messages)
        return response.choices[0].message.content or ""

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> ChatTurn:
        """带工具声明的一轮对话；工具参数 JSON 非法时抛 ToolArgumentsParseError"""
        response = self._create(messages, tools=tools)
        message = response.choices[0].message
        raw_calls = getattr(message, "tool_calls", None) or []

        tool_calls: list[ToolCall] = []
        for raw in raw_calls:
            raw_args = raw.function.arguments or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise ToolArgumentsParseError(
                    f"工具 {raw.function.name} 的参数不是合法 JSON: {raw_args!r}"
                ) from exc
            tool_calls.append(ToolCall(id=raw.id, name=raw.function.name,
                                      arguments=arguments))

        return ChatTurn(content=message.content or "", tool_calls=tool_calls)

    def stream_generate(self, messages: list[dict]):
        """流式正文生成器：逐块 yield delta.content（reasoning_content 丢弃，空块跳过）。

        建连阶段临时故障由 _create 重试 1 次；迭代中途故障不重试（已吐内容无法重放），
        异常向上传播，由 stream_service 转 stream_interrupted 事件。
        """
        stream = self._create(messages, stream=True)
        try:
            for chunk in stream:
                text = chunk.choices[0].delta.content or ""
                if text:
                    yield text
        finally:
            # 正常耗尽 / 迭代异常 / 生成器被 close（用户停止）都保证关闭上游 HTTP 流
            stream.close()
