"""
Prompt 构建器
把系统规则与检索到的文档片段组织成 OpenAI chat messages 格式。
纯字符串处理，不碰网络，方便单测。
"""

SYSTEM_PROMPT = """你是 DevDocs Copilot，一个严谨的技术文档助手。
规则：
1. 只能依据【参考资料】回答，资料不足就明说"文档中没有找到相关内容"
2. 回答使用 Markdown，代码块标注语言
3. 不编造 API 和参数"""


def _format_source(index: int, hit: dict) -> str:
    """格式化单条来源：[1] (来源: xxx.pdf, p.3)"""
    header = f"[{index}] (来源: {hit['filename']}"
    if hit.get("page") is not None:
        header += f", p.{hit['page']}"
    header += ")"
    return f"{header}\n{hit['content']}"


def format_hits_for_llm(hits: list[dict]) -> str:
    """把命中片段格式化为编号参考资料文本（RAG Prompt 与 Agent 工具回喂共用）"""
    return "\n\n".join(_format_source(i, hit) for i, hit in enumerate(hits, start=1))


def build_messages(query: str, hits: list[dict]) -> list[dict]:
    """
    构造 chat messages：
      - system：规则 + 编号参考资料
      - user：原始问题
    """
    sources = format_hits_for_llm(hits)
    system_content = f"{SYSTEM_PROMPT}\n\n【参考资料】\n{sources}"

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query},
    ]
