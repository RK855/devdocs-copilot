"""图片 / 扫描件转写：用硅基流动视觉模型做逐字 OCR（不总结、不补全）"""
import base64

import httpx

from app.config import settings

OCR_PROMPT = (
    "你是 OCR 引擎。请逐字转写图片中的全部文字，保持原有阅读顺序与分行；"
    "不要总结、不要解释、不要补全看不清的内容。只输出转写文字。"
)

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

SUPPORTED_IMAGE_SUFFIXES = frozenset(_MIME_BY_SUFFIX)


def mime_for_suffix(suffix: str) -> str | None:
    return _MIME_BY_SUFFIX.get(suffix.lower())


def transcribe_image(data: bytes, mime: str = "image/png") -> str:
    """把一张图片转成文字；未配置 key、请求失败或识别为空都抛 ValueError（带可读原因）"""
    if not settings.SILICONFLOW_API_KEY:
        raise ValueError("未配置 SILICONFLOW_API_KEY，无法对图片/扫描件做视觉转写")

    encoded = base64.b64encode(data).decode("ascii")
    payload = {
        "model": settings.VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                {"type": "text", "text": OCR_PROMPT},
            ],
        }],
        "max_tokens": 2048,
        "temperature": 0,
    }
    try:
        response = httpx.post(
            f"{settings.SILICONFLOW_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}"},
            json=payload,
            timeout=settings.VISION_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise ValueError(f"视觉转写请求失败：{exc}") from exc

    if response.status_code != 200:
        raise ValueError(f"视觉转写失败（HTTP {response.status_code}）：{response.text[:200]}")

    try:
        text = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("视觉转写返回结构异常") from exc

    text = (text or "").strip()
    if not text:
        raise ValueError("视觉模型未识别到文字，可能是空白图片")
    return text
