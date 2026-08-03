"""文档解析与出题的 Celery 任务入口。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.worker import celery_app

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _paper_timestamp(created_at: datetime, timezone_name: str) -> str:
    aware_created_at = (
        created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    )
    return aware_created_at.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M")


def _regenerated_question_metadata(
    original_id: str,
    original_metadata: Mapping[str, Any] | None,
    revised_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        **dict(original_metadata or {}),
        **dict(revised_metadata or {}),
        "regenerated_from": original_id,
    }


def _safe_source_path(raw_path: str) -> Path:
    from app.core.config import settings

    root = settings.storage_dir.resolve()
    source = Path(raw_path).resolve()
    if source != root and root not in source.parents:
        raise ValueError("文档存储路径超出 STORAGE_DIR")
    if not source.is_file():
        raise FileNotFoundError("上传的原始文档不存在")
    return source


def _rect_list(rect: Any) -> list[float]:
    return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]


def _citation_search_text(raw_question: Mapping[str, Any]) -> tuple[str, str, str]:
    correct_label = str(raw_question.get("correct_option") or "").upper()
    correct_text = ""
    raw_options = raw_question.get("options") or []
    for position, option in enumerate(raw_options):
        fallback_label = "ABCD"[position] if position < 4 else ""
        if isinstance(option, Mapping):
            label = str(option.get("label") or fallback_label).upper()
            text = str(option.get("text") or "")
        else:
            label = fallback_label
            text = str(option)
        if label == correct_label:
            correct_text = text
            break
    knowledge_point = str(raw_question.get("knowledge_point") or "")
    context = "\n".join(
        [
            str(raw_question.get("stem") or ""),
            correct_text,
            knowledge_point,
            str(raw_question.get("explanation") or ""),
        ]
    )
    return context, correct_text, knowledge_point


def _normalized_citation_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _citation_ngrams(value: str, size: int = 2) -> set[str]:
    normalized = _normalized_citation_text(value)
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _select_citation_anchor(
    chunk: Any, raw_question: Mapping[str, Any]
) -> Mapping[str, Any]:
    """从 chunk 的多个块级锚点中选出最直接支持答案的段落。"""

    anchors = [
        anchor
        for anchor in (chunk.bbox_data or [])
        if isinstance(anchor, Mapping) and str(anchor.get("quote") or "").strip()
    ]
    if not anchors:
        return {}
    context, correct_text, knowledge_point = _citation_search_text(raw_question)
    context_ngrams = _citation_ngrams(context)
    normalized_correct = _normalized_citation_text(correct_text)
    normalized_knowledge = _normalized_citation_text(knowledge_point)

    def score(anchor: Mapping[str, Any]) -> tuple[int, int]:
        quote = str(anchor.get("quote") or "")
        normalized_quote = _normalized_citation_text(quote)
        overlap = len(_citation_ngrams(quote) & context_ngrams)
        direct_answer = int(
            bool(normalized_correct) and normalized_correct in normalized_quote
        )
        knowledge_match = int(
            bool(normalized_knowledge) and normalized_knowledge in normalized_quote
        )
        return (
            direct_answer * 10_000 + knowledge_match * 500 + overlap,
            len(normalized_quote),
        )

    return max(anchors, key=score)


@celery_app.task(bind=True, name="app.tasks.parse_document")
def parse_document(self: Any, document_version_id: str) -> dict[str, Any]:
    """解析一个不可变文档版本并持久化块、chunk、页面与图片。"""

    from sqlalchemy import delete, func, select

    from app.core.config import settings
    from app.db import SessionLocal
    from app.models import (
        Chunk,
        Citation,
        ContentBlock,
        DocumentVersion,
        ImageAsset,
        Page,
    )
    from app.services.document_parser import ParserLimits, UnifiedDocumentParser

    with SessionLocal() as db:
        version = db.get(DocumentVersion, str(document_version_id))
        if version is None:
            raise LookupError(f"文档版本不存在：{document_version_id}")
        source = _safe_source_path(version.storage_path)
        version.status = "parsing"
        version.progress = max(version.progress, 2.0)
        version.error = None
        db.commit()

    try:
        asset_dir = source.parent / "assets"

        def report_parse_progress(current: int, total: int, stage: str) -> None:
            progress = 5.0 + 65.0 * min(1.0, current / max(1, total))
            with SessionLocal() as progress_db:
                current_version = progress_db.get(
                    DocumentVersion, str(document_version_id)
                )
                if current_version is None or current_version.status != "parsing":
                    return
                if progress < 70 and progress - current_version.progress < 0.5:
                    return
                current_version.progress = max(current_version.progress, progress)
                current_version.metadata_json = {
                    **(current_version.metadata_json or {}),
                    "parse_progress": {
                        "stage": stage,
                        "current": current,
                        "total": total,
                    },
                }
                progress_db.commit()

        parser = UnifiedDocumentParser(
            limits=ParserLimits(
                max_file_bytes=settings.max_upload_bytes,
                max_pages=settings.max_document_pages,
            ),
            asset_dir=asset_dir,
            progress_callback=report_parse_progress,
        )
        parsed = parser.parse(
            source,
            document_id=version.document_id,
            document_version_id=version.id,
        )

        with SessionLocal() as progress_db:
            current_version = progress_db.get(DocumentVersion, str(document_version_id))
            if current_version is not None:
                current_version.progress = max(current_version.progress, 75.0)
                current_version.metadata_json = {
                    **(current_version.metadata_json or {}),
                    "parse_progress": {"stage": "persisting", "current": 1, "total": 1},
                }
                progress_db.commit()

        with SessionLocal() as db:
            version = db.get(DocumentVersion, str(document_version_id))
            if version is None:
                raise LookupError(f"文档版本不存在：{document_version_id}")

            # 历史题已经引用该不可变版本时绝不重写定位数据。
            citation_count = (
                db.scalar(
                    select(func.count(Citation.id)).where(
                        Citation.document_version_id == version.id
                    )
                )
                or 0
            )
            existing_chunks = (
                db.scalar(
                    select(func.count(Chunk.id)).where(Chunk.document_version_id == version.id)
                )
                or 0
            )
            if citation_count and existing_chunks:
                version.status = "ready"
                version.progress = 100.0
                version.error = None
                version.metadata_json = {
                    **(version.metadata_json or {}),
                    "reparse_skipped": "该版本已有历史题引用，为保持出处坐标不变未覆盖解析产物",
                }
                db.commit()
                return {
                    "document_version_id": version.id,
                    "status": "ready",
                    "chunks": existing_chunks,
                    "reparse_skipped": True,
                }

            # 无历史引用时可安全地幂等重建。
            db.execute(delete(ImageAsset).where(ImageAsset.document_version_id == version.id))
            db.execute(delete(Chunk).where(Chunk.document_version_id == version.id))
            db.execute(delete(ContentBlock).where(ContentBlock.document_version_id == version.id))
            db.execute(delete(Page).where(Page.document_version_id == version.id))
            db.flush()

            page_rows: dict[int, Page] = {}
            pages_metadata = (
                parsed.metadata.get("pages", []) if isinstance(parsed.metadata, Mapping) else []
            )
            metadata_by_number = {
                int(item["page_number"]): item
                for item in pages_metadata
                if isinstance(item, Mapping) and item.get("page_number") is not None
            }
            page_numbers = sorted(
                {
                    block.anchor.page_number
                    for block in parsed.blocks
                    if block.anchor.page_number is not None
                }
                | set(metadata_by_number)
            )
            for page_number in page_numbers:
                page_blocks = [
                    block for block in parsed.blocks if block.anchor.page_number == page_number
                ]
                page_meta = metadata_by_number.get(page_number, {})
                row = Page(
                    document_version_id=version.id,
                    page_number=page_number,
                    width=page_meta.get("width")
                    or next(
                        (item.anchor.page_width for item in page_blocks if item.anchor.page_width),
                        None,
                    ),
                    height=page_meta.get("height")
                    or next(
                        (
                            item.anchor.page_height
                            for item in page_blocks
                            if item.anchor.page_height
                        ),
                        None,
                    ),
                    text="\n\n".join(item.text for item in page_blocks),
                    bbox_data=[
                        {
                            "block_id": item.block_id,
                            "rects": [_rect_list(rect) for rect in item.anchor.rects],
                        }
                        for item in page_blocks
                    ],
                    ocr_confidence=None,
                )
                db.add(row)
                db.flush()
                page_rows[page_number] = row

            blocks_by_source_id: dict[str, ContentBlock] = {}
            for block_index, block in enumerate(parsed.blocks):
                page_row = page_rows.get(block.anchor.page_number or -1)
                rects = [_rect_list(rect) for rect in block.anchor.rects]
                heading_level = len(block.section_path) if block.kind == "heading" else None
                row = ContentBlock(
                    id=block.block_id,
                    document_version_id=version.id,
                    page_id=page_row.id if page_row else None,
                    block_index=block_index,
                    block_type=block.kind,
                    heading_level=heading_level,
                    text=block.text,
                    bbox=rects[0] if rects else None,
                    char_start=block.anchor.char_start,
                    char_end=block.anchor.char_end,
                    metadata_json={
                        **dict(block.metadata),
                        "section_path": list(block.section_path),
                        "rects": rects,
                        "source_block_id": block.block_id,
                    },
                )
                db.add(row)
                blocks_by_source_id[block.block_id] = row
            db.flush()

            for ordinal, chunk in enumerate(parsed.chunks):
                page_values = [
                    anchor.page_number for anchor in chunk.anchors if anchor.page_number is not None
                ]
                bbox_data = [
                    {
                        "document_id": anchor.document_id,
                        "document_version_id": anchor.document_version_id,
                        "block_id": anchor.block_id,
                        "page_number": anchor.page_number,
                        "page_width": anchor.page_width,
                        "page_height": anchor.page_height,
                        "rects": [_rect_list(rect) for rect in anchor.rects],
                        "char_start": anchor.char_start,
                        "char_end": anchor.char_end,
                        "quote": anchor.quote,
                        "quote_hash": anchor.quote_hash,
                        "coordinate_system": anchor.coordinate_system,
                    }
                    for anchor in chunk.anchors
                ]
                first_block_id = chunk.block_ids[0] if chunk.block_ids else None
                db.add(
                    Chunk(
                        id=chunk.chunk_id,
                        document_version_id=version.id,
                        block_id=first_block_id if first_block_id in blocks_by_source_id else None,
                        ordinal=ordinal,
                        page_start=min(page_values) if page_values else None,
                        page_end=max(page_values) if page_values else None,
                        text=chunk.text,
                        text_hash=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                        bbox_data=bbox_data,
                        metadata_json={
                            **dict(chunk.metadata),
                            "section_path": list(chunk.section_path),
                            "block_ids": list(chunk.block_ids),
                            "token_estimate": chunk.token_estimate,
                        },
                    )
                )

            for asset in parsed.assets:
                if not asset.storage_path:
                    continue
                db.add(
                    ImageAsset(
                        id=asset.asset_id,
                        document_version_id=version.id,
                        page_number=asset.page_number,
                        storage_path=asset.storage_path,
                        content_hash=asset.content_hash,
                        bbox=_rect_list(asset.rect) if asset.rect else None,
                        metadata_json=dict(asset.metadata),
                    )
                )

            page_count = (
                parsed.metadata.get("page_count") if isinstance(parsed.metadata, Mapping) else None
            )
            version.page_count = (
                int(page_count) if page_count is not None else (len(page_rows) or None)
            )
            version.status = "ready"
            version.progress = 100.0
            version.error = None
            version.metadata_json = {
                **(version.metadata_json or {}),
                "parser_backend": parsed.parser_backend,
                "parser_warnings": list(parsed.warnings),
                "block_count": len(parsed.blocks),
                "chunk_count": len(parsed.chunks),
                "asset_count": len(parsed.assets),
                "parse_progress": {
                    "stage": "completed",
                    "current": len(page_rows),
                    "total": len(page_rows),
                },
            }
            db.commit()
            return {
                "document_version_id": version.id,
                "status": "ready",
                "pages": len(page_rows),
                "blocks": len(parsed.blocks),
                "chunks": len(parsed.chunks),
                "assets": len(parsed.assets),
                "warnings": list(parsed.warnings),
            }
    except Exception as exc:
        logger.exception("文档解析失败：%s", document_version_id)
        with SessionLocal() as db:
            version = db.get(DocumentVersion, str(document_version_id))
            if version is not None:
                version.status = "failed"
                version.progress = 100.0
                version.error = f"{type(exc).__name__}: {str(exc)[:1000]}"
                db.commit()
        raise


def _latest_ready_version(document: Any) -> Any | None:
    candidates = [item for item in document.versions if item.status == "ready"]
    return max(candidates, key=lambda item: item.version_number, default=None)


def _load_generation_materials(
    db: Any,
    job: Any,
    selected_chunk_ids: Mapping[str, list[str]] | None = None,
) -> tuple[dict[str, list[Any]], list[str]]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import Document, DocumentVersion
    from app.workflows.generation import Evidence

    request = job.request_json or {}
    allocations = request.get("source_documents") or []
    source_ids = [str(item.get("document_id")) for item in allocations if item.get("document_id")]
    outline_ids = [str(item) for item in (request.get("outline_document_ids") or [])]
    requested_ids = set(source_ids) | set(outline_ids)
    documents = {
        item.id: item
        for item in db.scalars(
            select(Document)
            .options(selectinload(Document.versions).selectinload(DocumentVersion.chunks))
            .where(Document.id.in_(requested_ids))
        )
        .unique()
        .all()
    }
    evidence_by_document: dict[str, list[Evidence]] = {}
    for document_id in source_ids:
        document = documents.get(document_id)
        if document is None or not document.allow_as_evidence:
            evidence_by_document[document_id] = []
            continue
        version = _latest_ready_version(document)
        if version is None:
            evidence_by_document[document_id] = []
            continue
        chunks = list(version.chunks)
        if selected_chunk_ids and document_id in selected_chunk_ids:
            positions = {
                chunk_id: index
                for index, chunk_id in enumerate(selected_chunk_ids[document_id])
            }
            chunks = [item for item in chunks if item.id in positions]
            chunks.sort(key=lambda item: positions[item.id])
        evidence_by_document[document_id] = [
            Evidence(
                evidence_id=chunk.id,
                document_id=document_id,
                text=chunk.text,
                chunk_id=chunk.id,
                document_version_id=version.id,
                section_path=tuple((chunk.metadata_json or {}).get("section_path") or ()),
                anchor={"anchors": chunk.bbox_data},
                metadata={"ordinal": chunk.ordinal},
            )
            for chunk in chunks
        ]
    focus_materials: list[str] = []
    for document_id in outline_ids:
        document = documents.get(document_id)
        version = _latest_ready_version(document) if document else None
        if version:
            joined = "\n\n".join(chunk.text for chunk in version.chunks)
            focus_materials.append(f"# {document.name}\n{joined[:100_000]}")
    return evidence_by_document, focus_materials


async def _enrich_visual_chunks(
    db: Any,
    document_ids: list[str],
    gateway: Any,
    profile_id: str,
    *,
    job_id: str | None = None,
) -> list[str]:
    """按需理解图片并把可出题事实写成带坐标的正式 chunk。"""

    from sqlalchemy import func, select

    from app.core.config import settings
    from app.core.job_events import append_job_event
    from app.models import (
        Chunk,
        ContentBlock,
        DocumentVersion,
        GenerationJob,
        ImageAsset,
        Page,
    )
    from app.services.content_enrichment import describe_image

    if not document_ids:
        return []
    model_name = gateway.profile.model_name
    cache_key = f"{profile_id}:{model_name}"
    all_assets = db.scalars(
        select(ImageAsset)
        .join(DocumentVersion, DocumentVersion.id == ImageAsset.document_version_id)
        .where(DocumentVersion.document_id.in_(document_ids))
        .order_by(ImageAsset.document_version_id, ImageAsset.page_number, ImageAsset.id)
    ).all()
    cached_assets = []
    uncached_assets = []
    for asset in all_assets:
        cached = (asset.metadata_json or {}).get("visual_analyses") or {}
        analysis = cached.get(cache_key) if isinstance(cached, Mapping) else None
        if not isinstance(analysis, Mapping) and asset.analysis_model == model_name:
            # 兼容升级前按 profile_id 存储的缓存，但仅在模型名仍一致时复用。
            analysis = cached.get(profile_id) if isinstance(cached, Mapping) else None
        if isinstance(analysis, Mapping):
            cached_assets.append(asset)
        else:
            uncached_assets.append(asset)

    max_new_assets = settings.visual_enrichment_max_new_assets_per_job
    if max_new_assets <= 0 or not uncached_assets:
        selected_uncached: list[Any] = []
    elif len(uncached_assets) <= max_new_assets:
        selected_uncached = list(uncached_assets)
    elif max_new_assets == 1:
        selected_uncached = [uncached_assets[len(uncached_assets) // 2]]
    else:
        last_index = len(uncached_assets) - 1
        selected_uncached = [
            uncached_assets[round(position * last_index / (max_new_assets - 1))]
            for position in range(max_new_assets)
        ]
    assets = [*cached_assets, *selected_uncached]
    warnings: list[str] = []
    next_ordinals: dict[str, int] = {}
    next_blocks: dict[str, int] = {}
    if job_id:
        append_job_event(
            db,
            job_id,
            stage="validating",
            progress=1,
            message=(
                f"正在准备视觉材料：复用 {len(cached_assets)} 张缓存，"
                f"本次最多分析 {len(selected_uncached)} 张新图片"
            ),
            payload={
                "visual_assets_total": len(all_assets),
                "visual_assets_cached": len(cached_assets),
                "visual_assets_selected": len(selected_uncached),
            },
        )
    for index, asset in enumerate(assets, start=1):
        if job_id:
            current_job = db.get(GenerationJob, job_id)
            if current_job is not None:
                db.refresh(current_job)
                if current_job.cancel_requested:
                    warnings.append("视觉材料预处理已按取消请求安全停止")
                    break
        try:
            cached = (asset.metadata_json or {}).get("visual_analyses") or {}
            analysis = cached.get(cache_key) if isinstance(cached, Mapping) else None
            if not isinstance(analysis, Mapping) and asset.analysis_model == model_name:
                analysis = cached.get(profile_id) if isinstance(cached, Mapping) else None
            if not isinstance(analysis, Mapping):
                source = _safe_source_path(asset.storage_path)
                analysis = await describe_image(
                    gateway,
                    source,
                    media_type=mimetypes.guess_type(source.name)[0],
                    seed=int(asset.content_hash[:8], 16),
                )
                cached = dict(cached) if isinstance(cached, Mapping) else {}
                cached[cache_key] = dict(analysis)
                asset.metadata_json = {**(asset.metadata_json or {}), "visual_analyses": cached}
            description = str(analysis.get("description") or "").strip()
            facts = [
                str(item).strip()
                for item in analysis.get("key_facts") or []
                if str(item).strip()
            ]
            asset.analysis_text = "\n".join([description, *facts]).strip() or None
            asset.analysis_model = model_name
            if not analysis.get("question_worthy") or not asset.analysis_text:
                continue
            version = db.get(DocumentVersion, asset.document_version_id)
            if version is None:
                continue
            page = db.scalar(
                select(Page).where(
                    Page.document_version_id == version.id,
                    Page.page_number == asset.page_number,
                )
            )
            if version.id not in next_ordinals:
                max_ordinal = db.scalar(
                    select(func.max(Chunk.ordinal)).where(
                        Chunk.document_version_id == version.id
                    )
                )
                max_block = db.scalar(
                    select(func.max(ContentBlock.block_index)).where(
                        ContentBlock.document_version_id == version.id
                    )
                )
                next_ordinals[version.id] = int(
                    max_ordinal if max_ordinal is not None else -1
                ) + 1
                next_blocks[version.id] = int(
                    max_block if max_block is not None else -1
                ) + 1
            block_id = "vb_" + hashlib.sha256(asset.id.encode()).hexdigest()[:32]
            block = db.get(ContentBlock, block_id)
            if block is None:
                block = ContentBlock(
                    id=block_id,
                    document_version_id=version.id,
                    page_id=page.id if page else None,
                    block_index=next_blocks[version.id],
                    block_type="image_analysis",
                    text=asset.analysis_text,
                    bbox=asset.bbox,
                    metadata_json={
                        "asset_id": asset.id,
                        "vision_profile_id": profile_id,
                        "vision_model": model_name,
                    },
                )
                next_blocks[version.id] += 1
                db.add(block)
                # Chunk 通过 block_id 直接引用新块；显式 flush 保证 PostgreSQL
                # 在同一轮视觉进度事件提交前先插入父记录。
                db.flush()
            else:
                block.text = asset.analysis_text
                block.metadata_json = {
                    **(block.metadata_json or {}),
                    "vision_profile_id": profile_id,
                    "vision_model": model_name,
                }
            chunk_id = "v_" + hashlib.sha256(asset.id.encode()).hexdigest()[:32]
            chunk = db.get(Chunk, chunk_id)
            anchor = {
                "document_version_id": version.id,
                "block_id": block_id,
                "page_number": asset.page_number,
                "page_width": page.width if page else None,
                "page_height": page.height if page else None,
                "rects": [asset.bbox] if asset.bbox else [],
                "quote": asset.analysis_text,
                "quote_hash": hashlib.sha256(asset.analysis_text.encode()).hexdigest(),
                "coordinate_system": "top-left",
            }
            if chunk is None:
                chunk = Chunk(
                    id=chunk_id,
                    document_version_id=version.id,
                    block_id=block_id,
                    ordinal=next_ordinals[version.id],
                    page_start=asset.page_number,
                    page_end=asset.page_number,
                    text=asset.analysis_text,
                    text_hash=hashlib.sha256(asset.analysis_text.encode()).hexdigest(),
                    bbox_data=[anchor],
                    metadata_json={
                        "kind": "visual_analysis",
                        "asset_id": asset.id,
                        "vision_profile_id": profile_id,
                        "vision_model": model_name,
                    },
                )
                next_ordinals[version.id] += 1
                db.add(chunk)
            else:
                if chunk.text != asset.analysis_text:
                    chunk.embeddings.clear()
                chunk.text = asset.analysis_text
                chunk.text_hash = hashlib.sha256(asset.analysis_text.encode()).hexdigest()
                chunk.bbox_data = [anchor]
                chunk.metadata_json = {
                    **(chunk.metadata_json or {}),
                    "vision_profile_id": profile_id,
                    "vision_model": model_name,
                }
        except Exception as exc:
            warnings.append(f"图片 {asset.id[:8]} 视觉分析失败：{type(exc).__name__}")
            logger.warning("视觉分析失败：%s（%s）", asset.id, type(exc).__name__)
        finally:
            if job_id and assets:
                append_job_event(
                    db,
                    job_id,
                    stage="validating",
                    progress=1 + (3 * index / len(assets)),
                    message=f"视觉材料处理中（{index}/{len(assets)}）",
                    payload={
                        "visual_assets_processed": index,
                        "visual_assets_selected": len(assets),
                    },
                )
    db.commit()
    return warnings


async def _select_relevant_chunk_ids(
    db: Any,
    evidence_by_document: Mapping[str, list[Any]],
    focus_materials: list[str],
    gateway: Any,
    profile_id: str,
    *,
    target_count: int,
) -> dict[str, list[str]]:
    """建立/复用向量索引，并按重点资料为每份正文选择相关且有上限的证据。"""

    from sqlalchemy import delete, select

    from app.models import Embedding
    from app.services.content_enrichment import embed_batches, ranked_indices

    all_evidence = [item for values in evidence_by_document.values() for item in values]
    if not all_evidence:
        return {}
    ids = [item.evidence_id for item in all_evidence]
    existing = {
        item.chunk_id: item
        for item in db.scalars(
            select(Embedding).where(
                Embedding.chunk_id.in_(ids),
                Embedding.model_profile_id == profile_id,
            )
        ).all()
    }
    query_text = "\n\n".join(focus_materials).strip()
    query_vector = (
        (await embed_batches(gateway, [query_text[:20_000]]))[0] if query_text else None
    )
    expected_dimensions = len(query_vector) if query_vector else None
    stale_ids = {
        chunk_id
        for chunk_id, item in existing.items()
        if item.model_name != gateway.profile.model_name
        or (expected_dimensions is not None and item.dimensions != expected_dimensions)
    }
    if stale_ids:
        db.execute(
            delete(Embedding).where(
                Embedding.model_profile_id == profile_id,
                Embedding.chunk_id.in_(stale_ids),
            )
        )
        db.commit()
        for chunk_id in stale_ids:
            existing.pop(chunk_id, None)
    missing = [item for item in all_evidence if item.evidence_id not in existing]
    if missing:
        vectors = await embed_batches(gateway, [item.text[:8000] for item in missing])
        for evidence, vector in zip(missing, vectors, strict=True):
            row = Embedding(
                chunk_id=evidence.evidence_id,
                model_profile_id=profile_id,
                model_name=gateway.profile.model_name,
                dimensions=len(vector),
                vector=vector,
            )
            db.add(row)
            existing[evidence.evidence_id] = row
        db.commit()

    selected: dict[str, list[str]] = {}
    per_document_limit = max(80, min(200, target_count * 2))
    for document_id, values in evidence_by_document.items():
        if len(values) <= per_document_limit:
            selected[document_id] = [item.evidence_id for item in values]
            continue
        if query_vector is None:
            selected[document_id] = [item.evidence_id for item in values[:per_document_limit]]
            continue
        vectors = [existing[item.evidence_id].vector for item in values]
        indices = ranked_indices(query_vector, vectors, limit=per_document_limit)
        selected[document_id] = [values[index].evidence_id for index in indices]
    return selected


def _profile_gateway(db: Any, profile_id: str | None, *, local_mode: bool) -> Any:
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.security import decrypt_secret
    from app.models import ModelProfile
    from app.services.model_gateway import create_model_gateway

    profile = (
        db.get(ModelProfile, str(profile_id))
        if profile_id
        else db.scalar(
            select(ModelProfile)
            .where(ModelProfile.enabled.is_(True), ModelProfile.is_default.is_(True))
            .order_by(ModelProfile.created_at)
        )
    )
    if profile is None:
        profile = db.scalar(
            select(ModelProfile)
            .where(ModelProfile.enabled.is_(True))
            .order_by(ModelProfile.created_at)
        )
    if profile is None:
        raise RuntimeError("尚未配置可用模型，请先在设置中添加模型")
    capabilities = [name for name, enabled in (profile.capabilities or {}).items() if enabled]
    return create_model_gateway(
        {
            "provider": profile.provider,
            "base_url": profile.base_url,
            "model_name": profile.model_name,
            "api_key": decrypt_secret(profile.api_key_encrypted),
            "capabilities": capabilities or ["chat", "structured_output"],
            "timeout_seconds": settings.model_request_timeout_seconds,
            "max_retries": settings.model_request_max_retries,
            "local": None,
        },
        local_mode=local_mode,
    ), profile.id


def _role_profile_id(assignments: Mapping[str, str], role: str) -> str | None:
    aliases = {
        "blueprint": ("blueprint", "outline", "planner"),
        "author": ("author", "generator", "question", "question_author"),
        "reviewer": ("reviewer", "review", "validator", "question_reviewer"),
        "vision": ("vision", "visual", "multimodal"),
        "embedding": ("embedding", "embeddings", "retrieval"),
    }
    return next((assignments[name] for name in aliases[role] if assignments.get(name)), None)


def _load_historical_fingerprints(
    db: Any,
    library_id: str,
    *,
    exclude_question_ids: set[str] | None = None,
) -> list[Any]:
    from sqlalchemy import select

    from app.models import Citation, Question
    from app.services.deduplication import QuestionFingerprint

    excluded = exclude_question_ids or set()
    historical_questions = [
        item
        for item in db.scalars(
            select(Question).where(Question.library_id == library_id)
        ).all()
        if item.id not in excluded
    ]
    evidence_by_question: dict[str, set[str]] = {
        item.id: set() for item in historical_questions
    }
    if evidence_by_question:
        for question_id, chunk_id in db.execute(
            select(Citation.question_id, Citation.chunk_id).where(
                Citation.question_id.in_(evidence_by_question)
            )
        ):
            evidence_by_question[str(question_id)].add(str(chunk_id))
    return [
        QuestionFingerprint(
            item.id,
            item.stem,
            item.knowledge_point,
            frozenset(evidence_by_question.get(item.id, set())),
            str((item.generation_metadata or {}).get("angle") or ""),
        )
        for item in historical_questions
    ]


async def _execute_generation(job_id: str) -> Mapping[str, Any]:
    from sqlalchemy import func, select

    from app.core.config import settings
    from app.core.job_events import append_job_event
    from app.db import SessionLocal
    from app.models import GenerationJob
    from app.workflows.generation import GenerationRequest, GenerationSupervisor
    from app.workflows.langgraph_workflow import LangGraphUnavailable, run_generation_graph

    with SessionLocal() as db:
        job = db.get(GenerationJob, str(job_id))
        if job is None:
            raise LookupError(f"任务不存在：{job_id}")
        if job.cancel_requested or job.status == "canceled":
            return {"status": "canceled", "questions": []}
        request_json = dict(job.request_json or {})
        allocations = request_json.get("source_documents") or []
        request_json["document_percentages"] = {
            str(item["document_id"]): item["percentage"] for item in allocations
        }
        request_json["total_questions"] = job.target_count
        request_json["random_seed"] = job.random_seed
        assignments = dict(request_json.get("model_assignments") or {})
        local_mode = request_json.get("execution_mode") == "local"
        source_document_ids = [str(item["document_id"]) for item in allocations]
        preflight_warnings: list[str] = []
        vision_profile_id = _role_profile_id(assignments, "vision")
        if vision_profile_id:
            vision_gateway, resolved_vision_profile_id = _profile_gateway(
                db, vision_profile_id, local_mode=local_mode
            )
            preflight_warnings.extend(
                await _enrich_visual_chunks(
                    db,
                    source_document_ids,
                    vision_gateway,
                    resolved_vision_profile_id,
                    job_id=str(job_id),
                )
            )
            db.refresh(job)
            if job.cancel_requested:
                from app.core.job_events import append_job_event

                append_job_event(
                    db,
                    str(job_id),
                    stage="canceled",
                    progress=100,
                    message="任务已在视觉材料预处理后安全取消",
                    status="canceled",
                )
                return {
                    "status": "canceled",
                    "questions": [],
                    "warnings": preflight_warnings,
                }
        else:
            from app.models import DocumentVersion, ImageAsset

            image_count = db.scalar(
                select(func.count(ImageAsset.id))
                .join(DocumentVersion, DocumentVersion.id == ImageAsset.document_version_id)
                .where(DocumentVersion.document_id.in_(source_document_ids))
            )
            if image_count:
                preflight_warnings.append(
                    f"检测到 {image_count} 个图片资源，但未配置视觉模型；图片内容未参与出题"
                )

        evidence_by_document, focus_materials = _load_generation_materials(db, job)
        embedding_profile_id = _role_profile_id(assignments, "embedding")
        resolved_embedding_profile_id: str | None = None
        embedding_gateway = None
        if embedding_profile_id:
            embedding_gateway, resolved_embedding_profile_id = _profile_gateway(
                db, embedding_profile_id, local_mode=local_mode
            )
            selected = await _select_relevant_chunk_ids(
                db,
                evidence_by_document,
                focus_materials,
                embedding_gateway,
                resolved_embedding_profile_id,
                target_count=job.target_count,
            )
            evidence_by_document, focus_materials = _load_generation_materials(
                db, job, selected
            )
        else:
            preflight_warnings.append(
                "未配置 Embedding 模型；本次使用章节顺序与随机采样准备证据"
            )
        request_json["focus_materials"] = focus_materials
        blueprint_gateway, blueprint_profile_id = _profile_gateway(
            db, _role_profile_id(assignments, "blueprint"), local_mode=local_mode
        )
        author_gateway, author_profile_id = _profile_gateway(
            db, _role_profile_id(assignments, "author"), local_mode=local_mode
        )
        reviewer_gateway, reviewer_profile_id = _profile_gateway(
            db, _role_profile_id(assignments, "reviewer"), local_mode=local_mode
        )
        historical = _load_historical_fingerprints(db, job.library_id)

    async def progress_hook(event: Any) -> None:
        payload = {
            **dict(event.payload),
            "accepted": event.accepted,
            "target": event.target,
            "generated": event.generated,
            "rejected": event.rejected,
            "revised": event.revised,
            "current_document": event.current_document,
            "current_topic": event.current_topic,
            "warning": event.warning,
            "error": event.error,
        }
        with SessionLocal() as progress_db:
            current = progress_db.get(GenerationJob, str(job_id))
            if current is None:
                return
            current.accepted_count = max(current.accepted_count, event.accepted)
            current.rejected_count = max(current.rejected_count, event.rejected)
            current.revision_count = max(current.revision_count, event.revised)
            append_job_event(
                progress_db,
                str(job_id),
                stage=event.stage.value,
                progress=event.progress,
                message=event.message,
                payload={key: value for key, value in payload.items() if value is not None},
            )

    async def cancel_check() -> bool:
        with SessionLocal() as cancel_db:
            current = cancel_db.get(GenerationJob, str(job_id))
            return current is None or current.cancel_requested

    supervisor = GenerationSupervisor.from_gateways(
        blueprint=blueprint_gateway,
        author=author_gateway,
        reviewer=reviewer_gateway,
        embedding=embedding_gateway,
    )
    spec = GenerationRequest.from_value(request_json)
    async def invoke_graph() -> Mapping[str, Any]:
        if settings.database_url.startswith("postgresql"):
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            except ImportError:
                logger.warning("未安装 Postgres checkpointer，当前任务使用数据库事件恢复")
            else:
                checkpoint_url = settings.database_url.replace(
                    "postgresql+psycopg://", "postgresql://", 1
                )
                async with AsyncPostgresSaver.from_conn_string(checkpoint_url) as checkpointer:
                    await checkpointer.setup()
                    return await run_generation_graph(
                        supervisor,
                        spec,
                        evidence_by_document,
                        historical_questions=historical,
                        progress_hook=progress_hook,
                        cancel_check=cancel_check,
                        checkpointer=checkpointer,
                        thread_id=str(job_id),
                    )
        return await run_generation_graph(
            supervisor,
            spec,
            evidence_by_document,
            historical_questions=historical,
            progress_hook=progress_hook,
            cancel_check=cancel_check,
            thread_id=str(job_id),
        )

    try:
        result = await invoke_graph()
    except LangGraphUnavailable:
        native = await supervisor.run(
            spec,
            evidence_by_document,
            historical_questions=historical,
            progress_hook=progress_hook,
            cancel_check=cancel_check,
        )
        result = native.to_dict()
    result = dict(result)
    result["warnings"] = list(
        dict.fromkeys([*(result.get("warnings") or []), *preflight_warnings])
    )
    result["model_profile_ids"] = {
        "blueprint": blueprint_profile_id,
        "author": author_profile_id,
        "reviewer": reviewer_profile_id,
        "vision": vision_profile_id,
        "embedding": resolved_embedding_profile_id,
    }
    return result


def _persist_generation_result(job_id: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    from sqlalchemy import select

    from app.core.config import settings
    from app.db import SessionLocal
    from app.models import (
        Blueprint,
        Chunk,
        Citation,
        GenerationJob,
        KnowledgeEvidence,
        KnowledgePoint,
        Paper,
        PaperQuestion,
        Question,
        QuestionOption,
        QuestionReview,
    )
    from app.services.deduplication import question_stem_hash

    with SessionLocal() as db:
        job = db.get(GenerationJob, str(job_id))
        if job is None:
            raise LookupError(f"任务不存在：{job_id}")
        if result.get("status") in {"cancelled", "canceled"}:
            job.status = "canceled"
            job.stage = "canceled"
            job.completed_at = _utcnow()
            job.result_json = dict(result)
            db.commit()
            return job.result_json

        request = job.request_json or {}
        blueprint_data = dict(result.get("blueprint") or {})
        blueprint = Blueprint(
            library_id=job.library_id,
            job_id=job.id,
            name=f"任务 {job.id[:8]} 考点蓝图",
            status="ready",
            source_document_ids=list(request.get("outline_document_ids") or []),
            content_json=blueprint_data,
            gaps_json=[{"message": value} for value in (blueprint_data.get("coverage_gaps") or [])],
        )
        db.add(blueprint)
        db.flush()
        job.blueprint_id = blueprint.id
        for raw_topic in blueprint_data.get("topics") or []:
            point = KnowledgePoint(
                blueprint_id=blueprint.id,
                name=str(raw_topic.get("name") or "未命名考点"),
                description=str(raw_topic.get("rationale") or "") or None,
                weight=float(raw_topic.get("weight") or 0),
                keywords=list(raw_topic.get("keywords") or []),
            )
            db.add(point)
            db.flush()
            for evidence_id in dict.fromkeys(raw_topic.get("evidence_ids") or []):
                if db.get(Chunk, str(evidence_id)) is not None:
                    db.add(
                        KnowledgeEvidence(knowledge_point_id=point.id, chunk_id=str(evidence_id))
                    )

        questions_data = list(result.get("questions") or [])
        paper = Paper(
            library_id=job.library_id,
            job_id=job.id,
            title=str(
                request.get("title")
                or f"模拟卷 {_paper_timestamp(job.created_at, settings.app_timezone)}"
            ),
            status="ready" if result.get("status") == "completed" else "partial",
            target_count=job.target_count,
            actual_count=0,
            random_seed=job.random_seed,
            metadata_json={
                "quotas": dict(result.get("quotas") or {}),
                "deficits": dict(result.get("deficits") or {}),
                "warnings": list(result.get("warnings") or []),
                "prompt_version": job.prompt_version,
                "model_profile_ids": dict(result.get("model_profile_ids") or {}),
            },
        )
        db.add(paper)
        db.flush()
        saved = 0
        reviewer_profile_id = (result.get("model_profile_ids") or {}).get("reviewer")
        for raw in questions_data:
            stem = str(raw.get("stem") or "").strip()
            normalized_hash = question_stem_hash(stem)
            if db.scalar(
                select(Question.id).where(
                    Question.library_id == job.library_id,
                    Question.normalized_hash == normalized_hash,
                )
            ):
                continue
            question = Question(
                library_id=job.library_id,
                stem=stem,
                normalized_hash=normalized_hash,
                correct_option=str(raw.get("correct_option") or ""),
                explanation=str(raw.get("explanation") or ""),
                knowledge_point=str(raw.get("knowledge_point") or ""),
                difficulty=str(raw.get("difficulty") or "medium"),
                status="approved",
                similarity_relaxed=bool(raw.get("similarity_relaxed")),
                generation_metadata={
                    **dict(raw.get("generation_metadata") or {}),
                    "job_id": job.id,
                    "document_id": raw.get("document_id"),
                    "angle": raw.get("angle"),
                },
            )
            db.add(question)
            db.flush()
            raw_options = raw.get("options") or []
            for position, option in enumerate(raw_options):
                if isinstance(option, Mapping):
                    label = str(option.get("label") or "ABCD"[position])
                    text = str(option.get("text") or "")
                else:
                    label, text = "ABCD"[position], str(option)
                db.add(
                    QuestionOption(
                        question_id=question.id, label=label, text=text, position=position
                    )
                )
            for evidence_id in raw.get("citations") or raw.get("evidence_ids") or []:
                chunk = db.get(Chunk, str(evidence_id))
                if chunk is None:
                    continue
                anchor = _select_citation_anchor(chunk, raw)
                page = next(
                    (
                        item
                        for item in chunk.document_version.pages
                        if item.page_number == (anchor.get("page_number") or chunk.page_start)
                    ),
                    None,
                )
                rectangles = []
                for rect in anchor.get("rects") or []:
                    if isinstance(rect, dict):
                        rectangles.append(rect)
                    elif isinstance(rect, (list, tuple)) and len(rect) == 4:
                        x0, y0, x1, y1 = (float(value) for value in rect)
                        rectangles.append(
                            {
                                "x": x0,
                                "y": y0,
                                "width": max(0.0, x1 - x0),
                                "height": max(0.0, y1 - y0),
                                "page_width": anchor.get("page_width")
                                or (page.width if page else None),
                                "page_height": anchor.get("page_height")
                                or (page.height if page else None),
                                "coordinate_system": "bottom-left"
                                if "bottom" in str(anchor.get("coordinate_system") or "").lower()
                                else "top-left",
                            }
                        )
                db.add(
                    Citation(
                        question_id=question.id,
                        document_version_id=chunk.document_version_id,
                        chunk_id=chunk.id,
                        block_id=anchor.get("block_id") or chunk.block_id,
                        page_number=anchor.get("page_number") or chunk.page_start,
                        rects=rectangles,
                        excerpt=str(anchor.get("quote") or chunk.text),
                        excerpt_hash=str(
                            anchor.get("quote_hash")
                            or hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
                        ),
                        char_start=anchor.get("char_start"),
                        char_end=anchor.get("char_end"),
                    )
                )
            review = dict(raw.get("review") or {})
            db.add(
                QuestionReview(
                    question_id=question.id,
                    reviewer_profile_id=reviewer_profile_id,
                    status="passed" if review.get("passed") else "failed",
                    chosen_option=review.get("selected_option"),
                    issues=list(review.get("issues") or []),
                    rationale="由独立审题 Agent 作答并通过确定性比对",
                )
            )
            db.add(PaperQuestion(paper_id=paper.id, question_id=question.id, position=saved))
            saved += 1

        paper.actual_count = saved
        final_status = (
            "completed"
            if saved == job.target_count and result.get("status") == "completed"
            else "partial"
        )
        paper.status = "ready" if final_status == "completed" else "partial"
        persisted = {
            **dict(result),
            "status": final_status,
            "paper_id": paper.id,
            "blueprint_id": blueprint.id,
            "persisted_question_count": saved,
        }
        job.status = final_status
        job.stage = final_status
        job.progress = 100.0
        job.accepted_count = saved
        stats = result.get("statistics") or {}
        job.rejected_count = int(stats.get("rejected") or 0)
        job.revision_count = int(stats.get("revised") or 0)
        job.result_json = persisted
        job.completed_at = _utcnow()
        db.commit()
        return persisted


@celery_app.task(bind=True, name="app.tasks.generate_exam")
def generate_exam(self: Any, job_id: str) -> Mapping[str, Any]:
    """运行 LangGraph（可用时）并将正式试卷一次性落库。"""

    from app.core.job_events import append_job_event
    from app.core.security import redact_text
    from app.db import SessionLocal
    from app.models import GenerationJob

    with SessionLocal() as db:
        job = db.get(GenerationJob, str(job_id))
        if job is None:
            raise LookupError(f"任务不存在：{job_id}")
        if job.status in {"completed", "partial", "canceled"}:
            return dict(job.result_json or {"status": job.status})
        if job.cancel_requested:
            job.status = "canceled"
            job.stage = "canceled"
            job.completed_at = _utcnow()
            db.commit()
            return {"status": "canceled"}
        job.status = "running"
        job.stage = "validating"
        job.started_at = job.started_at or _utcnow()
        job.error = None
        db.commit()

    try:
        result = asyncio.run(_execute_generation(str(job_id)))
        return _persist_generation_result(str(job_id), result)
    except Exception as exc:
        # 绝不把已解密 API Key 放入日志、事件或接口错误。
        message = f"{type(exc).__name__}: {str(exc)[:1000]}"
        if "ReadTimeout" in message:
            from app.core.config import settings

            message = (
                "模型响应超时：单次请求等待超过 "
                f"{int(settings.model_request_timeout_seconds)} 秒。"
                "系统已自动重试；可稍后重试任务，或改用响应更快的模型。"
            )
        with SessionLocal() as db:
            job = db.get(GenerationJob, str(job_id))
            if job is not None:
                try:
                    assignments = (job.request_json or {}).get("model_assignments") or {}
                    from app.core.security import decrypt_secret
                    from app.models import ModelProfile

                    for profile_id in assignments.values():
                        profile = db.get(ModelProfile, str(profile_id))
                        if profile:
                            message = redact_text(
                                message, decrypt_secret(profile.api_key_encrypted)
                            )
                except Exception:
                    message = "出题任务失败，且模型密钥配置无法读取"
                job.status = "failed"
                job.stage = "failed"
                job.progress = 100.0
                job.error = message
                job.completed_at = _utcnow()
                db.commit()
                append_job_event(
                    db,
                    str(job_id),
                    stage="failed",
                    progress=100,
                    message="出题任务失败",
                    payload={"error": message},
                    status="failed",
                )
        logger.exception("出题任务失败：%s（%s）", job_id, type(exc).__name__)
        raise


def _question_agent_context(db: Any, question_id: str) -> dict[str, Any]:
    """读取人工复审/重生成所需的不可变证据与原任务模型快照。"""

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import Citation, GenerationJob, Question
    from app.workflows.generation import Evidence, QuestionCandidate

    question = db.scalar(
        select(Question)
        .options(
            selectinload(Question.options),
            selectinload(Question.citations).selectinload(Citation.document_version),
            selectinload(Question.reviews),
        )
        .where(Question.id == question_id)
    )
    if question is None:
        raise LookupError(f"题目不存在：{question_id}")
    evidence: list[Evidence] = []
    for citation in question.citations:
        chunk = citation.document_version.chunks and next(
            (item for item in citation.document_version.chunks if item.id == citation.chunk_id),
            None,
        )
        if chunk is None:
            continue
        evidence.append(
            Evidence(
                evidence_id=chunk.id,
                document_id=citation.document_id,
                text=chunk.text,
                chunk_id=chunk.id,
                document_version_id=chunk.document_version_id,
                section_path=tuple((chunk.metadata_json or {}).get("section_path") or ()),
                anchor={"anchors": chunk.bbox_data},
            )
        )
    options = tuple(
        item.text for item in sorted(question.options, key=lambda value: value.position)
    )
    if len(options) != 4:
        raise RuntimeError("题目选项结构不完整，无法调用 Agent")
    candidate = QuestionCandidate(
        question_id=question.id,
        document_id=str((question.generation_metadata or {}).get("document_id") or ""),
        stem=question.stem,
        options=options,  # type: ignore[arg-type]
        correct_option=question.correct_option,
        explanation=question.explanation,
        knowledge_point=question.knowledge_point,
        difficulty=question.difficulty,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        angle=str((question.generation_metadata or {}).get("angle") or ""),
        generation_metadata=dict(question.generation_metadata or {}),
    )
    job_id = str((question.generation_metadata or {}).get("job_id") or "")
    job = db.get(GenerationJob, job_id) if job_id else None
    request = dict(job.request_json or {}) if job else {}
    assignments = dict(request.get("model_assignments") or {})
    local_mode = request.get("execution_mode") == "local"
    return {
        "question": question,
        "candidate": candidate,
        "evidence": evidence,
        "assignments": assignments,
        "local_mode": local_mode,
    }


@celery_app.task(bind=True, name="app.tasks.review_question")
def review_question(self: Any, question_id: str) -> Mapping[str, Any]:
    """使用原任务的独立审题模型重新作答并更新人工复核状态。"""

    from app.db import SessionLocal
    from app.models import QuestionReview
    from app.workflows.generation import QuestionReviewerAgent

    with SessionLocal() as db:
        context = _question_agent_context(db, str(question_id))
        gateway, profile_id = _profile_gateway(
            db,
            _role_profile_id(context["assignments"], "reviewer"),
            local_mode=context["local_mode"],
        )
        outcome = asyncio.run(
            QuestionReviewerAgent(gateway).review(
                context["candidate"],
                evidence=context["evidence"],
                seed=secrets.randbits(31),
            )
        )
        question = context["question"]
        pending = next(
            (item for item in reversed(question.reviews) if item.status == "pending"),
            None,
        )
        review = pending or QuestionReview(question_id=question.id, status="pending", issues=[])
        review.reviewer_profile_id = profile_id
        review.status = "passed" if outcome.passed else "failed"
        review.chosen_option = outcome.selected_option or None
        review.issues = list(outcome.feedback)
        review.rationale = "独立审题 Agent 已基于原始正文证据重新作答"
        if pending is None:
            db.add(review)
        question.status = "approved" if outcome.passed else "needs_revision"
        db.commit()
        return {
            "question_id": question.id,
            "status": question.status,
            "review_status": review.status,
            "issues": review.issues,
        }


@celery_app.task(bind=True, name="app.tasks.regenerate_question")
def regenerate_question(self: Any, question_id: str) -> Mapping[str, Any]:
    """基于原引用生成新题并替换试卷关联，保留旧题供历史答题追溯。"""

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Citation, PaperQuestion, Question, QuestionOption, QuestionReview
    from app.services.deduplication import DuplicatePolicy, question_stem_hash
    from app.workflows.generation import (
        QuestionAuthorAgent,
        QuestionReviewerAgent,
        validate_question,
    )

    with SessionLocal() as db:
        context = _question_agent_context(db, str(question_id))
        author_gateway, _ = _profile_gateway(
            db,
            _role_profile_id(context["assignments"], "author"),
            local_mode=context["local_mode"],
        )
        reviewer_gateway, reviewer_profile_id = _profile_gateway(
            db,
            _role_profile_id(context["assignments"], "reviewer"),
            local_mode=context["local_mode"],
        )

        historical = _load_historical_fingerprints(
            db,
            context["question"].library_id,
            exclude_question_ids={context["question"].id},
        )

        async def run_agents() -> tuple[Any, Any]:
            candidate = context["candidate"]
            previous_review_issues = tuple(
                issue
                for review in reversed(context["question"].reviews)
                if review.status == "failed"
                for issue in review.issues
            )[:6]
            feedback = (
                "用户请求换一个设问角度重新生成，不能仅做同义改写",
                "优先改成有实际判断价值的情境、分类、比较或决策题",
                "禁止询问资料列出、提到或出现了什么，也不能把资料未提及当作错误依据",
                "若证据只列出术语，只能考证据直接支持的概念分类或应用，不能凭空补写恢复速度、机制等关键前提",
                *previous_review_issues,
            )
            last_error = "出题模型没有返回可用的新题"
            for revision in range(1, 4):
                revised = await QuestionAuthorAgent(author_gateway).revise(
                    candidate,
                    evidence=context["evidence"],
                    feedback=feedback,
                    seed=secrets.randbits(31),
                    revision=revision,
                )
                if revised is None:
                    last_error = "出题模型没有返回可用的新题"
                    continue
                issues = validate_question(
                    revised, {item.evidence_id for item in context["evidence"]}
                )
                duplicate = DuplicatePolicy().evaluate(
                    revised.fingerprint(),
                    historical,
                    relaxed=False,
                )
                if not duplicate.accepted:
                    issues = (
                        *issues,
                        "新题与现有题目过于相似，必须改考察事实、应用情境或设问角度",
                    )
                if issues:
                    last_error = "；".join(issues)
                    feedback = tuple(issues)
                    candidate = revised
                    continue
                review = await QuestionReviewerAgent(reviewer_gateway).review(
                    revised,
                    evidence=[
                        item
                        for item in context["evidence"]
                        if item.evidence_id in revised.evidence_ids
                    ],
                    seed=secrets.randbits(31),
                )
                if review.passed:
                    return revised, review
                last_error = "新题独立审查未通过：" + "；".join(review.feedback)
                feedback = review.feedback or ("审题未通过，请更换设问角度",)
                candidate = revised
            raise RuntimeError(last_error)

        try:
            revised, outcome = asyncio.run(run_agents())
        except Exception as exc:
            context["question"].status = "needs_revision"
            db.add(
                QuestionReview(
                    question_id=context["question"].id,
                    reviewer_profile_id=reviewer_profile_id,
                    status="failed",
                    issues=[str(exc)[:500]],
                    rationale="重新生成失败，原题仍保留",
                )
            )
            db.commit()
            raise

        normalized_hash = question_stem_hash(revised.stem)
        if db.scalar(select(Question.id).where(Question.normalized_hash == normalized_hash)):
            raise RuntimeError("重新生成结果与现有题目完全重复")
        original = context["question"]
        replacement = Question(
            library_id=original.library_id,
            stem=revised.stem,
            normalized_hash=normalized_hash,
            correct_option=revised.correct_option,
            explanation=revised.explanation,
            knowledge_point=revised.knowledge_point,
            difficulty=revised.difficulty,
            status="approved",
            similarity_relaxed=revised.similarity_relaxed,
            generation_metadata=_regenerated_question_metadata(
                original.id,
                original.generation_metadata,
                revised.generation_metadata,
            ),
        )
        for position, (label, text) in enumerate(zip("ABCD", revised.options, strict=True)):
            replacement.options.append(
                QuestionOption(label=label, text=text, position=position)
            )
        citations_by_chunk = {item.chunk_id: item for item in original.citations}
        for evidence_id in revised.evidence_ids:
            source = citations_by_chunk.get(evidence_id)
            if source is None:
                continue
            replacement.citations.append(
                Citation(
                    document_version_id=source.document_version_id,
                    chunk_id=source.chunk_id,
                    block_id=source.block_id,
                    page_number=source.page_number,
                    rects=list(source.rects),
                    excerpt=source.excerpt,
                    excerpt_hash=source.excerpt_hash,
                    char_start=source.char_start,
                    char_end=source.char_end,
                )
            )
        replacement.reviews.append(
            QuestionReview(
                reviewer_profile_id=reviewer_profile_id,
                status="passed",
                chosen_option=outcome.selected_option,
                issues=[],
                rationale="新题已通过独立审查",
            )
        )
        db.add(replacement)
        db.flush()
        for link in db.scalars(
            select(PaperQuestion).where(PaperQuestion.question_id == original.id)
        ).all():
            link.question_id = replacement.id
        original.status = "disabled"
        db.commit()
        return {
            "question_id": replacement.id,
            "replaced_question_id": original.id,
            "status": "approved",
        }
