from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import documents as documents_api
from app.api import jobs as jobs_api
from app.api import papers as papers_api
from app.db import Base, get_db
from app.main import app
from app.models import (
    Chunk,
    Citation,
    ContentBlock,
    Document,
    DocumentVersion,
    GenerationJob,
    ImageAsset,
    ModelProfile,
    Page,
    Paper,
    PaperQuestion,
    Question,
    QuestionOption,
    QuestionReview,
)


@pytest.fixture()
def testing_session(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(documents_api.settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(jobs_api, "SessionLocal", TestingSession)
    monkeypatch.setattr(documents_api, "enqueue_task", lambda *args: True)
    monkeypatch.setattr(jobs_api, "enqueue_task", lambda *args: True)
    monkeypatch.setattr(papers_api, "enqueue_task", lambda *args: True)
    yield TestingSession
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(testing_session):
    return TestClient(app)


def _create_library(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/libraries",
        json={"name": "CISP 备考资料", "description": "个人知识库"},
    )
    assert response.status_code == 201
    return response.json()


def _upload_ready_document(
    client: TestClient,
    TestingSession,
    library_id: str,
    *,
    role: str = "source",
    allow_as_evidence: bool | None = None,
) -> dict:
    data = {"library_id": library_id, "role": role}
    if allow_as_evidence is not None:
        data["allow_as_evidence"] = str(allow_as_evidence).lower()
    response = client.post(
        "/api/v1/documents",
        data=data,
        files={"file": ("计算环境安全.txt", "访问控制是信息安全的重要机制。", "text/plain")},
    )
    assert response.status_code == 201
    document = response.json()
    with TestingSession() as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document["id"])
        )
        assert version is not None
        version.status = "ready"
        version.progress = 100
        chunk = Chunk(
            document_version_id=version.id,
            ordinal=0,
            page_start=1,
            page_end=1,
            text="访问控制是信息安全的重要机制。",
            text_hash=hashlib.sha256("访问控制是信息安全的重要机制。".encode()).hexdigest(),
        )
        db.add(chunk)
        db.commit()
    return document


def test_library_upload_model_secret_and_job_events(client: TestClient, testing_session):
    library = _create_library(client)
    document = _upload_ready_document(client, testing_session, library["id"])

    profile_response = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "本机出题模型",
            "provider": "ollama",
            "base_url": "http://host.docker.internal:11434",
            "model_name": "qwen3:8b",
            "api_key": "super-secret-key",
            "capabilities": {"structured_output": True},
        },
    )
    assert profile_response.status_code == 201
    serialized = profile_response.json()
    assert serialized["has_api_key"] is True
    assert "super-secret-key" not in profile_response.text
    with testing_session() as db:
        stored = db.get(ModelProfile, serialized["id"])
        assert stored is not None
        assert stored.api_key_encrypted != "super-secret-key"

    invalid = client.post(
        "/api/v1/jobs",
        json={
            "library_id": library["id"],
            "source_documents": [{"document_id": document["id"], "percentage": 90}],
            "target_count": 50,
        },
    )
    assert invalid.status_code == 422

    created = client.post(
        "/api/v1/jobs",
        json={
            "library_id": library["id"],
            "source_documents": [{"document_id": document["id"], "percentage": 100}],
            "target_count": 50,
            "execution_mode": "local",
            "model_assignments": {"generator": serialized["id"]},
        },
    )
    assert created.status_code == 201
    job = created.json()
    assert job["status"] == "queued"
    assert job["target_count"] == 50
    assert 0 <= job["random_seed"] <= 2_147_483_647
    assert job["request_json"]["model_assignments"] == {
        "blueprint": serialized["id"],
        "author": serialized["id"],
        "reviewer": serialized["id"],
    }

    canceled = client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    with client.stream("GET", f"/api/v1/jobs/{job['id']}/events") as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: progress" in body
    assert "任务已取消" in body


