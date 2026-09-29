"""硅基流动 BAAI/bge-m3 的 Chroma EmbeddingFunction 实现"""
from chromadb.api.types import EmbeddingFunction, Embeddings
from openai import OpenAI

from app.config import settings


class SiliconFlowEmbeddingFunction(EmbeddingFunction):
    """通过硅基流动 OpenAI 兼容接口生成向量；Chroma 会按批自动调用"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self._client = OpenAI(
            api_key=api_key or settings.SILICONFLOW_API_KEY,
            base_url=base_url or settings.SILICONFLOW_BASE_URL,
        )
        self._model = model or settings.EMBEDDING_MODEL

    def __call__(self, input) -> Embeddings:
        resp = self._client.embeddings.create(model=self._model, input=list(input))
        # 服务端保证顺序，保险起见按 index 排序后返回
        return [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]

    @staticmethod
    def name() -> str:
        return "siliconflow_bge_m3"

    def default_space(self) -> str:
        return "cosine"

    def get_config(self) -> dict:
        # 配置可序列化但不含密钥；重建时从 settings 取 key
        return {"model": self._model}

    @staticmethod
    def build_from_config(config: dict) -> "SiliconFlowEmbeddingFunction":
        return SiliconFlowEmbeddingFunction(model=config.get("model"))
