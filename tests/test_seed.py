"""语料灌库脚本行为测试：遍历 / 跳过已存在 / 单点失败不中断 / 递归"""
import pytest

from app.scripts.seed import SeedResult, seed_directory


def write(dir_path, name, content="内容"):
    path = dir_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class FakeIngester:
    """记录调用；fail_names 中的文件名抛异常，模拟单文件入库失败"""

    def __init__(self, fail_names=None):
        self.calls = []
        self.fail_names = set(fail_names or [])

    async def __call__(self, filename, data, source="seed"):
        self.calls.append((filename, data, source))
        if filename in self.fail_names:
            raise ValueError("模拟解析失败")
        return {"doc_id": f"id-{filename}", "filename": filename, "chunk_count": 2, "source": source}


async def fake_list_empty():
    return []


class TestSeedDirectory:
    async def test_ingests_supported_files_in_sorted_order(self, tmp_path):
        write(tmp_path, "b.md", "第二篇")
        write(tmp_path, "a.txt", "第一篇")
        write(tmp_path, "ignore.log", "不受支持")
        ingester = FakeIngester()

        result = await seed_directory(
            tmp_path, ingest=ingester, list_docs=fake_list_empty
        )

        assert isinstance(result, SeedResult)
        assert [item["filename"] for item in result.ingested] == ["a.txt", "b.md"]
        assert result.skipped == [] and result.failed == []
        assert result.total_chunks == 4
        # 文件内容确实被读出并传给 ingest，且盖的是预置语料的章
        by_name = {name: (data, src) for name, data, src in ingester.calls}
        assert by_name["b.md"] == ("第二篇".encode("utf-8"), "seed")

    async def test_ingested_items_carry_seed_source(self, tmp_path):
        write(tmp_path, "a.md", "第一篇")
        ingester = FakeIngester()

        result = await seed_directory(
            tmp_path, ingest=ingester, list_docs=fake_list_empty
        )

        assert all(item["source"] == "seed" for item in result.ingested)

    async def test_docx_is_a_supported_candidate(self, tmp_path):
        write(tmp_path, "notes.docx", "docx 也是候选")
        ingester = FakeIngester()

        result = await seed_directory(
            tmp_path, ingest=ingester, list_docs=fake_list_empty
        )

        assert [item["filename"] for item in result.ingested] == ["notes.docx"]

    async def test_skips_filenames_already_in_store(self, tmp_path):
        write(tmp_path, "exists.md")
        write(tmp_path, "new.md")
        ingester = FakeIngester()

        async def list_docs():
            return [{"doc_id": "x", "filename": "exists.md", "chunk_count": 3}]

        result = await seed_directory(tmp_path, ingest=ingester, list_docs=list_docs)

        assert result.skipped == ["exists.md"]
        assert [item["filename"] for item in result.ingested] == ["new.md"]

    async def test_non_recursive_ignores_subdirectories(self, tmp_path):
        write(tmp_path, "top.md")
        write(tmp_path, "sub/nested.md")
        ingester = FakeIngester()

        result = await seed_directory(
            tmp_path, recursive=False, ingest=ingester, list_docs=fake_list_empty
        )

        assert [item["filename"] for item in result.ingested] == ["top.md"]

    async def test_recursive_walks_subdirectories(self, tmp_path):
        write(tmp_path, "top.md")
        write(tmp_path, "sub/nested.md")
        ingester = FakeIngester()

        result = await seed_directory(
            tmp_path, recursive=True, ingest=ingester, list_docs=fake_list_empty
        )

        names = {item["filename"] for item in result.ingested}
        assert names == {"top.md", "nested.md"}

    async def test_failure_is_recorded_and_loop_continues(self, tmp_path):
        write(tmp_path, "bad.md")
        write(tmp_path, "good.md")
        ingester = FakeIngester(fail_names={"bad.md"})

        result = await seed_directory(
            tmp_path, ingest=ingester, list_docs=fake_list_empty
        )

        assert [item["filename"] for item in result.ingested] == ["good.md"]
        assert result.failed == [("bad.md", "模拟解析失败")]

    async def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            await seed_directory(
                tmp_path / "nope", ingest=FakeIngester(), list_docs=fake_list_empty
            )

    async def test_empty_directory_yields_empty_result(self, tmp_path):
        result = await seed_directory(
            tmp_path, ingest=FakeIngester(), list_docs=fake_list_empty
        )
        assert result.ingested == [] and result.skipped == [] and result.failed == []
