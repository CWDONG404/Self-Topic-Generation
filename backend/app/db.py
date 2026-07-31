from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if not url.startswith("sqlite"):
        return {"pool_pre_ping": True, "pool_recycle": 1800}

    if url.endswith(":memory:") or url.endswith(":memory:?cache=shared"):
        return {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }

    if url.startswith("sqlite:///"):
        db_path = url.removeprefix("sqlite:///").split("?", 1)[0]
        if db_path:
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return {"connect_args": {"check_same_thread": False}}


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # 导入模型以注册 metadata。生产环境仍应使用 Alembic；该函数服务于首次启动和测试。
    from app import models  # noqa: F401

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
