from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DBSession, get_library
from app.models import Document, Library, Paper
from app.schemas import LibraryCreate, LibraryRead, LibraryUpdate, Message

router = APIRouter(prefix="/libraries", tags=["资料库"])


def _read(db: DBSession, library: Library) -> LibraryRead:
    document_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.library_id == library.id, Document.archived.is_(False)
        )
    ) or 0
    paper_count = db.scalar(select(func.count(Paper.id)).where(Paper.library_id == library.id)) or 0
    return LibraryRead(
        id=library.id,
        name=library.name,
        description=library.description,
        archived=library.archived,
        created_at=library.created_at,
        updated_at=library.updated_at,
        document_count=document_count,
        paper_count=paper_count,
    )


@router.get("", response_model=list[LibraryRead])
def list_libraries(db: DBSession, include_archived: bool = Query(False)) -> list[LibraryRead]:
    statement = select(Library).order_by(Library.updated_at.desc())
    if not include_archived:
        statement = statement.where(Library.archived.is_(False))
    return [_read(db, item) for item in db.scalars(statement).all()]


@router.post("", response_model=LibraryRead, status_code=status.HTTP_201_CREATED)
def create_library(payload: LibraryCreate, db: DBSession) -> LibraryRead:
    library = Library(name=payload.name.strip(), description=payload.description)
    db.add(library)
    db.commit()
    db.refresh(library)
    return _read(db, library)


@router.get("/{library_id}", response_model=LibraryRead)
def read_library(library_id: str, db: DBSession) -> LibraryRead:
    return _read(db, get_library(db, library_id))


@router.patch("/{library_id}", response_model=LibraryRead)
def update_library(library_id: str, payload: LibraryUpdate, db: DBSession) -> LibraryRead:
    library = get_library(db, library_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(library, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(library)
    return _read(db, library)


@router.delete("/{library_id}", response_model=Message)
def archive_library(library_id: str, db: DBSession) -> Message:
    library = get_library(db, library_id)
    library.archived = True
    db.commit()
    return Message(message="资料库已归档")

