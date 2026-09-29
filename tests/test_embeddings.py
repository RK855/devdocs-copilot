"""硅基流动 bge-m3 Embedding —— 真实 API 集成测试"""
import numpy as np

from app.config import settings
from app.db.embeddings import SiliconFlowEmbeddingFunction


class TestSiliconFlowEmbeddingFunction:
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
