from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_storage_dirs()
    init_db()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="从个人资料库生成可溯源选择题的单用户自托管 API。",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "docs": "/docs", "health": "/health"}

    return application


app = create_app()

