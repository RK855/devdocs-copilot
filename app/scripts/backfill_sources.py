"""一次性迁移：给历史 chunk 补标 source=seed（预置语料）

用法（在项目根目录、激活虚拟环境后）：
    python -m app.scripts.backfill_sources

升级"语料来源分视图"功能前入库的文档没有 source 字段。本脚本原地补 metadata，
不改正文、不重新 embedding；重复执行安全（第二次补标数为 0）。
"""
import asyncio
import sys

from app.db.vector_store import VectorStore


async def _run() -> int:
    store = await asyncio.to_thread(VectorStore)
    result = await asyncio.to_thread(store.backfill_legacy_source, "seed")
    print(
        f"迁移完成：补标 {result['chunks']} 个 chunk，"
        f"涉及 {len(result['doc_ids'])} 个文档"
    )
    for doc_id in result["doc_ids"]:
        print(f"  - {doc_id}")
    if result["chunks"] == 0:
        print("（没有需要补标的历史数据）")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
