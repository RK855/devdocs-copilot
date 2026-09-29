"""文本切分行为测试"""
from app.services.chunker import split_text


class TestSplitText:
    def test_blank_text_returns_no_chunks(self):
        assert split_text("   \n  ", chunk_size=100, chunk_overlap=20) == []

    def test_short_text_becomes_single_chunk(self):
        chunks = split_text("FastAPI 很好用。", chunk_size=100, chunk_overlap=20)
        assert chunks == ["FastAPI 很好用。"]

    def test_long_text_is_split_into_multiple_chunks(self):
        text = "FastAPI 是一个现代的 Python Web 框架。" * 20  # 约 380 字
        chunks = split_text(text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) >= 3

    def test_each_chunk_respects_size_limit(self):
        text = "。".join(f"这是第{i}个完整的句子内容用来测试切分" for i in range(40))
        chunks = split_text(text, chunk_size=100, chunk_overlap=20)
        assert all(len(c) <= 100 for c in chunks)

    def test_adjacent_chunks_share_overlap(self):
        text = "。".join(f"这是第{i}个完整的句子内容用来测试切分" for i in range(40))
        chunks = split_text(text, chunk_size=100, chunk_overlap=20)
        tail = chunks[0][-15:]
        assert tail in chunks[1]

    def test_default_params_come_from_settings(self):
        # 不传参数时应能正常工作，默认 500/50
        text = "x" * 600
        chunks = split_text(text)
        assert len(chunks) == 2