def test_paper_exam_scoring_and_mistake_retry(client: TestClient, testing_session):
    library = _create_library(client)
    with testing_session() as db:
        paper = Paper(
            library_id=library["id"],
            title="模拟卷 1",
            status="ready",
            target_count=1,
            actual_count=1,
            random_seed=42,
        )
        question = Question(
            library_id=library["id"],
            stem="访问控制的首要目标是什么？",
            normalized_hash=hashlib.sha256("访问控制的首要目标是什么".encode()).hexdigest(),
            correct_option="A",
            explanation="访问控制用于限制主体对客体的访问。",
            knowledge_point="访问控制",
            difficulty="easy",
        )
        for position, (label, text) in enumerate(
            [("A", "限制未授权访问"), ("B", "提高网速"), ("C", "压缩文件"), ("D", "美化界面")]
        ):
            question.options.append(QuestionOption(label=label, text=text, position=position))
        paper.paper_questions.append(PaperQuestion(question=question, position=1))
        db.add(paper)
        db.commit()
        paper_id = paper.id
        question_id = question.id

    paper_response = client.get(f"/api/v1/papers/{paper_id}")
    assert paper_response.status_code == 200
    assert paper_response.json()["questions"][0]["correct_option"] == "A"

    started = client.post(
        "/api/v1/practice-sessions", json={"paper_id": paper_id, "mode": "exam"}
    )
    assert started.status_code == 201
    assert started.json()["questions"][0]["correct_option"] is None
    assert started.json()["questions"][0]["citations"] == []
    session_id = started.json()["id"]
    answered = client.post(
        f"/api/v1/practice-sessions/{session_id}/answers",
        json={"question_id": question_id, "selected_option": "B"},
    )
    assert answered.status_code == 200
    assert answered.json()["is_correct"] is None
    assert answered.json()["correct_option"] is None

    submitted = client.post(f"/api/v1/practice-sessions/{session_id}/submit")
    assert submitted.status_code == 200
    result = submitted.json()
    assert result["score"] == 0
    assert result["answers"][0]["is_correct"] is False
    assert result["questions"][0]["explanation"]

    retry = client.post(f"/api/v1/practice-sessions/{session_id}/retry-mistakes")
    assert retry.status_code == 201
    assert retry.json()["total_count"] == 1

    wrong_answers = client.get("/api/v1/practice-sessions/wrong-answers")
    assert wrong_answers.status_code == 200
    assert wrong_answers.json()[0]["question"]["id"] == question_id
    assert wrong_answers.json()[0]["wrong_count"] == 1

    selected_retry = client.post(
        "/api/v1/practice-sessions/wrong-answers/retry",
        json={"question_ids": [question_id]},
    )
    assert selected_retry.status_code == 201
    assert selected_retry.json()["mode"] == "wrong_answers"
    assert selected_retry.json()["questions"][0]["correct_option"] == "A"
    retried_answer = client.post(
        f"/api/v1/practice-sessions/{selected_retry.json()['id']}/answers",
        json={"question_id": question_id, "selected_option": "A"},
    )
    assert retried_answer.status_code == 200
    assert retried_answer.json()["is_correct"] is True
    assert retried_answer.json()["correct_option"] == "A"


