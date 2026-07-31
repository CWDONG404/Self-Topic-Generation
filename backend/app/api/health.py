from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DBSession

router = APIRouter(tags=["健康检查"])


@router.get("/health")
def health(db: DBSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}

