"""文档管理接口：上传 / 列表 / 删除"""
from fastapi import APIRouter, File, UploadFile

from app.errors import DocumentValidationError
from app.schemas import DeleteResponse, DocumentListResponse, UploadResponse
from app.services import document_service
from app.services.document_service import DOCUMENT_SCOPES

router = APIRouter()


@router.post("/upload", response_model=UploadResponse, summary="上传文档")
async def upload_document(file: UploadFile = File(...)):
    """支持 .md / .txt / .pdf / .docx；单个文件不超过 10MB"""
    data = await file.read()
    result = await document_service.ingest_document(file.filename, data)
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
