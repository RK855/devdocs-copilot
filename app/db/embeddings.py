"""硅基流动 BAAI/bge-m3 的 Chroma EmbeddingFunction 实现"""
from chromadb.api.types import EmbeddingFunction, Embeddings
from openai import OpenAI

from app.config import settings


class SiliconFlowEmbeddingFunction(EmbeddingFunction):
    """通过硅基流动 OpenAI 兼容接口生成向量。

    Chroma 会把一次 add/query 的全部文本一次性传进来，而供应商 embeddings
    接口有单请求条数上限（硅基流动约 32 条，超出直接报错），因此这里按
    EMBEDDING_BATCH_SIZE 分批请求后按序拼接。
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, *, batch_size: int | None = None):
        # 客户端懒构造：空 Key 不阻塞应用启动（与聊天侧 create_chat_client 同一纪律），
        # 首次真正生成向量时才校验凭据
        self._api_key = api_key or settings.SILICONFLOW_API_KEY
        self._base_url = base_url or settings.SILICONFLOW_BASE_URL
        self._model = model or settings.EMBEDDING_MODEL
        self._batch_size = max(1, batch_size or settings.EMBEDDING_BATCH_SIZE)
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    def __call__(self, input) -> Embeddings:
        inputs = list(input)
        embeddings: Embeddings = []
        for start in range(0, len(inputs), self._batch_size):
            batch = inputs[start:start + self._batch_size]
            resp = self._get_client().embeddings.create(model=self._model, input=batch)
            # 服务端保证顺序，保险起见按 index 排序后追加
            embeddings.extend(
                item.embedding for item in sorted(resp.data, key=lambda d: d.index)
            )
        return embeddings

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
