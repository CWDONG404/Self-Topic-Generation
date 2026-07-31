from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession, get_document, get_library
from app.core.config import settings
from app.core.queue import enqueue_task
from app.models import Chunk, ContentBlock, Document, DocumentVersion, new_id
from app.schemas import (
    ChunkRead,
    ContentBlockRead,
    DocumentRead,
    DocumentUpdate,
    DocumentVersionRead,
    Message,
)

router = APIRouter(tags=["文档"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}
QUEUE_ERROR = "解析任务入队失败，请检查任务队列配置或服务状态后重试"
MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


def _document_read(document: Document) -> DocumentRead:
    latest = max(document.versions, key=lambda item: item.version_number, default=None)
    return DocumentRead(
        id=document.id,
        library_id=document.library_id,
        name=document.name,
        role=document.role,
        allow_as_evidence=document.allow_as_evidence,
        extension=document.extension,
        mime_type=document.mime_type,
        archived=document.archived,
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_version=DocumentVersionRead.model_validate(latest) if latest else None,
    )


def _latest_version(document: Document) -> DocumentVersion:
    if not document.versions:
        raise HTTPException(status_code=404, detail="文档版本不存在")
    return max(document.versions, key=lambda item: item.version_number)


def _safe_storage_path(raw_path: str) -> Path:
    root = settings.storage_dir.resolve()
    path = Path(raw_path).resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=500, detail="文档存储路径无效")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原始文件不存在")
    return path


async def _save_upload(file: UploadFile, target: Path) -> tuple[str, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.uploading")
    digest = hashlib.sha256()
    size = 0
    try:
        async with aiofiles.open(temporary, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件不得超过 {settings.max_upload_mb} MB",
                    )
                digest.update(chunk)
                await output.write(chunk)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return digest.hexdigest(), size


async def _create_document(
    *,
    db: DBSession,
    library_id: str,
    role: str,
    allow_as_evidence: bool | None,
    title: str | None,
    file: UploadFile,
) -> DocumentRead:
    get_library(db, library_id)
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 PDF、DOCX、Markdown 和 TXT 文件",
        )
    if role not in {"outline", "source"}:
        raise HTTPException(status_code=422, detail="文档角色必须是 outline 或 source")

    document_id = new_id()
    version_id = new_id()
    target = settings.storage_dir / "documents" / document_id / version_id / f"original{extension}"
    content_hash, file_size = await _save_upload(file, target)
    mime_type = (
        file.content_type
        or MIME_BY_EXTENSION.get(extension)
        or mimetypes.guess_type(filename)[0]
    )
    mime_type = mime_type or "application/octet-stream"
    evidence_allowed = True if role == "source" else bool(allow_as_evidence)

    document = Document(
        id=document_id,
        library_id=library_id,
        name=(title or filename).strip(),
        role=role,
        allow_as_evidence=evidence_allowed,
        extension=extension,
        mime_type=mime_type,
    )
    version = DocumentVersion(
        id=version_id,
        document=document,
        version_number=1,
        content_hash=content_hash,
        storage_path=str(target.resolve()),
        mime_type=mime_type,
        file_size=file_size,
        status="uploaded",
        metadata_json={"original_filename": filename},
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(document)
    if not enqueue_task("parse_document", version.id):
        version.status = "failed"
        version.progress = 100.0
        version.error = QUEUE_ERROR
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"文档已保存，但{QUEUE_ERROR}",
        )
    return _document_read(document)


@router.get("/documents", response_model=list[DocumentRead])
def list_documents(
    db: DBSession,
    library_id: str | None = Query(None),
    role: str | None = Query(None),
    include_archived: bool = Query(False),
) -> list[DocumentRead]:
    statement = (
        select(Document)
        .options(selectinload(Document.versions))
        .order_by(Document.updated_at.desc())
    )
    if library_id:
        statement = statement.where(Document.library_id == library_id)
    if role:
        statement = statement.where(Document.role == role)
    if not include_archived:
        statement = statement.where(Document.archived.is_(False))
    return [_document_read(document) for document in db.scalars(statement).all()]


@router.post("/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    db: DBSession,
    library_id: str = Form(...),
    role: str = Form("source"),
    allow_as_evidence: bool | None = Form(None),
    title: str | None = Form(None),
    file: UploadFile = File(...),
) -> DocumentRead:
    return await _create_document(
        db=db,
        library_id=library_id,
        role=role,
        allow_as_evidence=allow_as_evidence,
        title=title,
        file=file,
    )


