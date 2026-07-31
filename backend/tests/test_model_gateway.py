from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services.content_enrichment import embed_batches, ranked_indices
from app.services.model_gateway import (
    CallableGateway,
    ModelCapability,
    ModelGatewayError,
    ModelProfile,
    Provider,
    create_model_gateway,
)


def test_local_mode_accepts_private_openai_endpoint_and_rejects_public_ollama() -> None:
    local_profile = ModelProfile(
        provider=Provider.OPENAI_COMPATIBLE,
        model_name="local-vllm",
        base_url="http://192.168.1.10:8000/v1",
    )
    assert create_model_gateway(local_profile, local_mode=True).profile == local_profile

    public_ollama = ModelProfile(
        provider=Provider.OLLAMA,
        model_name="remote-ollama",
        base_url="https://ollama.example.com",
    )
    with pytest.raises(ModelGatewayError, match="本地模式"):
        create_model_gateway(public_ollama, local_mode=True)


def test_upstream_validation_error_keeps_short_message_without_request_data() -> None:
    async def transport(url: str, **kwargs: Any):
        del url, kwargs
        return (
            400,
            {},
            {"error": {"message": "unsupported image url", "request": "sensitive prompt"}},
        )

    profile = ModelProfile(
        provider=Provider.OPENAI_COMPATIBLE,
        model_name="vision-model",
        base_url="https://models.example/v1",
        capabilities=frozenset({ModelCapability.VISION}),
    )
    gateway = create_model_gateway(profile, transport=transport)

    with pytest.raises(ModelGatewayError, match="HTTP 400：unsupported image url") as error:
        asyncio.run(
            gateway.complete_vision_json(
                prompt="private document",
                image_bytes=b"image",
                media_type="image/png",
            )
        )

    assert "private document" not in str(error.value)


def test_openai_compatible_embedding_orders_vectors_and_uses_declared_endpoint() -> None:
    captured: dict[str, Any] = {}

    async def transport(url: str, **kwargs: Any):
        captured["url"] = url
        captured.update(kwargs)
        return (
            200,
            {},
            {
                "data": [
                    {"index": 1, "embedding": [0, 1]},
                    {"index": 0, "embedding": [1, 0]},
                ]
            },
        )

    profile = ModelProfile(
        provider=Provider.OPENAI_COMPATIBLE,
        model_name="embedding-model",
        base_url="https://models.example/v1",
        api_key="secret",
        capabilities=frozenset({ModelCapability.EMBEDDING}),
    )
    gateway = create_model_gateway(profile, transport=transport)
    vectors = asyncio.run(gateway.embed_texts(["甲", "乙"]))

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert captured["url"] == "https://models.example/v1/embeddings"
    assert captured["payload"] == {"model": "embedding-model", "input": ["甲", "乙"]}
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_kimi_uses_fixed_temperature_and_omits_seed() -> None:
    captured: dict[str, Any] = {}

    async def transport(url: str, **kwargs: Any):
        captured["url"] = url
        captured.update(kwargs)
        return (
            200,
            {},
            {
                "model": "k3",
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {},
            },
        )

    profile = ModelProfile(
        provider=Provider.OPENAI_COMPATIBLE,
        model_name="k3",
        base_url="https://api.kimi.com/coding/v1",
        api_key="secret",
    )
    gateway = create_model_gateway(profile, transport=transport)
    response = asyncio.run(
        gateway.complete_json(
            [{"role": "user", "content": "返回 JSON"}],
            temperature=0.1,
            seed=42,
        )
    )

    assert response.data == {"ok": True}
    assert captured["payload"]["temperature"] == 1.0
    assert captured["payload"]["max_tokens"] == 16_384
    assert captured["payload"]["reasoning_effort"] == "low"
    assert "seed" not in captured["payload"]


def test_kimi_k3_vision_uses_openai_image_payload() -> None:
    captured: dict[str, Any] = {}

    async def transport(url: str, **kwargs: Any):
        captured["url"] = url
        captured.update(kwargs)
        return (
            200,
            {},
            {
                "model": "k3-256k",
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {},
            },
        )

    profile = ModelProfile(
        provider=Provider.OPENAI_COMPATIBLE,
        model_name="k3-256k",
        base_url="https://api.kimi.com/coding/v1",
        api_key="secret",
        capabilities=frozenset(
            {ModelCapability.STRUCTURED_OUTPUT, ModelCapability.VISION}
        ),
    )
    gateway = create_model_gateway(profile, transport=transport)
    response = asyncio.run(
        gateway.complete_vision_json(
            prompt="只返回 JSON",
            image_bytes=b"image",
            media_type="image/png",
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
            seed=42,
        )
    )

    content = captured["payload"]["messages"][0]["content"]
    assert response.data == {"ok": True}
    assert captured["url"] == "https://api.kimi.com/coding/v1/chat/completions"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,aW1hZ2U="
    assert captured["payload"]["temperature"] == 1.0
    assert captured["payload"]["max_tokens"] == 16_384
    assert captured["payload"]["reasoning_effort"] == "low"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in content[0]["text"]
    assert "seed" not in captured["payload"]


def test_other_openai_compatible_provider_keeps_sampling_parameters() -> None:
    captured: dict[str, Any] = {}

    async def transport(url: str, **kwargs: Any):
        captured.update(kwargs)
        return (
            200,
            {},
            {"choices": [{"message": {"content": '{"ok":true}'}}]},
        )

    profile = ModelProfile(
        provider=Provider.OPENAI_COMPATIBLE,
        model_name="custom-model",
        base_url="https://models.example/v1",
    )
    gateway = create_model_gateway(profile, transport=transport)
    asyncio.run(
        gateway.complete_json(
            [{"role": "user", "content": "返回 JSON"}],
            temperature=0.25,
            seed=7,
        )
    )

    assert captured["payload"]["temperature"] == 0.25
    assert captured["payload"]["seed"] == 7


def test_ollama_vision_sends_inline_image_without_cloud_fallback() -> None:
    captured: dict[str, Any] = {}

    async def transport(url: str, **kwargs: Any):
        captured["url"] = url
        captured.update(kwargs)
        return (
            200,
            {},
            {
                "message": {
                    "content": (
                        '{"description":"流程图","key_facts":["先鉴别后授权"],'
                        '"question_worthy":true}'
                    )
                }
            },
        )

    profile = ModelProfile(
        provider=Provider.OLLAMA,
        model_name="qwen-vision",
        base_url="http://ollama:11434",
        capabilities=frozenset({ModelCapability.VISION}),
    )
    gateway = create_model_gateway(profile, local_mode=True, transport=transport)
    response = asyncio.run(
        gateway.complete_vision_json(
            prompt="描述图片",
            image_bytes=b"image",
            media_type="image/png",
            seed=42,
        )
    )

    assert response.data["question_worthy"] is True
    assert captured["url"] == "http://ollama:11434/api/chat"
    assert captured["payload"]["messages"][0]["images"] == ["aW1hZ2U="]


def test_embedding_batches_and_vector_ranking() -> None:
    calls: list[list[str]] = []

    def handler(values: list[str], **kwargs: Any) -> list[list[float]]:
        assert kwargs["operation"] == "embedding"
        calls.append(values)
        return [[float(len(value)), 1.0] for value in values]

    vectors = asyncio.run(
        embed_batches(CallableGateway(handler), ["a", "bb", "ccc"], batch_size=2)
    )

    assert calls == [["a", "bb"], ["ccc"]]
    assert vectors == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert ranked_indices([1, 0], vectors, limit=2) == [2, 1]
