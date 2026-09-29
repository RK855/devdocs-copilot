"""
Agent 编排服务（F8 Day 9）
ReAct：LLM 自主调用 search_docs 检索知识库 → 观察结果 → 换词再查或给最终答案。
护栏：最大步数、同参去重缓存、参数错误回喂自纠、工具异常不炸循环、零证据统一拒答。
llm / store / bm25 / reranker 全部构造注入，测试传 Fake 对象零网络。
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.schemas import AgentChatResponse, AgentStep, SourceOut
from app.services.evidence_service import (
    ERROR_MESSAGE,
    REJECT_MESSAGE,
    gather_evidence,
)
from app.services.llm_client import (
    AgnesChatClient,
    AUTH_ERROR_MESSAGE,
    LLM_UNAVAILABLE_MESSAGE,
    ToolArgumentsParseError,
    is_config_error,
)
from app.services.prompt_builder import build_messages, format_hits_for_llm

AGENT_SYSTEM_PROMPT = """你是 DevDocs Copilot 的 Agent 模式，一个严谨的技术文档助手。
你可以调用以下工具：
1. search_docs：在知识库中检索技术文档片段（混合检索 + 精排）
2. generate_code_example：基于检索结果生成带注释、可运行的 fastapi 代码示例
3. explain_error：分析报错原因并给出修复建议
规则：
1. 先调用 search_docs 检索再作答；只能依据检索结果与工具产出回答，禁止编造 API 和参数
2. 一次检索没找到，可以更换关键词再次检索；不要用相同参数重复调用
3. 要代码示例时，必须先检索到相关内容，再调用 generate_code_example（该工具在未检索时会拒绝执行）
4. 分析报错时，若怀疑与项目框架有关，先 search_docs 查证；知识库确无相关内容时，可给出通用排查方向并明确说明
5. 回答使用 Markdown，代码块标注语言"""

NO_EVIDENCE_TOOL_TEXT = "未检索到与该关键词相关的内容，请更换关键词重试。"
MAX_STEPS_HINT = (
    "已达到工具调用最大次数，不能再调用任何工具。"
    "请仅基于上面已有的检索结果给出部分回答，并明确说明哪些部分资料不足。"
)

GROUNDING_REQUIRED_TEXT = (
    "生成代码前必须先调用 search_docs 检索知识库并确认命中相关片段，"
    "请先检索后再用相同任务调用 generate_code_example。"
)
CODE_CONTEXT_LIMIT = 8
STEP_ERROR_LIMIT = 120
TOOL_OUTPUT_LIMIT = 1500
TOOL_OUTPUT_CLIPPED_NOTICE = f"（已截断，仅保留前 {TOOL_OUTPUT_LIMIT} 字符）"

logger = logging.getLogger(__name__)

# 进度回调签名：SSE 端点把 ReAct 循环内部状态实时转推给前端（不传=静默，老契约不变）
ProgressEvent = dict
ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]


def _clip_tool_output(text: str) -> str:
    """回喂模型的 tool 观察文本单条限长：截头部并显式标注（缓存重放走同一出口）"""
    if len(text) <= TOOL_OUTPUT_LIMIT:
        return text
    return text[:TOOL_OUTPUT_LIMIT] + TOOL_OUTPUT_CLIPPED_NOTICE

CODE_TOOL_SYSTEM_PROMPT = """你是 DevDocs Copilot 的代码示例生成工具。
严格依据提供的知识库检索资料，输出一个带注释、可直接运行的 {framework} 最小示例。
要求：
1. 只使用资料中出现的 API 与参数，禁止编造资料外的接口
2. 先给完整代码块（标注语言），再用 2-4 个要点说明关键行
3. 资料不足以支撑任务时，明确指出缺什么，不要硬写"""

EXPLAIN_TOOL_SYSTEM_PROMPT = """你是 DevDocs Copilot 的报错分析工具。
依据提供的报错信息（如有知识库资料，优先依据资料）输出：
1. 错误的直接原因（一句话）
2. 触发条件与定位方法
3. 可操作的修复步骤（编号列出）
没有知识库资料时，可给出该类报错的通用排查方向，并明确说明"知识库中未找到该报错的项目内说明"。"""

# ============ Day 14：通用知识兜底（接地降级） ============
# 免责声明唯一真值：提示词要求与服务端前缀校验共用，保证前端看到的标识逐字一致
GENERAL_DISCLAIMER = (
    "⚠️ 以下内容来自模型通用知识，非知识库文档，"
    "可能与项目实际版本/配置不一致，请结合实际核实。"
)

GENERAL_KNOWLEDGE_PROMPT = f"""你现在处于「通用知识兜底」模式：知识库中已确认没有与该问题相关的文档。
规则：
1. 可以基于你的通用技术知识作答，但回答首行必须原样输出这行免责声明：
{GENERAL_DISCLAIMER}
2. 若问题询问的是用户项目的私有实现（如"我们项目怎么部署的""内部配置是什么"），
   通用知识无从得知，直接说明这类信息只能以项目文档为准，不要编造
