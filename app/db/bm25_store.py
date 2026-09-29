"""BM25 关键词检索（F5）

与向量检索互补：向量懂语义，BM25 精于词面匹配（代码标识符、报错信息、专有名词）。
纯内存索引，三条平行数组作为真相源：
  _tokens[i]   ── 第 i 个 chunk 的分词结果
  _contents[i] ── 第 i 个 chunk 原文
  _metadatas[i]── 第 i 个 chunk 的归属信息
BM25Okapi 对象本身不可变，任何增删后整体重建（语料量级轻，开销可忽略）。
启动时从 Chroma 全量重建兜底，保证与向量库不漂移。
"""
import re
import threading

import jieba
from rank_bm25 import BM25Okapi

# 第一轮：英文/数字代码词（含下划线，整体保留）或连续中文段，其余字符天然当分隔符
_CODE_OR_CJK = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+")

# 停用词：任何问句里都高频出现、对区分文档毫无贡献的词。
# 不剔除的话"的/与/怎么"会让候选预筛永远命中，BM25 的空结果信号失效（F6 接入问答时的实战教训）。
_STOPWORDS = frozenset({
    # 中文虚词/代词/高频疑问套话
    "的", "了", "和", "与", "及", "或", "是", "在", "也", "都", "就", "还", "又", "而",
    "我", "你", "他", "她", "它", "们",
    "把", "被", "让", "给", "向", "于", "对", "为",
    "着", "过", "吗", "呢", "吧", "啊",
    "什么", "怎么", "怎样", "如何", "为什么", "哪", "哪里", "哪个",
    "一个", "没有", "这个", "那个", "可以", "需要",
    "不", "很", "最",
    # 英文高频虚词
    "a", "an", "the", "is", "are", "was", "were", "to", "of", "in", "on", "and", "or",
    "how", "what", "why",
})


def tokenize(text: str) -> list[str]:
    """建索引与查询共用的唯一切词入口：小写 → 代码词整体保留 → 中文段交 jieba → 去停用词。

    两边规则必须完全一致，否则 @app.get 索引切成 app/get，查询切法不同就形同陌路。
    例：@app.get → [app, get]；query_similar → [query_similar]；红烧肉的做法 → [红烧肉, 做法]
    """
    tokens: list[str] = []
    for piece in _CODE_OR_CJK.findall(text.lower()):
        if piece[0].isascii():
            candidates = [piece]           # 代码/英文词整体保留，下划线与数字不拆
        else:
            candidates = (t for t in jieba.lcut(piece) if t.strip())
        tokens.extend(t for t in candidates if t not in _STOPWORDS)
    return tokens


class BM25Store:
    def __init__(self):
        self._tokens: list[list[str]] = []
        self._contents: list[str] = []
        self._metadatas: list[dict] = []
        self._bm25: BM25Okapi | None = None
        self._lock = threading.RLock()

    def _rebuild_index(self) -> None:
        """由平行数组重建 BM25Okapi；空语料置 None（空对象查询会除零）"""
        self._bm25 = BM25Okapi(self._tokens) if self._tokens else None

    def add_document(
        self,
        doc_id: str,
        chunks: list[str],
        filename: str,
        pages: list[int | None] | None = None,
    ) -> None:
        """追加一篇文档的全部 chunk（chunk_id 规则与 VectorStore 完全一致）"""
        with self._lock:
            for i, content in enumerate(chunks):
                self._tokens.append(tokenize(content))
                self._contents.append(content)
                metadata = {"doc_id": doc_id, "filename": filename, "chunk_index": i}
                if pages is not None:
                    metadata["page"] = pages[i]
                else:
                    metadata["page"] = None
                self._metadatas.append(metadata)
            self._rebuild_index()

    def delete_document(self, doc_id: str) -> None:
        """移除该文档的全部 chunk 后重建；doc_id 不存在时静默无操作"""
        with self._lock:
            kept = [
                (tokens, content, metadata)
                for tokens, content, metadata in zip(self._tokens, self._contents, self._metadatas)
                if metadata["doc_id"] != doc_id
            ]
            if len(kept) == len(self._tokens):
                return
            self._tokens = [item[0] for item in kept]
            self._contents = [item[1] for item in kept]
            self._metadatas = [item[2] for item in kept]
            self._rebuild_index()

    def clear(self) -> None:
        """清空内存索引（主要给测试隔离用）"""
        with self._lock:
            self._tokens = []
            self._contents = []
            self._metadatas = []
            self._bm25 = None

    def rebuild_from_vector_store(self, vector_store) -> None:
        """启动恢复：从 VectorStore.get_all_chunks() 全量重建，整体替换旧索引"""
        chunks = vector_store.get_all_chunks()
        with self._lock:
            self._tokens = [tokenize(c["content"]) for c in chunks]
            self._contents = [c["content"] for c in chunks]
            self._metadatas = [
                {
                    "doc_id": c["doc_id"],
                    "filename": c["filename"],
                    "chunk_index": c["chunk_index"],
                    "page": c.get("page"),
                }
                for c in chunks
            ]
            self._rebuild_index()

    def search(
        self, query: str, top_k: int = 20, doc_ids: list[str] | None = None
    ) -> list[dict]:
        """BM25 检索，返回结构与 VectorStore.query_similar 对齐；score 为 BM25 原始分。

        先按词面交集筛候选（零交集就是无关，不该凑数），再交 BM25 分排序。
        doc_ids 非空时把范围过滤并入候选预筛——必须在取 top_k 之前过滤，
        否则范围外的高分会占光名额。注：极小语料下罕见词 IDF 可能为负
        （BM25 标准公式使然），真实语料不影响排序。
        """
        query_tokens = tokenize(query)
        with self._lock:
            if not query_tokens or self._bm25 is None:
                return []

            scope = set(doc_ids) if doc_ids else None
            query_vocab = set(query_tokens)
            candidates = [
                i for i, doc_tokens in enumerate(self._tokens)
                if query_vocab & set(doc_tokens)
                and (scope is None or self._metadatas[i]["doc_id"] in scope)
            ]
            if not candidates:
                return []

            scores = self._bm25.get_scores(query_tokens)
            candidates.sort(key=lambda i: scores[i], reverse=True)

            hits = []
            for idx in candidates[:top_k]:
                metadata = self._metadatas[idx]
                hits.append({
                    "chunk_id": f"{metadata['doc_id']}:chunk-{metadata['chunk_index']}",
                    "content": self._contents[idx],
                    "doc_id": metadata["doc_id"],
                    "filename": metadata["filename"],
                    "chunk_index": metadata["chunk_index"],
                    "page": metadata["page"],
                    "score": float(scores[idx]),
                })
            return hits


# 全局单例：document_service 与 lifespan 共用同一份内存索引
bm25_store = BM25Store()
