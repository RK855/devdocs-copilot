"""自定义聊天模型注册表

内置模型来自 .env（CHAT_MODEL / CHAT_MODEL_OPTIONS + AGNES_BASE_URL/KEY）；
用户在界面「添加自定义模型」后写入 APP_HOME/data/models.json，重启仍生效。
只管理聊天模型，embedding/rerank 固定走 .env，换嵌入模型会破坏既有索引。
"""
import json
import threading
import time
import uuid
from pathlib import Path

from app.config import settings

_lock = threading.Lock()
_CHAT_COMPLETIONS = "/chat/completions"

# 前端「首次使用」弹窗的预设：两个有免费额度的平台，用户只需填 Key
PRESET_MODELS = [
    {
        "key": "siliconflow",
        "label": "硅基流动 · Qwen3-8B",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_id": "Qwen/Qwen3-8B",
        "display_name": "硅基流动 Qwen3-8B",
        "provider": "siliconflow",
    },
    {
        "key": "zhipu",
        "label": "智谱 · GLM-4.5-Flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_id": "glm-4.5-flash",
        "display_name": "智谱 GLM-4.5-Flash",
        "provider": "zhipu",
    },
]


class ModelRegistryError(Exception):
    """自定义模型校验/连通性错误；路由层转 400 展示给用户"""


def _store_path() -> Path:
    path = Path(settings.MODELS_STORE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_custom() -> list[dict]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 文件损坏不阻塞应用启动；重新添加即可覆盖
        return []
    models = data.get("models") if isinstance(data, dict) else None
    return [m for m in models if isinstance(m, dict) and m.get("id")] if models else []


def _save_custom(models: list[dict]) -> None:
    path = _store_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"models": models}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _builtin_names() -> list[str]:
    return settings.chat_model_options


def _is_real_key(value: str) -> bool:
    """空值或模板占位符（your-xxx）都视为未配置"""
    value = (value or "").strip()
    return bool(value) and not value.startswith("your-")


def _provider_keys_path() -> Path:
    """硅基流动等供应商 Key 的持久化文件，与 models.json 同目录"""
    return _store_path().with_name("provider_keys.json")


def _load_provider_keys() -> dict:
    path = _provider_keys_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_provider_keys(keys: dict) -> None:
    path = _provider_keys_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def apply_provider_keys() -> None:
    """启动时把已保存的供应商 Key 灌回 settings，补位 .env 的空白配置"""
    keys = _load_provider_keys()
    if _is_real_key(keys.get("siliconflow_api_key", "")):
        settings.SILICONFLOW_API_KEY = keys["siliconflow_api_key"]
        return
    if _is_real_key(settings.SILICONFLOW_API_KEY):
        return
    # 兼容旧安装：早期只保存了 models.json（还没有 provider_keys.json），
    # 用户填过的「硅基流动」聊天 Key 直接复用到向量/精排/OCR，避免上传文档 401
    for record in _load_custom():
        if "siliconflow" not in (record.get("base_url") or "").lower():
            continue
        key = record.get("api_key", "")
        if _is_real_key(key):
            settings.SILICONFLOW_API_KEY = key
            _save_provider_keys({"siliconflow_api_key": key})
            return


def _remember_provider_key(record: dict) -> None:
    """用户填的模型若来自硅基流动，同一个 Key 直接复用到向量/精排/OCR"""
    if "siliconflow" not in record["base_url"].lower():
        return
    keys = _load_provider_keys()
    if keys.get("siliconflow_api_key") != record["api_key"]:
        keys["siliconflow_api_key"] = record["api_key"]
        _save_provider_keys(keys)
    settings.SILICONFLOW_API_KEY = record["api_key"]


def needs_setup() -> bool:
    """首次使用判定：没添加过自定义模型，且 .env 里的内置 Key 还是占位符"""
    if _load_custom():
        return False
    return not _is_real_key(settings.AGNES_API_KEY)


def embedding_ready() -> bool:
    """文档切块/检索/OCR 是否已具备硅基流动 Key"""
    return _is_real_key(settings.SILICONFLOW_API_KEY)


def embedding_info() -> dict:
    """当前向量/精排/视觉模型（界面只读展示）。

    嵌入模型由 .env 固定：换模型意味着既有向量全部失效，必须整库重嵌，
    因此不提供运行时切换，只暴露信息给前端展示。
    """
    return {
        "model": settings.EMBEDDING_MODEL,
        "dim": settings.EMBEDDING_DIM,
        "provider": "硅基流动",
        "rerank": settings.RERANK_MODEL,
        "vision": settings.VISION_MODEL,
        "ready": embedding_ready(),
    }