@router.post(
    "/libraries/{library_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_to_library(
    library_id: str,
    db: DBSession,
    role: str = Form("source"),
    allow_as_evidence: bool | None = Form(None),
    title: str | None = Form(None),
    file: UploadFile = File(...),
) -> DocumentRead:
    return await _create_document(
        db=db,
        library_id=library_id,
        role=role,
        allow_as_evidence=allow_as_evidence,
        title=title,
        file=file,
    )


@router.get("/documents/{document_id}", response_model=DocumentRead)
def read_document(document_id: str, db: DBSession) -> DocumentRead:
    statement = (
        select(Document)
        .options(selectinload(Document.versions))
        .where(Document.id == document_id)
    )
    document = db.scalar(statement)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _document_read(document)


@router.patch("/documents/{document_id}", response_model=DocumentRead)
def update_document(document_id: str, payload: DocumentUpdate, db: DBSession) -> DocumentRead:
    document = get_document(db, document_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(document, key, value.strip() if isinstance(value, str) else value)
    if document.role == "source":
        document.allow_as_evidence = True
    elif "role" in payload.model_fields_set and "allow_as_evidence" not in payload.model_fields_set:
        document.allow_as_evidence = False
    db.commit()
    db.refresh(document)
    return _document_read(document)


@router.delete("/documents/{document_id}", response_model=Message)
def archive_document(document_id: str, db: DBSession) -> Message:
    document = get_document(db, document_id)
    document.archived = True
    db.commit()
    return Message(message="文档已归档；历史试卷引用仍然有效")


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionRead])
def list_versions(document_id: str, db: DBSession) -> list[DocumentVersionRead]:
    get_document(db, document_id)
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
    ).all()
    return [DocumentVersionRead.model_validate(item) for item in versions]


@router.post("/documents/{document_id}/parse", response_model=DocumentVersionRead)
def parse_document(document_id: str, db: DBSession) -> DocumentVersionRead:
    document = get_document(db, document_id)
    version = _latest_version(document)
    if version.status == "parsing":
        return DocumentVersionRead.model_validate(version)
    version.status = "queued"
    version.progress = 0.0
    version.error = None
    db.commit()
    if not enqueue_task("parse_document", version.id):
        version.status = "failed"
        version.progress = 100.0
        version.error = QUEUE_ERROR
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR,
        )
    db.refresh(version)
    return DocumentVersionRead.model_validate(version)


@router.get("/documents/{document_id}/file")
def read_document_file(
    document_id: str,
    db: DBSession,
    version_id: str | None = Query(None),
) -> FileResponse:
    document = get_document(db, document_id)
    if version_id:
        version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
        )
        if version is None:
            raise HTTPException(status_code=404, detail="文档版本不存在")
    else:
        version = _latest_version(document)
    path = _safe_storage_path(version.storage_path)
    return FileResponse(
        path,
        media_type=version.mime_type,
        filename=document.name,
        content_disposition_type="inline",
    )


@router.get("/documents/{document_id}/content")
def read_document_content(
    document_id: str,
    db: DBSession,
    version_id: str | None = Query(None),
    block_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    document = get_document(db, document_id)
    version = (
        db.get(DocumentVersion, version_id) if version_id else _latest_version(document)
    )
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="文档版本不存在")
    statement = select(ContentBlock).where(ContentBlock.document_version_id == version.id)
    if block_id:
        statement = statement.where(ContentBlock.id == block_id)
    else:
        statement = statement.offset(offset).limit(limit)
    blocks = db.scalars(statement.order_by(ContentBlock.block_index)).all()
    if block_id and not blocks:
        raise HTTPException(status_code=404, detail="引用段落不存在或不属于该文档版本")
    return {
        "document_id": document.id,
        "document_name": document.name,
        "version_id": version.id,
        "format": document.extension.removeprefix("."),
        "offset": offset,
        "limit": limit,
        "blocks": [
            ContentBlockRead.model_validate(item).model_dump(mode="json") for item in blocks
        ],
    }


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkRead])
def list_chunks(
    document_id: str,
    db: DBSession,
    version_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[ChunkRead]:
    document = get_document(db, document_id)
    version = db.get(DocumentVersion, version_id) if version_id else _latest_version(document)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="文档版本不存在")
    items = db.scalars(
        select(Chunk)
        .where(Chunk.document_version_id == version.id)
        .order_by(Chunk.ordinal)
        .offset(offset)
        .limit(limit)
    ).all()
    return [ChunkRead.model_validate(item) for item in items]