def test_citation_contract_contains_document_and_normalized_rectangles(
    client: TestClient, testing_session
):
    library = _create_library(client)
    document = _upload_ready_document(client, testing_session, library["id"])
    with testing_session() as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document["id"])
        )
        assert version is not None
        chunk = db.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
        assert chunk is not None
        db.add(Page(document_version_id=version.id, page_number=1, width=600, height=800))
        block = ContentBlock(
            document_version_id=version.id,
            block_index=0,
            block_type="paragraph",
            text=chunk.text,
            char_start=0,
            char_end=len(chunk.text),
        )
        db.add(block)
        db.flush()
        chunk.block_id = block.id
        paper = Paper(
            library_id=library["id"],
            title="出处契约测试卷",
            status="ready",
            target_count=1,
            actual_count=1,
            random_seed=7,
        )
        question = Question(
            library_id=library["id"],
            stem="访问控制是什么？",
            normalized_hash=hashlib.sha256("访问控制是什么".encode()).hexdigest(),
            correct_option="A",
            explanation="正文直接说明访问控制属于安全机制。",
            knowledge_point="访问控制",
            difficulty="easy",
        )
        for position, label in enumerate(("A", "B", "C", "D")):
            question.options.append(
                QuestionOption(label=label, text=f"选项 {label}", position=position)
            )
        question.citations.append(
            Citation(
                document_version_id=version.id,
                chunk_id=chunk.id,
                block_id=block.id,
                page_number=1,
                rects=[[10, 20, 110, 60]],
                excerpt=chunk.text,
                excerpt_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
            )
        )
        paper.paper_questions.append(PaperQuestion(question=question, position=1))
        db.add(paper)
        db.commit()
        paper_id = paper.id
        version_id = version.id
        block_id = block.id

    response = client.get(f"/api/v1/papers/{paper_id}")
    assert response.status_code == 200
    citation = response.json()["questions"][0]["citations"][0]
    assert citation["document_id"] == document["id"]
    assert citation["document_name"] == "计算环境安全.txt"
    assert citation["document_type"] == ".txt"
    assert citation["rectangles"] == [
        {
            "x": 10.0,
            "y": 20.0,
            "width": 100.0,
            "height": 40.0,
            "page_width": 600.0,
            "page_height": 800.0,
            "coordinate_system": "top-left",
        }
    ]
    content = client.get(
        f"/api/v1/documents/{document['id']}/content",
        params={"version_id": version_id, "block_id": block_id},
    )
    assert content.status_code == 200
    assert content.json()["version_id"] == version_id
    assert [item["id"] for item in content.json()["blocks"]] == [block_id]


def test_visual_enrichment_persists_parent_block_before_chunk(
    client: TestClient, testing_session, tmp_path, monkeypatch
):
    from app import tasks
    from app.core.config import settings
    from app.services import content_enrichment

    library = _create_library(client)
    document = _upload_ready_document(client, testing_session, library["id"])
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    image_path = storage_dir / "visual.png"
    image_path.write_bytes(b"valid-test-image-placeholder")
    monkeypatch.setattr(settings, "storage_dir", storage_dir)

    with testing_session() as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document["id"])
        )
        assert version is not None
        db.add(Page(document_version_id=version.id, page_number=1, width=600, height=800))
        asset = ImageAsset(
            id="visual-asset-parent-first",
            document_version_id=version.id,
            page_number=1,
            storage_path=str(image_path),
            content_hash="a" * 64,
            bbox=[10, 20, 110, 60],
            metadata_json={},
        )
        db.add(asset)
        db.commit()
        version_id = version.id

    calls: list[str] = []

    async def fake_describe_image(*args, **kwargs):
        calls.append("called")
        return {
            "description": "访问控制流程图",
            "key_facts": ["主体经过访问控制后访问客体"],
            "question_worthy": True,
        }

    monkeypatch.setattr(content_enrichment, "describe_image", fake_describe_image)
    gateway = SimpleNamespace(profile=SimpleNamespace(model_name="vision-test"))
    with testing_session() as db:
        warnings = asyncio.run(
            tasks._enrich_visual_chunks(
                db,
                [document["id"]],
                gateway,
                "vision-profile-test",
            )
        )
        assert warnings == []
        chunk = db.get(
            Chunk,
            "v_" + hashlib.sha256(b"visual-asset-parent-first").hexdigest()[:32],
        )
        assert chunk is not None
        assert chunk.document_version_id == version_id
        assert chunk.block_id is not None
        assert db.get(ContentBlock, chunk.block_id) is not None
        assert len(calls) == 1

    gateway.profile.model_name = "vision-test-v2"
    with testing_session() as db:
        warnings = asyncio.run(
            tasks._enrich_visual_chunks(
                db,
                [document["id"]],
                gateway,
                "vision-profile-test",
            )
        )
        assert warnings == []
        assert len(calls) == 2
        asset = db.get(ImageAsset, "visual-asset-parent-first")
        assert asset is not None
        assert asset.analysis_model == "vision-test-v2"
        assert (
            "vision-profile-test:vision-test-v2"
            in asset.metadata_json["visual_analyses"]
        )


