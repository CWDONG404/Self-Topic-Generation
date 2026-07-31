from __future__ import annotations

import base64
import time

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import DBSession, get_model_profile
from app.core.security import decrypt_secret, encrypt_secret, redact_text, secret_hint
from app.models import Embedding, ModelProfile
from app.schemas import (
    Message,
    ModelProfileCreate,
    ModelProfileRead,
    ModelProfileUpdate,
    ModelTestResult,
)
from app.services.model_gateway import ChatMessage, create_model_gateway

router = APIRouter(prefix="/model-profiles", tags=["模型配置"])

ROLE_CAPABILITIES = {
    "blueprint": "structured_output",
    "author": "structured_output",
    "reviewer": "structured_output",
    "vision": "vision",
    "embedding": "embedding",
}


def _read(profile: ModelProfile) -> ModelProfileRead:
    return ModelProfileRead(
        id=profile.id,
        name=profile.name,
        provider=profile.provider,
        base_url=profile.base_url,
        model_name=profile.model_name,
        capabilities=profile.capabilities,
        default_roles=list(profile.default_roles or []),
        enabled=profile.enabled,
        is_default=profile.is_default,
        has_api_key=bool(profile.api_key_encrypted),
        api_key_hint=profile.key_hint,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _clear_other_defaults(db: DBSession, keep_id: str | None = None) -> None:
    statement = update(ModelProfile).values(is_default=False)
    if keep_id:
        statement = statement.where(ModelProfile.id != keep_id)
    db.execute(statement)


def _clear_other_role_defaults(
    db: DBSession,
    roles: list[str],
    *,
    keep_id: str | None = None,
) -> None:
    claimed = set(roles)
    if not claimed:
        return
    for profile in db.scalars(select(ModelProfile)).all():
        if profile.id == keep_id:
            continue
        remaining = [role for role in (profile.default_roles or []) if role not in claimed]
        if remaining != (profile.default_roles or []):
            profile.default_roles = remaining


def _validate_default_role_capabilities(
    roles: list[str],
    capabilities: dict[str, bool],
) -> None:
    missing = [
        f"{role}（需要 {ROLE_CAPABILITIES[role]}）"
        for role in roles
        if not capabilities.get(ROLE_CAPABILITIES[role], False)
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="默认模型角色与能力不匹配：" + "、".join(missing),
        )


@router.get("", response_model=list[ModelProfileRead])
def list_model_profiles(db: DBSession) -> list[ModelProfileRead]:
    profiles = db.scalars(select(ModelProfile).order_by(ModelProfile.updated_at.desc())).all()
    return [_read(profile) for profile in profiles]


@router.post("", response_model=ModelProfileRead, status_code=status.HTTP_201_CREATED)
def create_model_profile(payload: ModelProfileCreate, db: DBSession) -> ModelProfileRead:
    if payload.default_roles and not payload.enabled:
        raise HTTPException(status_code=422, detail="停用的模型不能设为默认角色")
    _validate_default_role_capabilities(payload.default_roles, payload.capabilities)
    if payload.is_default:
        _clear_other_defaults(db)
    _clear_other_role_defaults(db, payload.default_roles)
    profile = ModelProfile(
        name=payload.name.strip(),
        provider=payload.provider,
        base_url=payload.base_url.rstrip("/"),
        model_name=payload.model_name.strip(),
        api_key_encrypted=encrypt_secret(payload.api_key),
        key_hint=secret_hint(payload.api_key),
        capabilities=payload.capabilities,
        default_roles=payload.default_roles,
        enabled=payload.enabled,
        is_default=payload.is_default,
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="模型配置名称已存在") from exc
    db.refresh(profile)
    return _read(profile)


@router.get("/{profile_id}", response_model=ModelProfileRead)
def read_model_profile(profile_id: str, db: DBSession) -> ModelProfileRead:
    return _read(get_model_profile(db, profile_id))


@router.patch("/{profile_id}", response_model=ModelProfileRead)
def update_model_profile(
    profile_id: str, payload: ModelProfileUpdate, db: DBSession
) -> ModelProfileRead:
    profile = get_model_profile(db, profile_id)
    values = payload.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
    if "default_roles" in values and values["default_roles"] is None:
        values["default_roles"] = []
    if values.get("enabled") is False:
        values["default_roles"] = []
        values["is_default"] = False
    final_capabilities = values.get("capabilities")
    if final_capabilities is None:
        final_capabilities = profile.capabilities or {}
    final_roles = values.get("default_roles")
    if final_roles is None:
        final_roles = list(profile.default_roles or [])
    _validate_default_role_capabilities(final_roles, final_capabilities)
    embedding_identity_changed = any(
        key in values and values[key] != getattr(profile, key)
        for key in ("provider", "base_url", "model_name")
    )
    if values.get("is_default"):
        _clear_other_defaults(db, profile.id)
    if "default_roles" in values:
        _clear_other_role_defaults(db, values["default_roles"], keep_id=profile.id)
    for key, value in values.items():
        if key == "base_url" and value:
            value = value.rstrip("/")
        setattr(profile, key, value)
    if payload.clear_api_key:
        profile.api_key_encrypted = None
        profile.key_hint = None
    elif "api_key" in payload.model_fields_set and payload.api_key:
        profile.api_key_encrypted = encrypt_secret(payload.api_key)
        profile.key_hint = secret_hint(payload.api_key)
    if embedding_identity_changed:
        db.execute(delete(Embedding).where(Embedding.model_profile_id == profile.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="模型配置名称已存在") from exc
    db.refresh(profile)
    return _read(profile)


@router.delete("/{profile_id}", response_model=Message)
def disable_model_profile(profile_id: str, db: DBSession) -> Message:
    profile = get_model_profile(db, profile_id)
    profile.enabled = False
    profile.is_default = False
    profile.default_roles = []
    db.commit()
    return Message(message="模型配置已停用")


@router.post("/{profile_id}/test", response_model=ModelTestResult)
async def test_model_profile(profile_id: str, db: DBSession) -> ModelTestResult:
    profile = get_model_profile(db, profile_id)
    secret = decrypt_secret(profile.api_key_encrypted)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            if profile.provider == "ollama":
                response = await client.get(f"{profile.base_url.rstrip('/')}/api/tags")
            else:
                headers = {"Authorization": f"Bearer {secret}"} if secret else {}
                response = await client.get(
                    f"{profile.base_url.rstrip('/')}/models", headers=headers
                )
            response.raise_for_status()
        enabled_capabilities = [
            name for name, enabled in (profile.capabilities or {}).items() if enabled
        ]
        gateway = create_model_gateway(
            {
                "provider": profile.provider,
                "base_url": profile.base_url,
                "model_name": profile.model_name,
                "api_key": secret,
                "capabilities": enabled_capabilities,
                "timeout_seconds": 20,
                "max_retries": 0,
            }
        )
        detected = {name: False for name in (profile.capabilities or {})}
        failures: list[str] = []
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        if profile.capabilities.get("structured_output"):
            try:
                result = await gateway.complete_json(
                    [ChatMessage("user", "仅返回 JSON：{\"ok\": true}")],
                    schema=schema,
                    temperature=0,
                )
                detected["structured_output"] = bool(
                    isinstance(result.data, dict) and result.data.get("ok") is True
                )
            except Exception as exc:
                detail = redact_text(str(exc), secret)[:120]
                failures.append(f"结构化输出：{type(exc).__name__}（{detail}）")
        if profile.capabilities.get("embedding"):
            try:
                vectors = await gateway.embed_texts(["模型能力检测"])
                detected["embedding"] = bool(vectors and vectors[0])
            except Exception as exc:
                detail = redact_text(str(exc), secret)[:120]
                failures.append(f"Embedding：{type(exc).__name__}（{detail}）")
        if profile.capabilities.get("vision"):
            try:
                # 32×32 纯色 PNG，只验证图片输入链路，不保存或记录图像内容。
                # 过小或编码不完整的占位 PNG 会被部分视觉端点拒绝解码。
                pixel = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAL0lEQVR4nO3OIQEAAAgDMMLQiS6Uhxg3E/Or3rmkEhAQEBAQEBAQEBAQEBAQSAce5NXQagKAk8gAAAAASUVORK5CYII="
                )
                result = await gateway.complete_vision_json(
                    prompt="确认可以读取图片，并仅返回 JSON：{\"ok\": true}",
                    image_bytes=pixel,
                    media_type="image/png",
                    schema=schema,
                )
                detected["vision"] = bool(
                    isinstance(result.data, dict) and result.data.get("ok") is True
                )
            except Exception as exc:
                detail = redact_text(str(exc), secret)[:120]
                failures.append(f"视觉输入：{type(exc).__name__}（{detail}）")
        required_checks = [name for name in enabled_capabilities if name in detected]
        all_detected = all(detected.get(name, False) for name in required_checks)
        latency = round((time.monotonic() - started) * 1000)
        return ModelTestResult(
            ok=all_detected,
            latency_ms=latency,
            message="连接及能力检测成功" if all_detected else f"连接成功；{'; '.join(failures)}",
            capabilities=detected,
        )
    except Exception as exc:
        latency = round((time.monotonic() - started) * 1000)
        safe_error = redact_text(str(exc), secret)
        # 避免错误正文过长或包含上游返回的其他敏感字段。
        safe_error = safe_error[:300]
        return ModelTestResult(
            ok=False,
            latency_ms=latency,
            message=f"连接失败：{safe_error}",
            capabilities=profile.capabilities,
        )
