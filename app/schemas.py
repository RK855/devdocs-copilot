"""请求/响应数据模型（Pydantic 自动校验与序列化）"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DocumentOut(BaseModel):
    """文档列表中的单项"""
    doc_id: str
    filename: str
    chunk_count: int
    # seed=脚本灌库的预置语料 / upload=网页上传
    source: Literal["seed", "upload"] = "upload"


class DocumentListResponse(BaseModel):
    documents: list[DocumentOut]
    total: int


class UploadResponse(BaseModel):
    success: bool = True
    doc_id: str
    filename: str
    chunk_count: int
    source: Literal["seed", "upload"] = "upload"


class DeleteResponse(BaseModel):
    success: bool = True


# ============ 问答相关 ============

class ChatRequest(BaseModel):
    """问答请求体"""
    # Day 13：2000 字符上限防超长输入（前端 textarea 同步 maxlength 软约束）
    query: str = Field(min_length=1, max_length=2000, description="用户问题")
    # Day 13++：文档级检索范围；None/空列表 = 全库，非空 = 只在这些文档内检索
    doc_ids: list[str] | None = Field(
        default=None,
        max_length=100,
        description="限定检索的文档 id 列表；不传或空列表表示全库",
    )
    # Day 14：仅 /api/agent/query 生效——库内检索确无内容时是否允许模型用通用知识兜底；
    # per-query 无状态授权，不传=False=接地模式；RAG 两端点收到一律忽略
    allow_general: bool = Field(
        default=False,
        description="Agent 库内零证据时是否允许通用知识兜底（仅本次请求有效）",
    )

    @field_validator("doc_ids")
    @classmethod
    def doc_id_elements_bounded(cls, v):
        """单个 doc_id 限长 64（uuid4 hex 为 32），挡异常长字符串灌进 where 子句"""
        if v:
            for doc_id in v:
                if len(doc_id) > 64:
                    raise ValueError("单个文档 id 长度不能超过 64")
        return v

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        """拒绝纯空白问题"""
        if not v.strip():
            raise ValueError("问题不能为空白")
        return v


class SourceOut(BaseModel):
    """回答引用的来源片段"""
    filename: str
    chunk_index: int
    snippet: str
    score: float
    page: int | None = None


class ChatResponse(BaseModel):
    """问答响应：正文 + 来源 + 模式 + 耗时"""
    answer: str
    sources: list[SourceOut]
    mode: str                       # rag：基于文档回答 / reject：拒答 / error：管线或 LLM 故障（HTTP 仍 200）
    response_time: float


# ============ Agent 问答相关（F8 Day 9） ============

class AgentStep(BaseModel):
    """Agent 一次工具调用的执行记录

    status：ok 正常有产出 / empty 检索跑通但零命中 / error 参数错、接地拒绝或执行异常
    error：失败短因（≤120 字由服务层截断）；完整异常文本只回喂模型，不进响应
    """
    step: int
    tool: str
    arguments: dict
    result_count: int
    cached: bool
    status: Literal["ok", "empty", "error"] = "ok"
    error: str | None = None


class AgentChatResponse(BaseModel):
    """Agent 问答响应：正文 + 跨步骤去重来源 + 模式 + 耗时 + 执行步骤

    mode：agent 正常作答 / reject 知识库确无内容 / error 取证管线全程故障
        / general 库内确无内容且获显式授权后的通用知识兜底（Day 14）
    degraded：agent 态但轨迹中出现过失败步（或主 LLM 中途故障兜底终答）
    """
    answer: str
    sources: list[SourceOut]
    mode: Literal["agent", "reject", "error", "general"]
    response_time: float
    steps: list[AgentStep]
    degraded: bool = False

