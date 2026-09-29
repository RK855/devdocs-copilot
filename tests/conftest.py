"""测试公共配置与集成测试门控。

绝大多数用例以 Fake LLM / httpx MockTransport / 临时目录运行，零网络零外部依赖；
少数集成用例会真实调用硅基流动的 bge-m3 / bge-reranker API：

- tests/test_embeddings.py、test_vector_store.py、test_documents_api.py
- tests/test_chat_api.py、test_agent_api.py（LLM 与 Reranker 仍为 Stub，
  仅入库 / 检索环节真实调用 Embedding）
- tests/test_rerank_service.py 中的 TestSiliconFlowRerankSmoke

未配置 SILICONFLOW_API_KEY 时这些用例自动 SKIP —— 克隆仓库后零配置
`python -m pytest -q` 即可全绿；在 .env 中配好 Key 后它们自动参与运行。
"""
import pytest

from app.config import settings

# 模块级 pytestmark 或类/函数装饰器引用此标记即可纳入门控
requires_embedding_api = pytest.mark.skipif(
    not settings.SILICONFLOW_API_KEY,
    reason="未配置 SILICONFLOW_API_KEY，跳过需真实 Embedding/Rerank API 的集成测试",
)
