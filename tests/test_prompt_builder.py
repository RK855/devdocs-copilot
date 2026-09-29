"""Prompt 构建器测试：把检索片段拼成模型 messages"""
from app.services.prompt_builder import SYSTEM_PROMPT, build_messages


def _hit(filename="a.md", page=None, content="FastAPI 用 uvicorn 启动", idx=0):
    return {
        "filename": filename,
        "page": page,
        "chunk_index": idx,
        "content": content,
        "score": 0.9,
    }


class TestBuildMessages:
    def test_returns_system_and_user_two_messages(self):
        messages = build_messages("怎么启动？", [_hit()])

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "怎么启动？"

    def test_system_contains_base_rules(self):
        content = build_messages("q", [_hit()])[0]["content"]

        assert SYSTEM_PROMPT in content
        assert "参考资料" in content

    def test_sources_are_numbered_with_filename(self):
        hits = [
            _hit(filename="guide.md", content="第一段"),
            _hit(filename="doc.pdf", page=3, content="第二段", idx=5),
        ]
        content = build_messages("q", hits)[0]["content"]

        assert "[1] (来源: guide.md)" in content
        assert "[2] (来源: doc.pdf, p.3)" in content
        assert "第一段" in content
        assert "第二段" in content

    def test_no_page_means_no_page_marker(self):
        content = build_messages("q", [_hit(filename="notes.txt", page=None)])[0]["content"]

        assert "p." not in content.split("(来源: notes.txt)")[1].split("\n")[0]


def test_format_hits_for_llm_numbers_sources():
    from app.services.prompt_builder import format_hits_for_llm

    text = format_hits_for_llm([
        {"filename": "a.md", "content": "AAA", "page": None},
        {"filename": "b.pdf", "content": "BBB", "page": 3},
    ])

    assert "[1] (来源: a.md)" in text
    assert "AAA" in text
    assert "[2] (来源: b.pdf, p.3)" in text
    assert "BBB" in text
