"""文本切分：长文档按递归分隔符切成带重叠的小块"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

# 分隔符优先级：段落 > 换行 > 中文句读 > 英文句读 > 空格 > 硬切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]


def split_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[str]:
    if not text or not text.strip():
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap,
        separators=SEPARATORS,
        keep_separator=True,
    )
    return [chunk for chunk in splitter.split_text(text) if chunk.strip()]
