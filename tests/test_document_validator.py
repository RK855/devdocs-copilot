"""文档上传校验规则 —— 行为测试"""
import pytest

from app.errors import DocumentValidationError
from app.services.document_validator import MAX_FILE_SIZE, validate_upload


class TestValidateUpload:
    def test_rejects_unsupported_extension(self):
        # 老版 .doc 二进制格式不在支持范围（仅支持新格式 .docx）
        with pytest.raises(DocumentValidationError, match="不支持"):
            validate_upload("notes.doc", size=100)

    @pytest.mark.parametrize("name", ["guide.md", "guide.txt", "paper.pdf", "paper.docx"])
    def test_accepts_supported_extensions(self, name):
        validate_upload(name, size=100)

    def test_extension_match_is_case_insensitive(self):
        validate_upload("README.MD", size=100)

    def test_docx_extension_match_is_case_insensitive(self):
        validate_upload("Notes.DOCX", size=100)

    def test_rejects_file_without_extension(self):
        with pytest.raises(DocumentValidationError):
            validate_upload("Makefile", size=100)

    def test_rejects_empty_file(self):
        with pytest.raises(DocumentValidationError, match="空"):
            validate_upload("empty.md", size=0)

    def test_rejects_oversized_file(self):
        with pytest.raises(DocumentValidationError, match="10MB"):
            validate_upload("big.pdf", size=MAX_FILE_SIZE + 1)

    def test_accepts_file_at_exact_size_limit(self):
        validate_upload("edge.md", size=MAX_FILE_SIZE)
