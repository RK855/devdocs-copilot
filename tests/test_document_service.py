"""document_service 编排行为测试（FakeStore 注入 + 临时上传目录）"""
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.db.bm25_store import bm25_store
from app.errors import DocumentValidationError
from app.services import document_service


def make_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 14 Tf 50 350 Td ({text}) Tj ET".encode())
    page.replace_contents(stream)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


class FakeStore:
    """记录编排层调用，避免真实网络；协议与 VectorStore 一致"""

    def __init__(self):
        self.added = []
        self.deleted = []

    def add_document(self, doc_id, chunks, filename, pages=None, source="upload"):
        self.added.append({
            "doc_id": doc_id, "chunks": chunks, "filename": filename,
            "pages": pages, "source": source,
        })

    def delete_document(self, doc_id):
        # 与真实 VectorStore 对齐：删除后列表聚合不再出现该文档
        self.added = [a for a in self.added if a["doc_id"] != doc_id]
        self.deleted.append(doc_id)

    def list_documents(self, source=None):
        docs = [
            {"doc_id": a["doc_id"], "filename": a["filename"],
             "chunk_count": len(a["chunks"]), "source": a["source"]}
            for a in self.added
        ]
        if source is not None:
            docs = [d for d in docs if d["source"] == source]
        return docs


class FakeBM25:
    """记录 BM25 同步调用，协议与 BM25Store 的 add_document/delete_document 一致"""

    def __init__(self):
        self.added = []
        self.deleted = []

    def add_document(self, doc_id, chunks, filename, pages=None):
        self.added.append({"doc_id": doc_id, "chunks": chunks, "filename": filename, "pages": pages})

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)


@pytest.fixture
def fake_store():
    return FakeStore()


@pytest.fixture
def fake_bm25():
    return FakeBM25()


@pytest.fixture(autouse=True)
def reset_global_state():
    # 没注入 bm25 的用例会落到全局单例，每个用例前清空，杜绝索引跨用例污染；
    # 会话基线（library/session 划分依据）同样是全局态，一并复位
    bm25_store.clear()
    document_service.reset_session_baseline()
    yield
    bm25_store.clear()
    document_service.reset_session_baseline()


@pytest.fixture
def upload_dir(tmp_path):
    d = tmp_path / "uploads"
    d.mkdir()
    return d


class TestIngestDocument:
    @pytest.mark.parametrize("ext", ["md", "txt"])
    async def test_ingest_plain_text_persists_file_and_chunks(self, fake_store, upload_dir, ext):
        data = "FastAPI 使用 uvicorn 启动服务。".encode()

        result = await document_service.ingest_document(
            f"guide.{ext}", data, store=fake_store, upload_dir=upload_dir
        )

        assert result["filename"] == f"guide.{ext}"
        assert result["chunk_count"] == 1
        doc_id = result["doc_id"]

        # 源文件以 doc_id 前缀落盘，天然防同名覆盖
        saved = list(upload_dir.glob(f"{doc_id}_*"))
        assert len(saved) == 1
        assert saved[0].read_bytes() == data

        # vector store 收到的内容
        assert fake_store.added[0]["doc_id"] == doc_id
        assert "uvicorn" in fake_store.added[0]["chunks"][0]
        assert fake_store.added[0]["pages"] is None

    async def test_ingest_pdf_carries_page_numbers(self, fake_store, upload_dir):
        data = make_pdf("Hello FastAPI")

        result = await document_service.ingest_document(
            "paper.pdf", data, store=fake_store, upload_dir=upload_dir
        )

        assert result["chunk_count"] == 1
        assert fake_store.added[0]["pages"] == [1]

    async def test_ingest_long_document_produces_multiple_chunks(self, fake_store, upload_dir):
        text = "FastAPI 是一个现代的 Python Web 框架，性能很好。" * 30
        result = await document_service.ingest_document(
            "long.md", text.encode(), store=fake_store, upload_dir=upload_dir
        )
        assert result["chunk_count"] >= 2

    async def test_document_with_no_extractable_text_is_rejected_before_saving(self, fake_store, upload_dir):
        # 文件非空但解析后无内容（只有空白）
        with pytest.raises(DocumentValidationError, match="内容"):
            await document_service.ingest_document(
                "blank.md", b"   \n   ", store=fake_store, upload_dir=upload_dir
            )

        assert list(upload_dir.iterdir()) == []
        assert fake_store.added == []

    async def test_validation_failure_leaves_nothing_behind(self, fake_store, upload_dir):
        with pytest.raises(DocumentValidationError):
            await document_service.ingest_document(
                "evil.doc", b"x", store=fake_store, upload_dir=upload_dir
            )

        assert list(upload_dir.iterdir()) == []
        assert fake_store.added == []

    async def test_ingest_syncs_chunks_to_bm25_index(self, fake_store, fake_bm25, upload_dir):
        data = b"@app.get defines a GET route"

        result = await document_service.ingest_document(
            "route.md", data, store=fake_store, bm25=fake_bm25, upload_dir=upload_dir
        )

        assert len(fake_bm25.added) == 1
        entry = fake_bm25.added[0]
        assert entry["doc_id"] == result["doc_id"]
        assert entry["filename"] == "route.md"
        assert entry["chunks"] == ["@app.get defines a GET route"]
        assert entry["pages"] is None

    async def test_failed_ingest_does_not_touch_bm25(self, fake_store, fake_bm25, upload_dir):
        with pytest.raises(DocumentValidationError):
            await document_service.ingest_document(
                "evil.doc", b"x", store=fake_store, bm25=fake_bm25, upload_dir=upload_dir
            )

        assert fake_bm25.added == []

    async def test_ingest_marks_upload_source_by_default(self, fake_store, upload_dir):
        result = await document_service.ingest_document(
            "a.md", b"FastAPI", store=fake_store, upload_dir=upload_dir
        )
        assert result["source"] == "upload"
        assert fake_store.added[0]["source"] == "upload"

    async def test_ingest_passes_seed_source_through(self, fake_store, upload_dir):
        result = await document_service.ingest_document(
            "a.md", b"FastAPI", store=fake_store, upload_dir=upload_dir, source="seed"
        )
        assert result["source"] == "seed"
        assert fake_store.added[0]["source"] == "seed"


