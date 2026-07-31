from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DBSession
from app.models import Blueprint
from app.schemas import BlueprintRead, BlueprintUpdate

router = APIRouter(prefix="/blueprints", tags=["考点蓝图"])


@router.get("", response_model=list[BlueprintRead])
def list_blueprints(
    db: DBSession,
    library_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[Blueprint]:
    statement = select(Blueprint).order_by(Blueprint.updated_at.desc()).limit(limit)
    if library_id:
        statement = statement.where(Blueprint.library_id == library_id)
    return list(db.scalars(statement).all())


@router.get("/{blueprint_id}", response_model=BlueprintRead)
def read_blueprint(blueprint_id: str, db: DBSession) -> Blueprint:
    blueprint = db.get(Blueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="考点蓝图不存在")
    return blueprint


@router.patch("/{blueprint_id}", response_model=BlueprintRead)
def update_blueprint(
    blueprint_id: str, payload: BlueprintUpdate, db: DBSession
) -> Blueprint:
    blueprint = db.get(Blueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="考点蓝图不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(blueprint, key, value)
    blueprint.version += 1
    db.commit()
    db.refresh(blueprint)
    return blueprint

