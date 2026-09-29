"""Chroma 向量库封装 —— 集成测试（真实 bge-m3，临时目录）"""
import pytest

from conftest import requires_embedding_api

from app.db.vector_store import VectorStore

pytestmark = requires_embedding_api


@pytest.fixture
def store(tmp_path):
    return VectorStore(path=tmp_path / "chroma")


class TestVectorStore:
    def test_add_document_stores_every_chunk(self, store):
        store.add_document("doc-1", ["FastAPI 用 uvicorn 启动", "路由用装饰器定义"], "a.md")
        assert store.count() == 2

    def test_query_returns_chunk_with_source_metadata(self, store):
        store.add_document("doc-1", ["FastAPI 使用 uvicorn ASGI 服务器启动服务"], "a.md")
        results = store.query_similar("怎么启动 FastAPI 应用", top_k=1)

        assert len(results) == 1
        hit = results[0]
        assert hit["doc_id"] == "doc-1"
        assert hit["filename"] == "a.md"
        assert hit["chunk_index"] == 0
        assert 0 < hit["score"] <= 1
        assert "uvicorn" in hit["content"]

    def test_list_documents_groups_chunk_counts(self, store):
        store.add_document("doc-1", ["块一", "块二", "块三"], "a.md")
        store.add_document("doc-2", ["块一"], "b.txt")

        docs = store.list_documents()
        grouped = sorted((d["doc_id"], d["chunk_count"]) for d in docs)
        assert grouped == [("doc-1", 3), ("doc-2", 1)]

    def test_delete_document_removes_only_its_own_chunks(self, store):
        store.add_document("doc-1", ["FastAPI 路由定义", "FastAPI 依赖注入"], "a.md")
        store.add_document("doc-2", ["红烧肉的做法很简单"], "b.txt")

        store.delete_document("doc-1")

        assert store.count() == 1
        remaining = store.list_documents()
        assert len(remaining) == 1
        assert remaining[0]["doc_id"] == "doc-2"

    def test_get_all_chunks_returns_content_and_ordered_metadata(self, store):
        store.add_document("doc-b", ["第二份文档的内容"], "b.md")
        store.add_document("doc-a", ["块甲", "块乙"], "a.md", pages=[2, 3])

        chunks = store.get_all_chunks()

        assert len(chunks) == 3
        # 按 (doc_id, chunk_index) 确定性排序，BM25 启动重建才有稳定顺序
        assert [(c["doc_id"], c["chunk_index"]) for c in chunks] == [
            ("doc-a", 0),
            ("doc-a", 1),
            ("doc-b", 0),
        ]
        first = chunks[0]
        assert first["chunk_id"] == "doc-a:chunk-0"
        assert first["content"] == "块甲"
        assert first["filename"] == "a.md"
        assert first["page"] == 2

    def test_get_all_chunks_empty_store_returns_empty_list(self, store):
        assert store.get_all_chunks() == []

    def test_pdf_chunks_carry_page_number(self, store):
        store.add_document("doc-9", ["PDF 里的第一块内容"], "x.pdf", pages=[3])
        results = store.query_similar("PDF 内容", top_k=1)
        assert results[0]["page"] == 3

    def test_default_source_is_upload(self, store):
        store.add_document("doc-1", ["块一"], "a.md")
        assert store.list_documents()[0]["source"] == "upload"

    def test_explicit_source_is_recorded(self, store):
        store.add_document("doc-1", ["块一"], "a.md", source="seed")
        assert store.list_documents()[0]["source"] == "seed"

    def test_list_documents_filters_by_source(self, store):
        store.add_document("doc-seed", ["预置语料内容"], "a.md", source="seed")
        store.add_document("doc-up-1", ["我上传的内容"], "b.md", source="upload")
        store.add_document("doc-up-2", ["另一份上传"], "c.md", source="upload")

        seed_docs = store.list_documents(source="seed")
        assert [d["doc_id"] for d in seed_docs] == ["doc-seed"]

        upload_docs = store.list_documents(source="upload")
        assert sorted(d["doc_id"] for d in upload_docs) == ["doc-up-1", "doc-up-2"]

    def test_legacy_chunks_without_source_default_to_seed(self, store):
        # 模拟升级前写入的旧 chunk：metadata 没有 source 字段
        store._collection.add(
            ids=["legacy:chunk-0"],
            documents=["旧时代的语料"],
            metadatas=[{"doc_id": "legacy", "filename": "old.md", "chunk_index": 0}],
        )
        docs = store.list_documents()
        assert docs == [{
            "doc_id": "legacy", "filename": "old.md",
            "chunk_count": 1, "source": "seed",
        }]
        # 过滤视图也能被正确归类
        assert [d["doc_id"] for d in store.list_documents(source="seed")] == ["legacy"]
        assert store.list_documents(source="upload") == []


