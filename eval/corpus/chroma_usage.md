# Chroma 向量库使用

## 基本概念

Chroma 是嵌入式向量数据库，核心概念是 collection（集合，类似表）、document（文本）、embedding（向量）、metadata（元数据）、id（唯一标识）。一个 collection 有一个固定维度，写入向量维度必须一致。

## 创建与写入

```python
import chromadb

client = chromadb.PersistentClient(path="./data/chroma")
collection = client.get_or_create_collection(name="docs", metadata={"hnsw:space": "cosine"})

collection.add(
    ids=["c1", "c2"],
    documents=["第一段", "第二段"],
    embeddings=[[0.1] * 1024, [0.2] * 1024],
    metadatas=[{"doc_id": "d1", "chunk_index": 0}, {"doc_id": "d1", "chunk_index": 1}],
)
```

如果不传 embeddings，Chroma 会用它默认的嵌入函数自动计算，这通常与项目使用的模型不一致，导致检索质量异常。生产项目应显式传入 embedding。

## 查询

```python
result = collection.query(
    query_embeddings=[[...]],
    n_results=5,
    where={"doc_id": {"$in": ["d1", "d2"]}},
)
```

返回结构包含 ids、documents、metadatas、distances。距离越小越相似（余弦距离 0 表示完全相同）。不要把它误当成相似度分数，需要转换。

## 元数据过滤

`where` 支持等值、比较、in、and/or。过滤在向量检索前生效，能缩小候选范围，也能实现按文档范围检索。注意过滤条件要建索引或控制取值基数，否则会拖慢查询。

## 更新与删除

`update` 修改文档、向量或元数据；`upsert` 存在则更新否则插入；`delete(ids=[...])` 删除指定 id，也可以按 `where` 批量删除。删除文档时要同时删除其所有 chunk，否则会留下孤立向量。

## 持久化

`PersistentClient` 把数据落盘到指定目录，重启后仍可读取；`EphemeralClient` 只存在内存。测试时用临时目录 + EphemeralClient 可避免污染。

Windows 上文件句柄释放有延迟，临时目录清理可能抛 PermissionError，实践上常用 `mkdtemp` + `rmtree(ignore_errors=True)` 兜底。

## collection 命名与隔离

不同环境、不同评测集应使用不同 collection，避免数据混在一起。collection 名称要稳定，改名等于新建库。维度变更必须删库重建，因为 collection 维度不可变。

## 性能

HNSW 索引的 `M` 与 `ef_construction` 影响召回与构建时间。数据量小时默认参数足够。批量写入比逐条写入快得多，尽量攒批。查询时的 `n_results` 不要一次要太多，过滤后再排序更划算。

## 常见坑

- 忘记显式传 embedding，用了默认模型
- 维度不一致导致写入失败
- 距离当相似度用
- 删除文档只删向量没删 BM25 索引
- 用同一个 collection 混放不同维度的数据
- 测试污染真实库
