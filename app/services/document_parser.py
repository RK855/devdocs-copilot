"""文档解析：md/txt 纯文本（UTF-8，失败兜底 GBK）；pdf 逐页按坐标提取，扫描页走视觉转写；
图片（png/jpg/jpeg/webp）直接视觉转写；docx 提取段落与表格"""
from io import BytesIO
from pathlib import Path

import pymupdf
from docx import Document as DocxDocument

from app.config import settings
from app.services.vision_service import mime_for_suffix, transcribe_image, SUPPORTED_IMAGE_SUFFIXES


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


def _ocr_pdf_page(page) -> str:
    """把 PDF 页渲染成 PNG 后交给视觉模型逐字转写；页面过大时按 110 dpi 控制体积"""
    png = page.get_pixmap(dpi=110).tobytes("png")
    return transcribe_image(png, "image/png")


def _parse_pdf(data: bytes) -> list[tuple[str, int | None]]:
    """PyMuPDF 按文本块坐标自上而下排序，恢复视觉阅读顺序；空白/扫描页走视觉转写。

    pypdf 按内容流顺序拼接，多栏简历或带翻译层的 PDF 会读成半句开头、
    章节前后颠倒（实测一份简历被切成 6 块，块首直接是"...务域分 6 库"）。
    """
    units: list[tuple[str, int | None]] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page_number, page in enumerate(doc, start=1):
            # (左上 x, 上 y, 右下 x, 下 y, 文本, 块号, 类型)，只保留正文块
            blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
            blocks.sort(key=lambda b: (round(b[1], 1), b[0]))
            text = "\n\n".join(b[4].strip() for b in blocks)
            if not text.strip() and page_number <= settings.VISION_MAX_PAGES:
                # 没有文本层 = 扫描页/图片页；OCR 失败要让上传方看到明确原因，不静默跳过
                text = _ocr_pdf_page(page)
            if text.strip():
                units.append((text, page_number))
    return units


def _parse_image(data: bytes, suffix: str) -> list[tuple[str, int | None]]:
    mime = mime_for_suffix(suffix)
    if mime is None:
        raise ValueError(f"不支持的图片类型：{suffix}")
    return [(transcribe_image(data, mime), None)]


def parse_document(data: bytes, filename: str) -> list[tuple[str, int | None]]:
    """返回 [(文本, 页码)]；md/txt/docx/图片页码为 None；PDF 保留页码，扫描页自动 OCR"""
    suffix = Path(filename).suffix.lower()

    if suffix in (".md", ".txt"):
        return [(_parse_plain_text(data), None)]

    if suffix == ".docx":
        return _parse_docx(data)

    if suffix == ".pdf":
        return _parse_pdf(data)

    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return _parse_image(data, suffix)

    raise ValueError(f"不支持的文件类型：{suffix}")