class TestQueryScope:
    def test_scoped_query_returns_only_selected_documents(self, store):
        # 两篇语义相近的文档；限定 doc_ids 后，结果只能来自被选文档
        store.add_document("doc-a", ["FastAPI 使用 uvicorn ASGI 服务器启动应用"], "a.md")
        store.add_document("doc-b", ["FastAPI 使用 uvicorn 启动 Web 应用的方法"], "b.md")

        results = store.query_similar("怎么启动 FastAPI", top_k=10, doc_ids=["doc-a"])

        assert results  # 范围内有内容，不能因为过滤而空
        assert {h["doc_id"] for h in results} == {"doc-a"}

    def test_scoped_query_with_unknown_doc_id_returns_empty(self, store):
        store.add_document("doc-a", ["FastAPI 使用 uvicorn 启动应用"], "a.md")

        assert store.query_similar("FastAPI", top_k=5, doc_ids=["ghost"]) == []

    def test_empty_scope_list_means_all_documents(self, store):
        store.add_document("doc-a", ["FastAPI 启动"], "a.md")
        store.add_document("doc-b", ["红烧肉做法"], "b.md")

        # 空列表归一为全库：与不传 doc_ids 的结果完全一致
        # （向量库不卡相似度门槛，相关性由上层证据门负责）
        unscoped = store.query_similar("FastAPI", top_k=5)
        emptylist = store.query_similar("FastAPI", top_k=5, doc_ids=[])

        assert [h["chunk_id"] for h in emptylist] == [
            h["chunk_id"] for h in unscoped
        ]


class TestBackfillSource:
    def test_marks_legacy_chunks_without_re_embedding(self, store):
        # 一份旧文档（无 source）+ 一份新文档（已有 source=upload）
        store._collection.add(
            ids=["legacy:chunk-0", "legacy:chunk-1"],
            documents=["旧块甲", "旧块乙"],
            metadatas=[
                {"doc_id": "legacy", "filename": "old.md", "chunk_index": 0},
                {"doc_id": "legacy", "filename": "old.md", "chunk_index": 1},
            ],
        )
        store.add_document("fresh", ["新块"], "new.md", source="upload")

        touched = store.backfill_legacy_source("seed")

        assert touched["chunks"] == 2
        assert touched["doc_ids"] == ["legacy"]

        # metadata 原地补标，正文未动；新文档不被触碰
        got = store._collection.get(include=["documents", "metadatas"])
        by_id = dict(zip(got["ids"], zip(got["documents"], got["metadatas"])))
        doc, meta = by_id["legacy:chunk-0"]
        assert doc == "旧块甲" and meta["source"] == "seed"
        assert by_id["fresh:chunk-0"][1]["source"] == "upload"

        # 补标后按来源过滤正确
        assert [d["doc_id"] for d in store.list_documents(source="seed")] == ["legacy"]

    def test_backfill_is_idempotent(self, store):
        store.add_document("doc-1", ["块一"], "a.md", source="upload")
        assert store.backfill_legacy_source("seed")["chunks"] == 0

    def test_backfill_empty_store(self, store):
        assert store.backfill_legacy_source("seed") == {"chunks": 0, "doc_ids": []}
