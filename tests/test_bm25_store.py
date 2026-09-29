"""BM25 关键词检索封装 —— 纯内存单元测试（零网络，不依赖 Chroma / Embedding）"""
import pytest

from app.db.bm25_store import BM25Store, tokenize


class TestTokenize:
    def test_lowercases_english(self):
        assert tokenize("FastAPI") == ["fastapi"]

    def test_drops_pure_punctuation_and_whitespace(self):
        # 标点/空白单独成词时丢弃；含字符的标识符保留
        assert tokenize("@app.get") == ["app", "get"]
        assert "，" not in tokenize("你好，世界")

    def test_keeps_underscore_in_identifier(self):
        # 下划线是代码标识符的一部分，query_similar 不能被拆散
        assert tokenize("query_similar") == ["query_similar"]

    def test_blank_text_returns_empty(self):
        assert tokenize("  @，. ") == []

    def test_drops_common_chinese_stopwords(self):
        # "的/怎么" 篇篇出现，必须在分词阶段剔除，否则候选预筛永远命中
        assert tokenize("红烧肉的做法") == ["红烧肉", "做法"]
        assert "怎么" not in tokenize("@app.get 怎么用")


class TestBM25StoreSearch:
    def test_empty_store_search_returns_empty_list(self):
        assert BM25Store().search("随便查", top_k=5) == []

    def test_chinese_keyword_hits_matching_chunk(self):
        store = BM25Store()
        store.add_document("d1", ["红烧肉的做法是先焯水再小火慢炖"], "cook.txt")
        store.add_document("d2", ["FastAPI 是一个 Python Web 框架"], "dev.md")

        hits = store.search("红烧肉怎么做", top_k=1)

        assert len(hits) == 1
        assert hits[0]["doc_id"] == "d1"
        assert hits[0]["chunk_index"] == 0

    def test_code_identifier_query_ranks_exact_chunk_first(self):
        # F5 核心验收场景：代码标识符精确匹配必须排第一
        store = BM25Store()
        store.add_document("d1", ["使用 @app.get 装饰器定义 GET 路由"], "routing.md")
        store.add_document("d2", ["路由也可以用 APIRouter 统一管理"], "router.md")
        store.add_document("d3", ["红烧肉需要冰糖炒糖色"], "cook.txt")

        hits = store.search("@app.get 怎么用", top_k=3)

        assert hits[0]["doc_id"] == "d1"
        assert hits[0]["chunk_id"] == "d1:chunk-0"

    def test_search_is_case_insensitive(self):
        store = BM25Store()
        store.add_document("d1", ["uvicorn main:app --reload 启动热重载"], "run.md")

        assert store.search("UVICORN", top_k=1)[0]["doc_id"] == "d1"

    def test_hit_schema_matches_vector_store(self):
        # 字段与 VectorStore.query_similar 对齐，F6 融合时两路结果可直接合并
        store = BM25Store()
        store.add_document("d1", ["FastAPI 路由装饰器"], "a.md", pages=[7])
        store.add_document("d2", ["红烧肉需要小火慢炖"], "b.txt")
        store.add_document("d3", ["明天可能会下雨"], "c.txt")

        hit = store.search("FastAPI", top_k=1)[0]

        assert set(hit.keys()) == {
            "chunk_id", "content", "doc_id", "filename", "chunk_index", "page", "score",
        }
        assert hit["filename"] == "a.md"
        assert hit["page"] == 7
        assert hit["score"] > 0

    def test_top_k_limits_result_count(self):
        store = BM25Store()
        store.add_document("d1", ["FastAPI FastAPI FastAPI"], "a.md")
        store.add_document("d2", ["FastAPI 入门"], "b.md")
        store.add_document("d3", ["FastAPI 进阶"], "c.md")

        assert len(store.search("FastAPI", top_k=2)) == 2

    def test_query_with_no_valid_tokens_returns_empty(self):
        store = BM25Store()
        store.add_document("d1", ["一些内容"], "a.md")

        assert store.search("，。@", top_k=3) == []