3. 不得伪造文档名、章节或引用来源；技术答案尽量标注适用的大致版本
4. 回答使用 Markdown，代码块标注语言"""


class _EmptyGeneralAnswerError(Exception):
    """通用知识兜底返回空正文：视同生成失败，不得冒充成功态"""


async def _generate_general_answer(
    chat_llm: Any, query: str
) -> tuple[str, Exception | None]:
    """库内确无内容后的通用知识单次生成（独立 messages，不继承 ReAct 历史）。

    成功返回 (正文, None)，且保证首行为 GENERAL_DISCLAIMER（模型漏写则服务端补齐）；
    失败（generate 异常 / 空正文）返回 ("", exc)，错误文案分类交给调用方。
    """
    messages = [
        {"role": "system", "content": GENERAL_KNOWLEDGE_PROMPT},
        {"role": "user", "content": query},
    ]
    try:
        content = await asyncio.to_thread(chat_llm.generate, messages)
    except Exception as exc:
        return "", exc
    content = (content or "").strip()
    if not content:
        return "", _EmptyGeneralAnswerError("general knowledge answer is empty")
    if not content.startswith(GENERAL_DISCLAIMER):
        content = f"{GENERAL_DISCLAIMER}\n\n{content}"
    return content, None


@dataclass
class AgentContext:
    """工具执行时可访问的外部依赖（全部可注入替身）"""

    store: Any = None
    bm25: Any = None
    reranker: Any = None
    mode: str | None = None
    llm: Any = None
    # Day 13++：文档级检索范围，None=全库；search_docs 每一步都带上
    doc_ids: list[str] | None = None
    hits_seen: list[dict] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)

    def add_hits(self, hits: list[dict]) -> None:
        """累积跨步骤检索证据（供接地工具使用），按 chunk_id 去重保序、首次出现优先"""
        for hit in hits:
            cid = hit["chunk_id"]
            if cid not in self.seen_ids:
                self.seen_ids.add(cid)
                self.hits_seen.append(hit)


@dataclass
class ToolResult:
    """一次工具执行的产物。

    invalid_args：参数没过校验，不进缓存；
    cacheable：状态相关结果（如接地前置不满足）不进缓存，状态变化后允许重试；
    produces_answer：内容型工具（报错分析）成功产出，零检索命中时也允许作答。
    """

    ok: bool
    text: str
    hits: list[dict] = field(default_factory=list)
    invalid_args: bool = False
    cacheable: bool = True
    produces_answer: bool = False
    # Day 11：结果三态。empty=检索跑通零命中；error=参数/接地/异常；默认 ok
    status: str = "ok"
    error: str | None = None


class SearchDocsArgs(BaseModel):
    """search_docs 入参（Pydantic 校验，错误信息经 tool 消息回喂模型）"""

    query: str = Field(min_length=1, description="检索关键词或问题")
    top_k: int = Field(default=5, ge=1, le=10, description="返回片段数 1-10")


class SearchDocsTool:
    """知识库检索工具：复用与 RAG 完全相同的证据管线（粗排门 → 精排 → 二次门）"""

    name = "search_docs"
    description = (
        "在知识库中检索技术文档片段（混合检索 + 精排）。"
        "概念解释、API 用法、报错信息中的代码标识符，都应先调用本工具查证。"
    )
    args_model = SearchDocsArgs

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    async def arun(self, args: SearchDocsArgs, ctx: AgentContext) -> ToolResult:
        evidence = await gather_evidence(
            args.query,
            top_k=args.top_k,
            store=ctx.store,
            bm25=ctx.bm25,
            reranker=ctx.reranker,
            mode=ctx.mode,
            doc_ids=ctx.doc_ids,
        )
        if not evidence.ok:
            return ToolResult(
                ok=False, text=NO_EVIDENCE_TOOL_TEXT, status="empty",
            )
        ctx.add_hits(evidence.hits)
        return ToolResult(
            ok=True,
            text=format_hits_for_llm(evidence.hits),
            hits=evidence.hits,
        )


class GenerateCodeExampleArgs(BaseModel):
    """generate_code_example 入参（Pydantic 校验，错误信息经 tool 消息回喂模型）"""

    task: str = Field(min_length=1, description="要生成代码示例的具体任务，如：声明带默认值的查询参数")
    framework: Literal["fastapi"] = Field(
        default="fastapi", description="目标框架，当前仅支持 fastapi"
    )


class GenerateCodeExampleTool:
    """接地代码生成：必须已有检索证据，基于证据调 LLM 产出带注释可运行示例"""

    name = "generate_code_example"
    description = (
        "基于知识库检索结果生成带注释、可直接运行的 fastapi 代码示例。"
        "调用前必须先用 search_docs 检索并命中相关片段，否则本工具会拒绝执行。"
    )
    args_model = GenerateCodeExampleArgs

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    async def arun(self, args: GenerateCodeExampleArgs, ctx: AgentContext) -> ToolResult:
        if not ctx.hits_seen:
            return ToolResult(
                ok=False,
                text=GROUNDING_REQUIRED_TEXT,
                cacheable=False,
                status="error",
                error="未检索到相关片段，接地条件不满足",
            )
        messages = [
            {
                "role": "system",
                "content": CODE_TOOL_SYSTEM_PROMPT.format(framework=args.framework),
            },
            {
                "role": "user",
                "content": (
                    f"【知识库检索资料】\n"
                    f"{format_hits_for_llm(ctx.hits_seen[:CODE_CONTEXT_LIMIT])}"
                    f"\n\n【任务】\n{args.task}"
                ),
            },
        ]
        code = await asyncio.to_thread(ctx.llm.generate, messages)
        return ToolResult(ok=True, text=code)


class ExplainErrorArgs(BaseModel):
    """explain_error 入参"""

    error_message: str = Field(
        min_length=1,
        max_length=4000,
        description="完整报错信息，至少含异常类型；有堆栈请贴关键行（最长 4000 字符）",
    )


class ExplainErrorTool:
    """报错分析：LLM 给原因/定位/修复步骤；是否先检索由 ReAct 循环自主决定"""

    name = "explain_error"
    description = (
        "分析报错信息的原因并给出可操作的修复建议。"
        "若怀疑报错与项目框架（FastAPI/Pydantic/uvicorn 等）有关，应先调用 search_docs 查证。"
    )
    args_model = ExplainErrorArgs

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    async def arun(self, args: ExplainErrorArgs, ctx: AgentContext) -> ToolResult:
        grounding = ""
        if ctx.hits_seen:
            grounding = (
                "【知识库相关资料】\n"
                f"{format_hits_for_llm(ctx.hits_seen[:CODE_CONTEXT_LIMIT])}\n\n"
            )
        messages = [
            {"role": "system", "content": EXPLAIN_TOOL_SYSTEM_PROMPT},
            {"role": "user", "content": f"{grounding}【报错信息】\n{args.error_message}"},
        ]
        analysis = await asyncio.to_thread(ctx.llm.generate, messages)
        return ToolResult(ok=True, text=analysis, produces_answer=True)


class ToolRegistry:
    """工具注册表：名字 → 工具实例；负责生成 OpenAI tools schema 与分发执行"""

    def __init__(self):
        self._tools: dict[str, Any] = {}

    def register(self, tool: Any) -> None:
        self._tools[tool.name] = tool

    def openai_schema(self) -> list[dict]:
        return [tool.spec() for tool in self._tools.values()]

    async def arun(self, name: str, arguments: dict, ctx: AgentContext) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self._tools) or "（暂无可用工具）"
            return ToolResult(
                ok=False, invalid_args=True,
                text=f"未知工具 {name!r}；可用工具：{available}",
                status="error",
                error=f"未知工具 {name!r}",
            )
        try:
            parsed = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                invalid_args=True,
                text=f"工具 {name} 参数校验失败，请修正参数后重试：\n{exc}",
                status="error",
                error="工具参数校验失败",
            )
        return await tool.arun(parsed, ctx)


def _default_registry() -> ToolRegistry:
    """生产默认注册表：search_docs 必须第一个注册（tools schema 顺序有既有断言）"""
    registry = ToolRegistry()
    registry.register(SearchDocsTool())
    registry.register(GenerateCodeExampleTool())
    registry.register(ExplainErrorTool())
    return registry


async def run_agent(
    query: str,
    *,
    llm=None,
    store=None,
    bm25=None,
    reranker=None,
    mode=None,
    doc_ids=None,
    allow_general: bool = False,
    registry: ToolRegistry | None = None,
    on_event: ProgressCallback | None = None,
) -> AgentChatResponse:
    """ReAct 主循环：LLM 决定调用工具 → 执行回喂 → 再决策，直至给最终答案或触顶。

    doc_ids 非空时，每一步 search_docs 都只在指定文档范围内检索。
    allow_general=True 且库内检索确无内容（reject 支）时，切换通用知识提示词兜底，
    响应 mode="general"；管线故障（error 支）与有证据时开关均不生效。
    on_event：可选异步回调，按序推送 round_start（每轮模型思考前）/
        tool_start（工具执行或缓存重放前，含参数与 cached）/
        tool_end（完整 AgentStep）/ phase=answering（终答/通用知识生成前）。
    """
    started = time.perf_counter()
    chat_llm = llm or AgnesChatClient()
    registry = registry or _default_registry()

    async def _emit(event: ProgressEvent) -> None:
        if on_event is not None:
            await on_event(event)

    ctx = AgentContext(
        store=store, bm25=bm25, reranker=reranker, mode=mode, llm=chat_llm,
        doc_ids=doc_ids,
    )

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    steps: list[AgentStep] = []
    all_hits: list[dict] = []
    cache: dict[str, ToolResult] = {}
    content_answer = False   # 内容型工具（explain_error）成功产出过
    final_content = ""
    search_succeeded = False   # 任一 search_docs 跑通过（ok 或 empty）：管线正常
    had_error_step = False     # 轨迹中出现过 error 步
    fatal: Exception | None = None   # 主 LLM 非解析类致命异常

    for round_no in range(1, settings.AGENT_MAX_STEPS + 1):
        await _emit({"type": "round_start", "round": round_no})
        try:
            turn = await asyncio.to_thread(
                chat_llm.chat, messages, tools=registry.openai_schema()
            )
        except ToolArgumentsParseError as exc:
            # 整轮参数 JSON 非法、无法配对 tool 消息：以 user 身份回喂，让模型重发
            messages.append({
                "role": "user",
                "content": (
                    "你上一次工具调用的参数无法被解析，"
                    f"错误：{exc}。请修正参数格式后重新调用，或直接作答。"
                ),
            })
            continue
        except Exception as exc:
            # 非解析类故障（网络/5xx 未被重试救回等）：跳出循环走终局分类
            fatal = exc
            break
        if not turn.tool_calls:
            final_content = turn.content
            break

        # OpenAI 协议：assistant 的 tool_calls 必须原样回灌，后续 tool 消息才能配对
        messages.append({
            "role": "assistant",
            "content": turn.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in turn.tool_calls
            ],
        })

        for call in turn.tool_calls:
            cache_key = (
                f"{call.name}:"
                f"{json.dumps(call.arguments, sort_keys=True, ensure_ascii=False)}"
            )
            cached = cache_key in cache
            # 执行（或重放）前先推一步：前端立刻能看到"在查什么词"
            await _emit({
                "type": "tool_start",
                "step": round_no,
                "tool": call.name,
                "arguments": call.arguments,
                "cached": cached,
            })
            if cached:
                result = cache[cache_key]
            else:
                try:
                    result = await registry.arun(call.name, call.arguments, ctx)
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    # 失败短因只进响应（≤120 字），完整原因落服务端日志：
                    # 否则前端"部分工具执行失败"横幅出现时事后无法复盘
                    logger.warning(
                        "Agent 工具执行异常 tool=%s args=%s reason=%s",
                        call.name, call.arguments, reason,
                    )
                    result = ToolResult(
                        ok=False,
                        text=f"工具 {call.name} 执行异常：{reason}",
                        status="error",
                        error=reason,
                    )
                # 参数非法不缓存；状态相关结果（接地闸门拒绝）也不缓存
                if not result.invalid_args and result.cacheable:
                    cache[cache_key] = result
                if result.ok:
                    all_hits.extend(result.hits)

            # 内容型工具成功过（缓存重放也带着标记）：零检索命中也允许作答
            if result.produces_answer:
                content_answer = True

            if call.name == "search_docs" and result.status in ("ok", "empty"):
                search_succeeded = True
            if result.status == "error":
                had_error_step = True

            step_record = AgentStep(
                step=round_no,
                tool=call.name,
                arguments=call.arguments,
                result_count=len(result.hits),
                cached=cached,
                status=result.status,
                error=(result.error[:STEP_ERROR_LIMIT]
                       if result.error else None),
            )
            steps.append(step_record)
            await _emit({
                "type": "tool_end",
                "step": step_record.model_dump(),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": _clip_tool_output(result.text),
            })

    else:
        # 超步仍在调工具：有检索证据或内容工具产出过，就强制无工具收尾
        if all_hits or content_answer:
            messages.append({"role": "user", "content": MAX_STEPS_HINT})
            await _emit({"type": "phase", "phase": "answering"})
            try:
                final_content = await asyncio.to_thread(chat_llm.generate, messages)
            except Exception as exc:
                fatal = exc

    # 跨步骤按 chunk_id 去重：保序（首次出现优先），score 取跨步骤最大值
    merged_hits: dict[str, dict] = {}
    for hit in all_hits:
        cid = hit["chunk_id"]
        if cid not in merged_hits:
            merged_hits[cid] = dict(hit)
        elif hit["score"] > merged_hits[cid]["score"]:
            merged_hits[cid]["score"] = hit["score"]
    final_hits = list(merged_hits.values())

    # 零检索证据且内容型工具也没产出：
    # 零工具直拒、或管线成功执行过（有 ok/empty 的 search）→ reject（库里真没有）
    # 有工具调用但取证全部 error（管线全程故障）→ error，不把故障说成"没有"
    if not final_hits and not content_answer:
        # fatal 且零证据 → error；零工具直拒 / 管线成功执行过 → reject
        all_evidence_failed = (
            fatal is not None or (bool(steps) and not search_succeeded)
        )
        if all_evidence_failed:
            # fatal 为认证/配置类错误时给明确配置提示，其余故障文案不变。
            # allow_general 无权把管线故障粉饰成"库里没有"，此支不响应开关。
            terminal_message = (
                AUTH_ERROR_MESSAGE
                if fatal is not None and is_config_error(fatal)
                else ERROR_MESSAGE
            )
            return AgentChatResponse(
                answer=terminal_message,
                sources=[],
                mode="error",
                response_time=round(time.perf_counter() - started, 2),
                steps=steps,
            )

        # reject 支：库内确无内容。未授权通用知识 → 统一拒答文案（现状不变）
        if not allow_general:
            return AgentChatResponse(
                answer=REJECT_MESSAGE,
                sources=[],
                mode="reject",
                response_time=round(time.perf_counter() - started, 2),
                steps=steps,
            )

        # Day 14：显式 per-query 授权 + 库内已完整检索仍零证据 → 通用知识兜底
        await _emit({"type": "phase", "phase": "answering"})
        general_text, general_exc = await _generate_general_answer(chat_llm, query)
        if general_exc is not None:
            terminal_message = (
                AUTH_ERROR_MESSAGE
                if is_config_error(general_exc)
                else LLM_UNAVAILABLE_MESSAGE
            )
            return AgentChatResponse(
                answer=terminal_message,
                sources=[],
                mode="error",
                response_time=round(time.perf_counter() - started, 2),
                steps=steps,
            )
        return AgentChatResponse(
            answer=general_text,
            sources=[],
            mode="general",
            response_time=round(time.perf_counter() - started, 2),
            steps=steps,
        )

    # 模型吐空正文：有证据用证据补呼；零证据（报错分析路径）沿用 ReAct 历史补呼
    if not final_content.strip():
        fallback_messages = (
            build_messages(query, final_hits) if final_hits else messages
        )
        await _emit({"type": "phase", "phase": "answering"})
        try:
            final_content = await asyncio.to_thread(
                chat_llm.generate, fallback_messages
            )
        except Exception:
            return AgentChatResponse(
                answer=ERROR_MESSAGE,
                sources=[],
                mode="error",
                response_time=round(time.perf_counter() - started, 2),
                steps=steps,
            )

    sources = [
        SourceOut(
            filename=hit["filename"],
            chunk_index=hit["chunk_index"],
            snippet=hit["content"][:150],
            score=hit["score"],
            page=hit["page"],
        )
        for hit in final_hits
    ]
    return AgentChatResponse(
        answer=final_content,
        sources=sources,
        mode="agent",
        response_time=round(time.perf_counter() - started, 2),
        steps=steps,
        degraded=had_error_step or fatal is not None,
    )