def test_outline_can_only_enter_answer_quota_with_explicit_permission(
    client: TestClient, testing_session
):
    library = _create_library(client)
    outline = _upload_ready_document(
        client,
        testing_session,
        library["id"],
        role="outline",
        allow_as_evidence=True,
    )
    payload = {
        "library_id": library["id"],
        "outline_document_ids": [outline["id"]],
        "source_documents": [{"document_id": outline["id"], "percentage": 100}],
        "target_count": 10,
    }

    denied = client.post("/api/v1/jobs", json=payload)
    assert denied.status_code == 422

    profile = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "重点资料测试模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "qwen3:8b",
            "capabilities": {"structured_output": True},
        },
    )
    assert profile.status_code == 201
    allowed = client.post(
        "/api/v1/jobs", json={**payload, "allow_outline_as_evidence": True}
    )
    assert allowed.status_code == 201


def test_document_role_keeps_evidence_permission_consistent(
    client: TestClient,
    testing_session,
):
    library = _create_library(client)

    source = client.post(
        "/api/v1/documents",
        data={
            "library_id": library["id"],
            "role": "source",
            "allow_as_evidence": "false",
        },
        files={"file": ("source.txt", "正文", "text/plain")},
    )
    assert source.status_code == 201
    assert source.json()["allow_as_evidence"] is True

    outline = client.post(
        "/api/v1/documents",
        data={"library_id": library["id"], "role": "outline"},
        files={"file": ("outline.txt", "重点", "text/plain")},
    )
    assert outline.status_code == 201
    assert outline.json()["allow_as_evidence"] is False

    explicit_outline = client.post(
        "/api/v1/documents",
        data={
            "library_id": library["id"],
            "role": "outline",
            "allow_as_evidence": "true",
        },
        files={"file": ("allowed-outline.txt", "可引用重点", "text/plain")},
    )
    assert explicit_outline.status_code == 201
    assert explicit_outline.json()["allow_as_evidence"] is True

    source_update = client.patch(
        f"/api/v1/documents/{outline.json()['id']}",
        json={"role": "source", "allow_as_evidence": False},
    )
    assert source_update.status_code == 200
    assert source_update.json()["role"] == "source"
    assert source_update.json()["allow_as_evidence"] is True

    outline_update = client.patch(
        f"/api/v1/documents/{source.json()['id']}",
        json={"role": "outline"},
    )
    assert outline_update.status_code == 200
    assert outline_update.json()["allow_as_evidence"] is False

    explicit_update = client.patch(
        f"/api/v1/documents/{source.json()['id']}",
        json={"allow_as_evidence": True},
    )
    assert explicit_update.status_code == 200
    assert explicit_update.json()["allow_as_evidence"] is True

    with testing_session() as db:
        stored_source = db.get(Document, outline.json()["id"])
        assert stored_source is not None
        assert stored_source.role == "source"
        assert stored_source.allow_as_evidence is True


def test_model_default_roles_are_persisted_unique_and_secret_safe(
    client: TestClient,
    testing_session,
):
    first = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "默认结构化模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "qwen3:8b",
            "api_key": "do-not-return-this-key",
            "capabilities": {"structured_output": True},
            "default_roles": ["blueprint", "author", "reviewer", "author"],
        },
    )
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["default_roles"] == ["blueprint", "author", "reviewer"]
    assert "api_key" not in first_body
    assert "do-not-return-this-key" not in first.text

    second = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "新的出题审题默认模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "qwen3:14b",
            "capabilities": {"structured_output": True},
            "default_roles": ["author", "reviewer"],
        },
    )
    assert second.status_code == 201

    first_after = client.get(f"/api/v1/model-profiles/{first_body['id']}")
    assert first_after.status_code == 200
    assert first_after.json()["default_roles"] == ["blueprint"]

    updated = client.patch(
        f"/api/v1/model-profiles/{second.json()['id']}",
        json={"default_roles": ["author"]},
    )
    assert updated.status_code == 200
    assert updated.json()["default_roles"] == ["author"]

    without_defaults = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "无默认角色模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "qwen3:4b",
            "capabilities": {"structured_output": True},
        },
    )
    assert without_defaults.status_code == 201
    assert without_defaults.json()["default_roles"] == []

    with testing_session() as db:
        stored = db.get(ModelProfile, first_body["id"])
        assert stored is not None
        assert stored.default_roles == ["blueprint"]
        assert stored.api_key_encrypted != "do-not-return-this-key"


