"""本地语料一键灌库脚本

用法（在项目根目录、激活虚拟环境后）：
    python -m app.scripts.seed eval/corpus
    python -m app.scripts.seed D:/docs --recursive

遍历目录下受支持的文档（.md / .txt / .pdf / .docx），走与网页上传完全相同
的 ingest_document 链路：校验 → 解析 → 切分 → 源文件落盘 uploads → 写 Chroma
→ 同步 BM25。库中已存在的同名文件默认跳过，因此可以安全重复执行。

注意：BM25 是纯内存索引，脚本进程结束后随之释放；下次服务启动时会自动从
Chroma 全量重建（见 main.py lifespan），所以灌完库直接启动服务即可。
"""
import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.db.bm25_store import BM25Store
from app.db.vector_store import VectorStore
from app.services import document_service
from app.services.document_validator import ALLOWED_EXTENSIONS


@dataclass
class SeedResult:
    """灌库结果：成功入库 / 跳过（同名已存在）/ 失败（文件名, 原因）"""

    ingested: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_chunks(self) -> int:
        return sum(item.get("chunk_count", 0) for item in self.ingested)


def iter_candidate_files(directory: Path, recursive: bool) -> list[Path]:
    """目录下受支持扩展名的文件，按路径排序保证灌库顺序确定"""
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
    )


async def seed_directory(
    directory: Path | str,
    *,
    recursive: bool = False,
    ingest=None,
    list_docs=None,
    on_event=None,
    source: str = "seed",
) -> SeedResult:
    """把目录内文档灌入向量库。

    ingest / list_docs 可注入（测试用 Fake）；on_event(event: str, payload)
    用于进度回调，事件类型：ingested / skipped / failed。
    source 为入库语料盖的来源章，脚本场景恒为 seed（预置语料）。
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"目录不存在或不是目录：{directory}")

    ingest = ingest or document_service.ingest_document
    list_docs = list_docs or document_service.list_documents

    # 以文件名为幂等键：脚本重跑时已入库的文件跳过，避免重复 embedding
    existing_names = {doc["filename"] for doc in await list_docs()}
    result = SeedResult()

    for path in iter_candidate_files(directory, recursive):
        if path.name in existing_names:
            result.skipped.append(path.name)
            if on_event:
                on_event("skipped", path.name)
            continue
        try:
            data = await asyncio.to_thread(path.read_bytes)
            item = await ingest(path.name, data, source=source)
        except Exception as exc:  # 单文件失败不拖垮整批，结果里列明原因
            result.failed.append((path.name, str(exc)))
            if on_event:
                on_event("failed", (path.name, str(exc)))
        else:
            result.ingested.append(item)
            if on_event:
                on_event("ingested", item)

    return result


async def run_seed(directory: Path, recursive: bool) -> SeedResult:
    """真实接线：整个批次复用同一 VectorStore / BM25 实例。

    桌面版启动器（run_desktop.py）首启灌库时直接复用本函数，
    与命令行 ``python -m app.scripts.seed`` 走完全相同的链路。
    """
    store = await asyncio.to_thread(VectorStore)
    bm25 = BM25Store()

    async def ingest(filename: str, data: bytes, source: str = "seed") -> dict:
        return await document_service.ingest_document(
            filename, data, store=store, bm25=bm25, source=source
        )

    async def list_docs() -> list[dict]:
        return await asyncio.to_thread(store.list_documents)

    def on_event(event, payload):
        if event == "ingested":
            print(f"  [入库] {payload['filename']} → {payload['chunk_count']} 块")
        elif event == "skipped":
            print(f"  [跳过] {payload}（库中已存在同名文档）")
        else:
            name, reason = payload
            print(f"  [失败] {name}：{reason}")

    print(f"开始灌库：{directory}（递归={recursive}）")
    result = await seed_directory(
        directory,
        recursive=recursive,
        ingest=ingest,
        list_docs=list_docs,
        on_event=on_event,
    )
    print(
        f"完成：入库 {len(result.ingested)} 个 / {result.total_chunks} 块，"
        f"跳过 {len(result.skipped)} 个，失败 {len(result.failed)} 个"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把本地目录的文档批量灌入正式向量库（.md/.txt/.pdf/.docx）"
    )
    parser.add_argument("directory", help="语料目录路径")
    parser.add_argument(
        "--recursive", action="store_true", help="递归遍历子目录（默认只灌顶层）"
    )
    args = parser.parse_args()

    result = asyncio.run(run_seed(Path(args.directory), args.recursive))
    if result.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
