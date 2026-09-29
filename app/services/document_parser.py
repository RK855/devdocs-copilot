"""文档解析：md/txt 纯文本（UTF-8，失败兜底 GBK）；pdf 逐页提取并标注页码；docx 提取段落与表格"""
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


def _parse_plain_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk")


def _parse_docx(data: bytes) -> list[tuple[str, int | None]]:
    """docx 无页码概念，段落与表格单元格按阅读顺序拼成一个文本单元；全空返回 []"""
    doc = DocxDocument(BytesIO(data))

    parts: list[str] = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    text = "\n".join(parts)
    return [(text, None)] if text.strip() else []


def parse_document(data: bytes, filename: str) -> list[tuple[str, int | None]]:
    """返回 [(文本, 页码)]；md/txt/docx 页码为 None；PDF 空白页自动跳过"""
    suffix = Path(filename).suffix.lower()

    if suffix in (".md", ".txt"):
        return [(_parse_plain_text(data), None)]

    if suffix == ".docx":
        return _parse_docx(data)

    if suffix == ".pdf":
        reader = PdfReader(BytesIO(data))
        units = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                units.append((text, page_number))
        return units

    raise ValueError(f"不支持的文件类型：{suffix}")