def test_job_resolves_required_roles_from_role_defaults(
    client: TestClient,
    testing_session,
):
    library = _create_library(client)
    document = _upload_ready_document(client, testing_session, library["id"])
    blueprint = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "蓝图模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "blueprint",
            "capabilities": {"structured_output": True},
            "default_roles": ["blueprint"],
        },
    )
    author_reviewer = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "出题审题模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "author-reviewer",
            "capabilities": {"structured_output": True},
            "default_roles": ["author", "reviewer"],
        },
    )
    assert blueprint.status_code == 201
    assert author_reviewer.status_code == 201

    created = client.post(
        "/api/v1/jobs",
        json={
            "library_id": library["id"],
            "source_documents": [{"document_id": document["id"], "percentage": 100}],
            "target_count": 10,
        },
    )
    assert created.status_code == 201
    assert created.json()["request_json"]["model_assignments"] == {
        "blueprint": blueprint.json()["id"],
        "author": author_reviewer.json()["id"],
        "reviewer": author_reviewer.json()["id"],
    }


def test_job_rejects_ambiguous_or_incapable_required_model_roles(
    client: TestClient,
    testing_session,
):
    library = _create_library(client)
    document = _upload_ready_document(client, testing_session, library["id"])
    compatible_ids = []
    for index in range(2):
        profile = client.post(
            "/api/v1/model-profiles",
            json={
                "name": f"候选结构化模型 {index}",
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model_name": f"candidate-{index}",
                "capabilities": {"structured_output": True},
            },
        )
        assert profile.status_code == 201
        compatible_ids.append(profile.json()["id"])

    payload = {
        "library_id": library["id"],
        "source_documents": [{"document_id": document["id"], "percentage": 100}],
        "target_count": 10,
    }
    ambiguous = client.post("/api/v1/jobs", json=payload)
    assert ambiguous.status_code == 422
    assert "default_roles" in ambiguous.json()["detail"]

    incapable = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "无结构化能力模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "plain-chat",
            "capabilities": {},
        },
    )
    assert incapable.status_code == 201
    invalid_assignment = client.post(
        "/api/v1/jobs",
        json={
            **payload,
            "model_assignments": {
                "blueprint": compatible_ids[0],
                "author": compatible_ids[0],
                "reviewer": incapable.json()["id"],
            },
        },
    )
    assert invalid_assignment.status_code == 422
    assert "structured_output" in invalid_assignment.json()["detail"]

    invalid_default = client.patch(
        f"/api/v1/model-profiles/{incapable.json()['id']}",
        json={"default_roles": ["reviewer"]},
    )
    assert invalid_default.status_code == 422


