"""硅基流动 bge-m3 Embedding：真实 API 集成测试 + 分批逻辑零网络测试"""
from types import SimpleNamespace

import numpy as np
import pytest

from conftest import requires_embedding_api

from app.config import settings
from app.db.embeddings import SiliconFlowEmbeddingFunction


class TestSiliconFlowEmbeddingFunction:
    """真实 API 集成用例（需 SILICONFLOW_API_KEY，未配置自动 SKIP）"""

    pytestmark = requires_embedding_api

    def test_embeds_single_text_into_1024_dims(self):
        ef = SiliconFlowEmbeddingFunction()
        result = ef(["FastAPI 怎么创建 GET 路由"])
        assert len(result) == 1
        assert len(result[0]) == settings.EMBEDDING_DIM

    def test_embeds_batch_preserves_order(self):
        ef = SiliconFlowEmbeddingFunction()
        texts = ["第一个文本AAA", "第二个文本BBB", "第三个文本CCC"]
        result = ef(texts)
        assert len(result) == 3
        # 不同输入得到不同向量，顺序与输入一致
        assert not np.allclose(result[0], result[1])
        assert not np.allclose(result[1], result[2])

    def test_semantic_nearness_beats_unrelated_text(self):
        ef = SiliconFlowEmbeddingFunction()
        vecs = ef([
            "如何在 FastAPI 中定义一个 GET 接口",
            "FastAPI 创建 GET 路由的方法",
            "今天的红烧肉炖得很入味",
        ])
        v = [np.array(x) for x in vecs]

        def cosine(a, b):
            return a @ b / (np.linalg.norm(a) * np.linalg.norm(b))

        assert cosine(v[0], v[1]) > cosine(v[0], v[2])


class FakeEmbeddingsClient:
    """伪 OpenAI 客户端：记录每批 input，返回可识别批大小与批内下标的伪向量"""

    def __init__(self):
        self.batches: list[list[str]] = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, *, model, input):
        self.batches.append(list(input))
        data = [
            SimpleNamespace(index=i, embedding=[float(len(input)), float(i)])
            for i in range(len(input))
        ]
        return SimpleNamespace(data=data)


class TestBatching:
    """供应商 embeddings 接口有单请求条数上限，EF 必须分批（零网络，注入 Fake 客户端）"""

    def _make_ef(self, batch_size: int):
        ef = SiliconFlowEmbeddingFunction(
            api_key="k", base_url="http://test", model="m", batch_size=batch_size
        )
        fake = FakeEmbeddingsClient()
        ef._client = fake
        return ef, fake

    def test_large_input_splits_into_limited_batches(self):
        ef, fake = self._make_ef(batch_size=4)
        result = ef([f"text-{i}" for i in range(10)])
        assert [len(b) for b in fake.batches] == [4, 4, 2]
        assert len(result) == 10

    def test_batch_vectors_stay_in_input_order(self):
        ef, fake = self._make_ef(batch_size=4)
        result = ef([f"text-{i}" for i in range(6)])
        # 向量由 (批大小, 批内下标) 决定：第 5 条落在第二批 0 号位
        # （chroma EF 基类会把返回值校验成 numpy 数组，先转回 list 再比）
        assert list(result[0]) == [4.0, 0.0]
        assert list(result[4]) == [2.0, 0.0]
        assert list(result[5]) == [2.0, 1.0]

    def test_input_below_batch_size_is_single_request(self):
        ef, fake = self._make_ef(batch_size=32)
        result = ef(["只有一条"])
        assert len(fake.batches) == 1
        assert len(result) == 1
