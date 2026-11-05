"""文档管理接口：上传 / 列表 / 删除"""
from fastapi import APIRouter, File, UploadFile
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from app.errors import DocumentValidationError
from app.schemas import DeleteResponse, DocumentListResponse, UploadResponse
from app.services import document_service, model_registry
from app.services.document_service import DOCUMENT_SCOPES
from app.services.document_validator import MAX_FILE_SIZE

router = APIRouter()

# 上传链路要调用硅基流动做 Embedding/OCR，凭据问题必须说人话，而不是裸 500
_KEY_HINT = (
    "请到页面右上角模型下拉里重新添加「硅基流动」模型并填写有效 Key，"
    "保存后会自动灌入预置语料"
)


@router.post("/upload", response_model=UploadResponse, summary="上传文档")
async def upload_document(file: UploadFile = File(...)):
    """支持 .md / .txt / .pdf / .docx；单个文件不超过 10MB"""
    # size 在 multipart 解析期已逐块统计，先拒超大文件，避免整体读入内存后才拒绝
    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise DocumentValidationError("文件超过 10MB 大小限制")
    if not model_registry.embedding_ready():
        raise DocumentValidationError(
            f"尚未配置向量模型 Key（硅基流动），暂时无法生成文档向量。{_KEY_HINT}"
        )
    data = await file.read()
    try:
        result = await document_service.ingest_document(file.filename, data)
    except (AuthenticationError, PermissionDeniedError) as exc:
        raise DocumentValidationError(
            f"向量模型鉴权失败（Key 无效或已过期）。{_KEY_HINT}"
        ) from exc
    except RateLimitError as exc:
        raise DocumentValidationError(
            "向量模型接口触发限流，请稍等片刻后重试"
        ) from exc
    except APITimeoutError as exc:
        raise DocumentValidationError("向量模型响应超时，请检查网络后重试") from exc
    except APIConnectionError as exc:
        raise DocumentValidationError("无法连接向量模型服务，请检查网络后重试") from exc
    return UploadResponse(**result)


@router.get("", response_model=DocumentListResponse, summary="文档列表")
async def list_documents(scope: str | None = None):
    """文档列表，按服务会话划分视图：
    ?scope=library（语料库：启动时已在库）/ session（我的上传：本次启动后入库）；
    不带参数返回全量。
    """
    if scope is not None and scope not in DOCUMENT_SCOPES:
        raise DocumentValidationError(
            f"非法 scope 取值：{scope}，只接受 library / session"
        )
    documents = await document_service.list_documents(scope=scope)
    return DocumentListResponse(documents=documents, total=len(documents))


@router.delete("/{doc_id}", response_model=DeleteResponse, summary="删除文档")
async def delete_document(doc_id: str):
    await document_service.delete_document(doc_id)
    return DeleteResponse()