def public_models() -> list[dict]:
    """返回给前端的清单：绝不包含 api_key"""
    items = [{
        "id": name,
        "name": name,
        "model_id": name,
        "builtin": True,
    } for name in _builtin_names()]
    for record in _load_custom():
        items.append({
            "id": record["id"],
            "name": record.get("display_name") or record.get("model_id", ""),
            "model_id": record.get("model_id", ""),
            "builtin": False,
        })
    return items


def is_supported(model_id: str | None) -> bool:
    if model_id is None:
        return True
    if model_id in _builtin_names():
        return True
    return any(r["id"] == model_id for r in _load_custom())


def resolve(model_id: str | None) -> dict:
    """把前端传来的模型 id 解析为真实供应商参数；未知 id 抛 ModelRegistryError"""
    if model_id is None or model_id in _builtin_names():
        return {
            "api_key": settings.AGNES_API_KEY,
            "base_url": settings.AGNES_BASE_URL,
            "model": model_id or settings.CHAT_MODEL,
        }
    for record in _load_custom():
        if record["id"] == model_id:
            return {
                "api_key": record["api_key"],
                "base_url": _base_url(record),
                "model": record["model_id"],
            }
    raise ModelRegistryError(f"不支持的模型：{model_id}")


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def _base_url(record: dict) -> str:
    """OpenAI SDK 会在 base_url 后拼 /chat/completions；
    用户勾选「完整 URL」时填的是完整端点，这里把后缀剥掉"""
    url = _normalize_url(record["base_url"])
    if record.get("full_url") and url.endswith(_CHAT_COMPLETIONS):
        url = url[: -len(_CHAT_COMPLETIONS)]
    return url


def validate_payload(payload: dict) -> dict:
    """字段级校验，返回清洗后的记录（不含 id）"""
    base_url = _normalize_url(payload.get("base_url") or "")
    model_id = (payload.get("model_id") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    display_name = (payload.get("display_name") or "").strip()
    full_url = bool(payload.get("full_url"))

    if not base_url.startswith(("http://", "https://")):
        raise ModelRegistryError("请求地址必须以 http:// 或 https:// 开头")
    if not full_url and base_url.endswith(_CHAT_COMPLETIONS):
        raise ModelRegistryError(
            "未勾选「完整 URL」时不要以 /chat/completions 结尾，系统会自动补全"
        )
    if not model_id:
        raise ModelRegistryError("模型 ID 不能为空")
    if len(model_id) > 128:
        raise ModelRegistryError("模型 ID 不能超过 128 个字符")
    if not api_key:
        raise ModelRegistryError("API 密钥不能为空")
    if len(display_name) > 64:
        raise ModelRegistryError("模型展示名称不能超过 64 个字符")

    return {
        "base_url": base_url,
        "model_id": model_id,
        "api_key": api_key,
        "display_name": display_name or model_id,
        "full_url": full_url,
        "api_format": "openai",
    }


def test_connection(record: dict) -> int:
    """发起一次最小真实请求验证地址/模型/密钥；成功返回耗时毫秒"""
    from openai import OpenAI

    client = OpenAI(
        api_key=record["api_key"],
        base_url=_base_url(record),
        timeout=20.0,
        max_retries=0,
    )
    started = time.perf_counter()
    try:
        client.chat.completions.create(
            model=record["model_id"],
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=16,
            temperature=0,
        )
    except Exception as exc:
        raise ModelRegistryError(_explain(exc)) from exc
    return int((time.perf_counter() - started) * 1000)


def _explain(exc: Exception) -> str:
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return "API 密钥无效或没有访问权限"
    if name == "NotFoundError":
        return "地址或模型 ID 不正确（接口返回 404）"
    if name == "APIConnectionError":
        return "无法连接到该地址，请检查网络与 URL"
    if name in ("APITimeoutError", "TimeoutException"):
        return "连接超时，请检查地址是否可访问"
    text = str(exc).replace("\n", " ").strip()
    return f"连接失败：{text[:180]}" if text else f"连接失败：{name}"


def add_model(payload: dict) -> dict:
    """校验 → 真实连通性测试 → 落盘；测试失败不写入"""
    record = validate_payload(payload)
    test_connection(record)
    record["id"] = f"custom_{uuid.uuid4().hex[:10]}"
    with _lock:
        models = _load_custom()
        models.append(record)
        _save_custom(models)
    _remember_provider_key(record)
    return {
        "id": record["id"],
        "name": record["display_name"],
        "model_id": record["model_id"],
        "builtin": False,
    }


def delete_model(model_id: str) -> bool:
    if model_id in _builtin_names():
        raise ModelRegistryError("内置模型不能删除，请在 .env 中调整 CHAT_MODEL_OPTIONS")
    with _lock:
        models = _load_custom()
        remaining = [m for m in models if m["id"] != model_id]
        if len(remaining) == len(models):
            return False
        _save_custom(remaining)
        return True
