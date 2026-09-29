"""文档业务编排：校验 → 解析 → 切分 → 源文件落盘 → 写向量库 → 同步 BM25 索引"""
import asyncio
import uuid
from collections.abc import Iterable
from pathlib import Path

from app.config import settings
from app.db.bm25_store import bm25_store
from app.db.vector_store import VectorStore
from app.errors import DocumentValidationError
from app.services.chunker import split_text
from app.services.document_parser import parse_document
from app.services.document_validator import validate_upload

# 文档列表的视图口径：
#   library = 语料库：本次服务启动时已在库的文档（会话基线快照）
#   session = 我的上传：本次服务启动之后才入库的文档
# 进程重启后基线重新拍照，上一轮的"我的上传"自动并入"语料库"。
DOCUMENT_SCOPES = ("library", "session")

# 会话基线：进程内全局 doc_id 集合，由 lifespan 启动时拍照写入（纯内存、不持久化）
_session_baseline_ids: set[str] = set()


def capture_session_baseline(doc_ids: Iterable[str]) -> None:
    """把"启动时已在库"的 doc_id 集合整体替换为会话基线（先清空再写入）"""
    _session_baseline_ids.clear()
    _session_baseline_ids.update(doc_ids)


def reset_session_baseline() -> None:
    """清空基线（测试用）；基线为空时所有存活文档都归入 session 视图"""
    _session_baseline_ids.clear()


async def ingest_document(
    filename: str,
    data: bytes,
    *,
    store=None,
    bm25=None,
    upload_dir: Path | str | None = None,
    source: str = "upload",
) -> dict:
    # 1. 先校验，不合法什么都不留
    validate_upload(filename, len(data))

    # 2. 解析 + 切分（纯内存操作）
    chunks: list[str] = []
    pages: list[int | None] = []
    for text, page in parse_document(data, filename):
        for chunk in split_text(text):
            chunks.append(chunk)
            pages.append(page)

    if not chunks:
        raise DocumentValidationError("文档解析后没有可用内容")

    # 3. 生成 doc_id，源文件以 doc_id 前缀落盘（同名文件天然不覆盖）
    doc_id = uuid.uuid4().hex
    target_dir = Path(upload_dir or settings.UPLOAD_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_path = target_dir / f"{doc_id}_{filename}"
    await asyncio.to_thread(saved_path.write_bytes, data)

    # 4. 写入向量库（阻塞调用扔线程池，不卡死事件循环）
    vector_store = store or await asyncio.to_thread(VectorStore)
    pages_arg = pages if any(p is not None for p in pages) else None
    await asyncio.to_thread(
        vector_store.add_document, doc_id, chunks, filename, pages_arg, source
    )

    # 5. 同步写入 BM25 内存索引（F5）：与向量库同批 chunks，失败不回滚——启动重建兜底
    bm25_index = bm25 if bm25 is not None else bm25_store
    await asyncio.to_thread(bm25_index.add_document, doc_id, chunks, filename, pages_arg)

    return {
        "doc_id": doc_id,
        "filename": filename,
        "chunk_count": len(chunks),
        "source": source,
    }


async def list_documents(*, store=None, scope: str | None = None) -> list[dict]:
    """列出文档。scope=None 全量；library=会话基线内（语料库）；session=基线外（我的上传）。

    与向量库 metadata 的 source 章（seed/upload）是两个维度：视图归属只看
    「文档是否在服务启动时已存在」，与入库渠道无关。
    """
    vector_store = store or await asyncio.to_thread(VectorStore)
    docs = await asyncio.to_thread(vector_store.list_documents)
    if scope is None:
        return docs
    if scope not in DOCUMENT_SCOPES:
        raise ValueError(f"非法 scope 取值：{scope}，只接受 library / session")
    if scope == "library":
        return [doc for doc in docs if doc["doc_id"] in _session_baseline_ids]
    return [doc for doc in docs if doc["doc_id"] not in _session_baseline_ids]


async def delete_document(
    doc_id: str,
    *,
    store=None,
    bm25=None,
    upload_dir: Path | str | None = None,
) -> None:
    vector_store = store or await asyncio.to_thread(VectorStore)
    await asyncio.to_thread(vector_store.delete_document, doc_id)

    # 同步移除 BM25 中该文档的段落（内部过滤数组后重建索引）
    bm25_index = bm25 if bm25 is not None else bm25_store
    await asyncio.to_thread(bm25_index.delete_document, doc_id)

    # 同步清理该文档的源文件（按 doc_id 前缀定位）
    target_dir = Path(upload_dir or settings.UPLOAD_DIR)
    for path in target_dir.glob(f"{doc_id}_*"):
        await asyncio.to_thread(path.unlink)