class TestListAndDelete:
    async def test_list_documents_passes_through_store(self, fake_store, upload_dir):
        await document_service.ingest_document("a.md", b"aaa", store=fake_store, upload_dir=upload_dir)
        docs = await document_service.list_documents(store=fake_store)
        assert len(docs) == 1
        assert docs[0]["chunk_count"] == 1

    async def test_list_documents_filters_by_session_scope(self, fake_store, upload_dir):
        # 第一份：模拟"服务启动时已在库"——拍照进会话基线
        old = await document_service.ingest_document(
            "seed.md", "预置教程内容".encode(), store=fake_store, upload_dir=upload_dir, source="seed"
        )
        # 第二份：基线拍照之后才入库 = 本次服务期间上传
        await document_service.ingest_document(
            "up.md", "我的上传笔记".encode(), store=fake_store, upload_dir=upload_dir
        )

        # 基线集合只认 doc_id，与 source 章无关
        document_service.capture_session_baseline([old["doc_id"]])

        library = await document_service.list_documents(store=fake_store, scope="library")
        assert [d["filename"] for d in library] == ["seed.md"]
        session = await document_service.list_documents(store=fake_store, scope="session")
        assert [d["filename"] for d in session] == ["up.md"]
        # 不带 scope 仍是全量
        assert len(await document_service.list_documents(store=fake_store)) == 2

    async def test_library_scope_intersects_live_docs(self, fake_store, upload_dir):
        # 基线里记过的文档若已被删除，library 视图不能把幽灵捞回来
        old = await document_service.ingest_document(
            "old.md", b"old", store=fake_store, upload_dir=upload_dir, source="seed"
        )
        document_service.capture_session_baseline([old["doc_id"]])
        await document_service.delete_document(old["doc_id"], store=fake_store, upload_dir=upload_dir)

        assert await document_service.list_documents(store=fake_store, scope="library") == []
        assert await document_service.list_documents(store=fake_store, scope="session") == []

    async def test_baseline_is_a_snapshot(self, fake_store, upload_dir):
        old = await document_service.ingest_document(
            "old.md", b"old", store=fake_store, upload_dir=upload_dir, source="seed"
        )
        document_service.capture_session_baseline([old["doc_id"]])
        # 拍照之后的入库不改变基线；reset 后基线清空，一切文档都算 session
        await document_service.ingest_document("new.md", b"new", store=fake_store, upload_dir=upload_dir)
        assert len(await document_service.list_documents(store=fake_store, scope="library")) == 1
        document_service.reset_session_baseline()
        assert await document_service.list_documents(store=fake_store, scope="library") == []
        assert len(await document_service.list_documents(store=fake_store, scope="session")) == 2

    async def test_delete_removes_chunks_and_source_file(self, fake_store, upload_dir):
        result = await document_service.ingest_document("a.md", b"FastAPI", store=fake_store, upload_dir=upload_dir)
        doc_id = result["doc_id"]
        assert list(upload_dir.glob(f"{doc_id}_*")) != []

        await document_service.delete_document(doc_id, store=fake_store, upload_dir=upload_dir)

        assert fake_store.deleted == [doc_id]
        assert list(upload_dir.glob(f"{doc_id}_*")) == []

    async def test_delete_syncs_to_bm25_index(self, fake_store, fake_bm25, upload_dir):
        result = await document_service.ingest_document(
            "a.md", b"FastAPI", store=fake_store, bm25=fake_bm25, upload_dir=upload_dir
        )

        await document_service.delete_document(
            result["doc_id"], store=fake_store, bm25=fake_bm25, upload_dir=upload_dir
        )

        assert fake_bm25.deleted == [result["doc_id"]]