def test_enqueue_failure_marks_document_and_job_failed(
    client: TestClient,
    testing_session,
    monkeypatch,
):
    library = _create_library(client)
    monkeypatch.setattr(documents_api, "enqueue_task", lambda *args: False)
    failed_upload = client.post(
        "/api/v1/documents",
        data={"library_id": library["id"], "role": "source"},
        files={"file": ("queue-failure.txt", "正文", "text/plain")},
    )
    assert failed_upload.status_code == 503
    assert "入队失败" in failed_upload.json()["detail"]
    with testing_session() as db:
        failed_version = db.scalar(select(DocumentVersion))
        assert failed_version is not None
        assert failed_version.status == "failed"
        assert failed_version.progress == 100
        assert "入队失败" in (failed_version.error or "")

    monkeypatch.setattr(documents_api, "enqueue_task", lambda *args: True)
    document = _upload_ready_document(client, testing_session, library["id"])
    monkeypatch.setattr(documents_api, "enqueue_task", lambda *args: False)
    failed_parse = client.post(f"/api/v1/documents/{document['id']}/parse")
    assert failed_parse.status_code == 503
    with testing_session() as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document["id"])
        )
        assert version is not None
        assert version.status == "failed"
        assert version.progress == 100
        version.status = "ready"
        version.error = None
        db.commit()

    profile = client.post(
        "/api/v1/model-profiles",
        json={
            "name": "队列失败测试模型",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model_name": "qwen3:8b",
            "capabilities": {"structured_output": True},
        },
    )
    assert profile.status_code == 201
    monkeypatch.setattr(jobs_api, "enqueue_task", lambda *args: False)
    failed_job = client.post(
        "/api/v1/jobs",
        json={
            "library_id": library["id"],
            "source_documents": [{"document_id": document["id"], "percentage": 100}],
            "target_count": 10,
        },
    )
    assert failed_job.status_code == 503
    with testing_session() as db:
        job = db.scalar(select(GenerationJob))
        assert job is not None
        assert job.status == "failed"
        assert job.stage == "failed"
        assert job.progress == 100
        assert "入队失败" in (job.error or "")
        assert job.completed_at is not None
        failed_job_id = job.id

    failed_retry = client.post(f"/api/v1/jobs/{failed_job_id}/retry")
    assert failed_retry.status_code == 503
    with testing_session() as db:
        retried = db.scalar(
            select(GenerationJob).where(GenerationJob.parent_job_id == failed_job_id)
        )
        assert retried is not None
        assert retried.status == "failed"
        assert retried.stage == "failed"
        assert "入队失败" in (retried.error or "")


def test_enqueue_failure_does_not_leave_question_pending(
    client: TestClient,
    testing_session,
    monkeypatch,
):
    library = _create_library(client)
    document = _upload_ready_document(client, testing_session, library["id"])
    with testing_session() as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document["id"])
        )
        assert version is not None
        chunk = db.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
        assert chunk is not None
        question = Question(
            library_id=library["id"],
            stem="访问控制的作用是什么？",
            normalized_hash=hashlib.sha256("访问控制的作用是什么".encode()).hexdigest(),
            correct_option="A",
            explanation="限制未授权访问。",
            knowledge_point="访问控制",
            difficulty="easy",
            status="approved",
        )
        for position, label in enumerate(("A", "B", "C", "D")):
            question.options.append(
                QuestionOption(label=label, text=f"选项 {label}", position=position)
            )
        question.citations.append(
            Citation(
                document_version_id=version.id,
                chunk_id=chunk.id,
                page_number=1,
                rects=[],
                excerpt=chunk.text,
                excerpt_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
            )
        )
        db.add(question)
        db.commit()
        question_id = question.id

    monkeypatch.setattr(papers_api, "enqueue_task", lambda *args: False)
    failed_review = client.post(f"/api/v1/questions/{question_id}/review")
    assert failed_review.status_code == 503
    with testing_session() as db:
        question = db.get(Question, question_id)
        assert question is not None
        assert question.status == "approved"
        reviews = db.scalars(
            select(QuestionReview).where(QuestionReview.question_id == question_id)
        ).all()
        assert reviews[-1].status == "failed"
        assert any("入队失败" in issue for issue in reviews[-1].issues)

    failed_regeneration = client.post(f"/api/v1/questions/{question_id}/regenerate")
    assert failed_regeneration.status_code == 503
    with testing_session() as db:
        question = db.get(Question, question_id)
        assert question is not None
        assert question.status == "approved"
        reviews = db.scalars(
            select(QuestionReview).where(QuestionReview.question_id == question_id)
        ).all()
        assert reviews[-1].status == "failed"
        assert any("入队失败" in issue for issue in reviews[-1].issues)
