"""
DevDocs Copilot —— 技术文档智能问答助手
应用入口：应用初始化、中间件、路由注册与静态挂载都在这里编排
"""
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import RESOURCE_DIR, settings
from app.db.bm25_store import bm25_store
from app.db.vector_store import VectorStore
from app.errors import DocumentValidationError
from app.routes.chat import router as chat_router
from app.routes.agent import router as agent_router
from app.routes.documents import router as documents_router
from app.services import document_service

# 前端静态目录：开发态在项目根，桌面版在包内 _MEIPASS，从任意工作目录启动都能找到
STATIC_DIR = RESOURCE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期
    启动：确保运行所需目录存在；BM25 内存索引从 Chroma 全量重建（重启不丢、不漂移）；
          给会话基线拍照（语料库/我的上传两视图的划分依据，详见 document_service）
    关闭：预留资源清理口
    """
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.CHROMA_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _rebuild_bm25() -> None:
        store = VectorStore()
        bm25_store.rebuild_from_vector_store(store)
        # 重建同一时刻顺手拍照：此时刻已在库的文档归"语料库"，之后上传的归"我的上传"
        document_service.capture_session_baseline(
            doc["doc_id"] for doc in store.list_documents()
        )

    await asyncio.to_thread(_rebuild_bm25)
    yield
    # 关闭时的资源清理（暂无）


# ========== 1. 创建 FastAPI 应用 ==========
app = FastAPI(
    title="DevDocs Copilot API",
    description="技术文档智能问答助手 - 基于 RAG + Agent 的文档问答系统",
    version="1.0.0",
    lifespan=lifespan,
)

# ========== 2. CORS 跨域中间件 ==========
# 浏览器同源策略会拦截跨端口/跨域的前端调用，这里统一放行
# 注意：allow_origins 为通配符时不能携带凭证，否则违反浏览器规范
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 3. 业务异常处理 ==========
@app.exception_handler(DocumentValidationError)
async def document_validation_error_handler(request: Request, exc: DocumentValidationError):
    """文档规则类错误统一转 400，而不是默认 500"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ========== 4. API 路由注册区 ==========
# ⚠️ 所有业务路由必须在此 include_router，且必须早于下方的静态兜底挂载
app.include_router(documents_router, prefix="/api/documents", tags=["文档管理"])
app.include_router(chat_router, prefix="/api/chat", tags=["智能问答"])
app.include_router(agent_router, prefix="/api/agent", tags=["Agent 问答"])


# ========== 4.1 API 路径兜底（必须早于静态兜底挂载） ==========
# 未被业务路由匹配的 /api/* 统一回 JSON 404；
# 否则 POST 会落到根路径 StaticFiles 上返回 405（它只接受 GET/HEAD）
@app.api_route(
    "/api/{rest:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def api_not_found(rest: str):
    return JSONResponse(
        status_code=404,
        content={"detail": f"接口 /api/{rest} 不存在"},
    )


# ========== 5. 框架级接口 ==========
@app.get("/health", summary="健康检查")
async def health_check():
    """判断服务是否正常运行"""
    return {
        "status": "ok",
        "message": "DevDocs Copilot is running!",
        "version": app.version,
    }


# ========== 6. 静态前端兜底挂载 ==========
# 挂在根路径并放最后：未被 API 路由匹配的 GET 请求交给前端
# html=True：访问目录时自动返回 index.html
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ========== 7. 启动应用 ==========
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,   # 热重载只在 DEBUG 时开启，生产环境不埋雷
    )
