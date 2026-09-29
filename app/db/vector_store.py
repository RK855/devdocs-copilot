"""Chroma 向量库封装：文档写入、相似查询、列表聚合、按文档删除"""
import chromadb

from app.config import settings
from app.db.embeddings import SiliconFlowEmbeddingFunction

# 文档来源：seed=脚本灌库的预置语料 / upload=网页上传
DOCUMENT_SOURCES = ("seed", "upload")
# 升级前写入的历史 chunk 没有 source 字段，列表聚合时的防御性归类
LEGACY_DEFAULT_SOURCE = "seed"


class VectorStore:
    def __init__(self, path=None, collection_name=None, embedding_function=None):
        self._client = chromadb.PersistentClient(path=str(path or settings.CHROMA_DATA_DIR))
        self._collection = self._client.get_or_create_collection(
            name=collection_name or settings.COLLECTION_NAME,
            embedding_function=embedding_function or SiliconFlowEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )

    def add_document(
        self,
        doc_id: str,
        chunks: list[str],
        filename: str,
        pages: list[int] | None = None,
        source: str = "upload",
    ) -> None:
        ids = [f"{doc_id}:chunk-{i}" for i in range(len(chunks))]
        metadatas = []
        for i in range(len(chunks)):
            metadata = {"doc_id": doc_id, "filename": filename, "chunk_index": i, "source": source}
            if pages is not None:
                metadata["page"] = pages[i]
            metadatas.append(metadata)

        # 只传 documents，embedding 由 collection 绑定的 bge-m3 EF 自动批量生成
        self._collection.add(ids=ids, documents=list(chunks), metadatas=metadatas)

    def count(self) -> int:
        return self._collection.count()

    def query_similar(
        self, query_text: str, top_k: int = 5, doc_ids: list[str] | None = None
    ) -> list[dict]:
        # doc_ids 限定检索范围（文档级圈选）；None/空列表均为全库
        where = {"doc_id": {"$in": list(doc_ids)}} if doc_ids else None
        result = self._collection.query(
            query_texts=[query_text], n_results=top_k, where=where
        )

        hits = []
        for i in range(len(result["ids"][0])):
            metadata = result["metadatas"][0][i]
            distance = result["distances"][0][i]
            hits.append({
                "chunk_id": result["ids"][0][i],
                "content": result["documents"][0][i],
                "doc_id": metadata["doc_id"],
                "filename": metadata["filename"],
                "chunk_index": metadata["chunk_index"],
                "page": metadata.get("page"),
                "score": 1 - distance,  # cosine distance 转相似度
            })
        return hits

    def get_all_chunks(self) -> list[dict]:
        """拉取全部 chunk 的原文与 metadata，按 (doc_id, chunk_index) 排序。

        专供 BM25 启动重建：确定性顺序保证内存索引每次重建结果一致。
        """
        result = self._collection.get(include=["documents", "metadatas"])

        chunks = []
        for i in range(len(result["ids"])):
            metadata = result["metadatas"][i]
            chunks.append({
                "chunk_id": result["ids"][i],
                "content": result["documents"][i],
                "doc_id": metadata["doc_id"],
                "filename": metadata["filename"],
                "chunk_index": metadata["chunk_index"],
                "page": metadata.get("page"),
            })
        chunks.sort(key=lambda c: (c["doc_id"], c["chunk_index"]))
        return chunks

    def list_documents(self, source: str | None = None) -> list[dict]:
        result = self._collection.get(include=["metadatas"])

        grouped: dict[str, dict] = {}
        for metadata in result["metadatas"]:
            doc_id = metadata["doc_id"]
            # 历史数据无 source 字段时防御性归类（backfill 跑完后不会走到）
            doc_source = metadata.get("source", LEGACY_DEFAULT_SOURCE)
            if doc_id not in grouped:
                grouped[doc_id] = {
                    "doc_id": doc_id,
                    "filename": metadata["filename"],
                    "chunk_count": 0,
                    "source": doc_source,
                }
            grouped[doc_id]["chunk_count"] += 1

        docs = list(grouped.values())
        if source is not None:
            docs = [doc for doc in docs if doc["source"] == source]
        return docs

    def backfill_legacy_source(self, default_source: str = "seed") -> dict:
        """一次性迁移：给缺少 source 字段的历史 chunk 原地补标来源。

        只更新 metadata（Chroma update 覆盖该条 metadata，需传完整字典），
        不动正文、不重新 embedding。返回补标 chunk 数与涉及文档 id 列表。
        """
        result = self._collection.get(include=["metadatas"])
        legacy_ids: list[str] = []
        legacy_metadatas: list[dict] = []
        doc_ids: set[str] = set()
        for chunk_id, metadata in zip(result["ids"], result["metadatas"]):
            if "source" in metadata:
                continue
            new_metadata = dict(metadata)
            new_metadata["source"] = default_source
            legacy_ids.append(chunk_id)
            legacy_metadatas.append(new_metadata)
            doc_ids.add(metadata["doc_id"])

        if legacy_ids:
            self._collection.update(ids=legacy_ids, metadatas=legacy_metadatas)
        return {"chunks": len(legacy_ids), "doc_ids": sorted(doc_ids)}

    def delete_document(self, doc_id: str) -> None:
        self._collection.delete(where={"doc_id": {"$eq": doc_id}})
