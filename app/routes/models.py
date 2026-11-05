"""聊天模型清单与「自定义模型」管理

GET 清单只返回 id / 展示名 / 真实模型 ID，绝不回传 API Key；
POST 添加会先发起一次真实最小请求（连通性测试），失败不落盘；
POST /test 供前端单独验证，DELETE 仅允许删除自定义模型。
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.config import RESOURCE_DIR, settings
from app.schemas import CustomModelIn
from app.services import model_registry

router = APIRouter()
logger = logging.getLogger(__name__)

# 预置语料灌入是进程级一次性动作：首次配置向量模型 Key 后补跑，
# 避免重复添加模型时反复触发；失败则释放标志，下次保存可重试
_seed_started = False


async def _seed_bundled_corpus() -> None:
    """把随包预置语料灌入向量库（同名文档跳过，幂等）。"""
    global _seed_started
    from app.db.bm25_store import bm25_store
    from app.db.vector_store import VectorStore
    from app.scripts.seed import seed_directory
    from app.services import document_service

    corpus_dir = RESOURCE_DIR / "desktop_seed"
    if not corpus_dir.is_dir():
        _seed_started = False
        return
    try:
        store = await asyncio.to_thread(VectorStore)
        if await asyncio.to_thread(store.count) > 0:
            return  # 库里已有文档（用户自己的或之前灌过），不重复灌

        # 复用进程内的 BM25 单例：灌入的文档无需重启即可被混合检索命中
        async def ingest(filename: str, data: bytes, source: str = "seed") -> dict:
            return await document_service.ingest_document(
                filename, data, store=store, bm25=bm25_store, source=source
            )

        async def list_docs() -> list[dict]:
            return await asyncio.to_thread(store.list_documents)

        def on_event(event: str, payload):
            if event == "failed":
                logger.warning("预置语料单篇失败：%s", payload)

        result = await seed_directory(
            corpus_dir, ingest=ingest, list_docs=list_docs, on_event=on_event
        )
        logger.info(
            "预置语料灌入完成：入库 %s 篇 / %s 块",
            len(result.ingested), result.total_chunks,
        )
    except Exception:
        # 灌库失败不影响用户已上传的文档；下次保存模型时自动重试
        _seed_started = False
        logger.warning("预置语料自动灌入失败", exc_info=True)


def _maybe_start_seed() -> bool:
    """向量模型 Key 就绪且本进程还没灌过时，后台启动灌库任务"""
    global _seed_started
    if _seed_started or not model_registry.embedding_ready():
        return False
    _seed_started = True
    asyncio.create_task(_seed_bundled_corpus())
    return True


@router.get("", summary="可切换的聊天模型")
async def list_chat_models():
    return {
        "models": model_registry.public_models(),
        "default": settings.CHAT_MODEL,
        # 首次使用引导：前端据此决定是否自动弹出模型配置弹窗
        "needs_setup": model_registry.needs_setup(),
        "embedding_ready": model_registry.embedding_ready(),
        # 向量/精排/视觉模型信息：前端「切换向量模型」只读展示
        "embedding": model_registry.embedding_info(),
        "presets": model_registry.PRESET_MODELS,
    }


@router.post("/test", summary="测试自定义模型连通性")
async def test_custom_model(payload: CustomModelIn):
    try:
        record = model_registry.validate_payload(payload.model_dump())
        latency = await run_in_threadpool(model_registry.test_connection, record)
    except model_registry.ModelRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "latency_ms": latency}


@router.post("", status_code=201, summary="测试通过后添加自定义模型")
async def add_custom_model(payload: CustomModelIn):
    try:
        result = await run_in_threadpool(
            model_registry.add_model, payload.model_dump()
        )
    except model_registry.ModelRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 桌面版在服务启动前才尝试灌库，此时 Key 还没配；用户保存 Key 后在这里补跑
    seed_started = _maybe_start_seed()
    return {**result, "seed_started": seed_started}


@router.delete("/{model_id}", summary="删除自定义模型")
async def delete_custom_model(model_id: str):
    try:
        removed = model_registry.delete_model(model_id)
    except model_registry.ModelRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="模型不存在")
    return {"ok": True}
