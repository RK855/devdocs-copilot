"""文档上传校验规则"""
from pathlib import Path

from app.errors import DocumentValidationError

ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def validate_upload(filename: str, size: int) -> None:
    """校验通过返回 None；不满足规则抛 DocumentValidationError"""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(f"不支持的文件类型：{extension or '无扩展名'}，仅支持 .md / .txt / .pdf / .docx")

    if size == 0:
        raise DocumentValidationError("文件内容为空")

    if size > MAX_FILE_SIZE:
        raise DocumentValidationError("文件超过 10MB 大小限制")