class TestBM25StoreSearchScope:
    def test_scoped_search_ignores_out_of_scope_stronger_match(self):
        # d2 的词频更高（BM25 本应排第一），但范围只圈 d1
        store = BM25Store()
        store.add_document("d1", ["FastAPI 入门教程"], "a.md")
        store.add_document("d2", ["FastAPI FastAPI FastAPI 进阶"], "b.md")

        hits = store.search("FastAPI", top_k=5, doc_ids=["d1"])

        assert hits
        assert {h["doc_id"] for h in hits} == {"d1"}

    def test_scope_filters_before_top_k(self):
        # 范围外多篇高分文档不能占光 top_k 名额，把范围内结果挤没
        store = BM25Store()
        store.add_document("d-in", ["FastAPI 路由装饰器用法"], "in.md")
        for i in range(5):
            store.add_document(f"d-out-{i}", [f"FastAPI 第 {i} 篇"], f"out{i}.md")

        hits = store.search("FastAPI 路由", top_k=3, doc_ids=["d-in"])

        assert [h["doc_id"] for h in hits] == ["d-in"]

    def test_scoped_search_unknown_doc_id_returns_empty(self):
        store = BM25Store()
        store.add_document("d1", ["FastAPI 入门"], "a.md")

        assert store.search("FastAPI", top_k=5, doc_ids=["ghost"]) == []

    def test_empty_scope_list_means_all_documents(self):
        store = BM25Store()
        store.add_document("d1", ["FastAPI 入门"], "a.md")
        store.add_document("d2", ["红烧肉做法"], "b.txt")

        assert [h["chunk_id"] for h in store.search("FastAPI", top_k=5, doc_ids=[])] == [
            h["chunk_id"] for h in store.search("FastAPI", top_k=5)
        ]


class TestBM25StoreDelete:
    def test_delete_removes_only_target_document_chunks(self):
        store = BM25Store()
        store.add_document("d1", ["FastAPI 路由", "FastAPI 依赖注入"], "a.md")
        store.add_document("d2", ["红烧肉做法"], "b.txt")

        store.delete_document("d1")

        hits = store.search("FastAPI", top_k=5)
        assert hits == []
        assert store.search("红烧肉", top_k=1)[0]["doc_id"] == "d2"

    def test_delete_then_readd_keeps_index_consistent(self):
        store = BM25Store()
        store.add_document("d1", ["旧版 FastAPI 教程"], "a.md")
        store.delete_document("d1")
        store.add_document("d1", ["新版 FastAPI 教程"], "a.md")

        hits = store.search("FastAPI", top_k=3)
        assert len(hits) == 1
        assert "新版" in hits[0]["content"]

    def test_delete_unknown_doc_id_is_noop(self):
        store = BM25Store()
        store.add_document("d1", ["FastAPI 教程"], "a.md")

        store.delete_document("not-exist")

        assert len(store.search("FastAPI", top_k=3)) == 1


class TestRebuildFromVectorStore:
    class FakeVectorStore:
        """只实现重建所需的 get_all_chunks 协议"""

        def __init__(self, chunks):
            self._chunks = chunks

        def get_all_chunks(self):
            return list(self._chunks)

    def test_rebuild_indexes_all_existing_chunks(self):
        chunks = [
            {
                "chunk_id": "doc-1:chunk-0",
                "content": "用 @app.get 定义路由",
                "doc_id": "doc-1",
                "filename": "a.md",
                "chunk_index": 0,
                "page": None,
            },
            {
                "chunk_id": "doc-1:chunk-1",
                "content": "用 @app.post 定义写接口",
                "doc_id": "doc-1",
                "filename": "a.md",
                "chunk_index": 1,
                "page": None,
            },
        ]
        store = BM25Store()
        store.add_document("old", ["早就过时的内容"], "old.txt")

        store.rebuild_from_vector_store(self.FakeVectorStore(chunks))

        hits = store.search("@app.post", top_k=1)
        assert hits[0]["doc_id"] == "doc-1"
        assert hits[0]["chunk_index"] == 1
        # 旧索引内容被整体替换，不是追加
        assert store.search("过时", top_k=3) == []
