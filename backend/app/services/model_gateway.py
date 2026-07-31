"""OpenAI 兼容接口与 Ollama 的统一模型网关。

本模块不依赖 OpenAI SDK，也不会实现云端自动回退。网络传输可注入，因此工作流测试
可以完全离线运行。API Key 被标记为不可 ``repr``，异常与日志中也不会输出请求头。
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import random
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse


class ModelGatewayError(RuntimeError):
    """模型调用失败，消息中不含密钥或完整提示词。"""


class ModelResponseError(ModelGatewayError):
    """模型响应不是期望的结构化 JSON。"""


class Provider(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA = "ollama"


class ModelCapability(StrEnum):
    CHAT = "chat"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    EMBEDDING = "embedding"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelProfile:
    provider: Provider
    model_name: str
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    capabilities: frozenset[ModelCapability] = frozenset(
        {ModelCapability.CHAT, ModelCapability.STRUCTURED_OUTPUT}
    )
    timeout_seconds: float = 120.0
    max_retries: int = 2
    local: bool | None = None

    @classmethod
    def from_value(cls, value: ModelProfile | Mapping[str, Any] | Any) -> ModelProfile:
        if isinstance(value, cls):
            return value

        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(value, Mapping) and name in value:
                    return value[name]
                if hasattr(value, name):
                    return getattr(value, name)
            return default

        provider_value = str(read("provider", "provider_type", default="openai_compatible")).lower()
        if provider_value in {"openai", "openai-compatible", "openai_compatible", "custom"}:
            provider = Provider.OPENAI_COMPATIBLE
        elif provider_value == "ollama":
            provider = Provider.OLLAMA
        else:
            raise ValueError(f"不支持的模型接口类型：{provider_value}")
        raw_capabilities = read("capabilities", default=None)
        if raw_capabilities:
            capabilities = frozenset(ModelCapability(str(item)) for item in raw_capabilities)
        else:
            capabilities = frozenset({ModelCapability.CHAT, ModelCapability.STRUCTURED_OUTPUT})
        return cls(
            provider=provider,
            model_name=str(read("model_name", "model", default="")).strip(),
            base_url=str(read("base_url", default="")).strip(),
            api_key=read("api_key", "secret", default=None),
            capabilities=capabilities,
            timeout_seconds=float(read("timeout_seconds", "timeout", default=120)),
            max_retries=int(read("max_retries", default=2)),
            local=read("local", "is_local", default=None),
        )


@dataclass(frozen=True, slots=True)
class GatewayResponse:
    data: Any
    raw_text: str
    model: str
    usage: Mapping[str, int] = field(default_factory=dict)


class JSONTransport(Protocol):
    async def __call__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> tuple[int, Mapping[str, str], Any]: ...


async def _httpx_transport(
    url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float,
) -> tuple[int, Mapping[str, str], Any]:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - production dependency
        raise ModelGatewayError("模型网络调用需要安装 httpx") from exc
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=dict(headers), json=dict(payload))
    try:
        body: Any = response.json()
    except ValueError:
        body = {"message": response.text[:500]}
    return response.status_code, response.headers, body


def _messages_payload(messages: Sequence[ChatMessage | Mapping[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, ChatMessage):
            role, content = message.role, message.content
        else:
            role, content = str(message["role"]), str(message["content"])
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"不支持的消息角色：{role}")
        result.append({"role": role, "content": content})
    if not result:
        raise ValueError("消息列表不能为空")
    return result


def _upstream_error_detail(body: Any) -> str:
    """提取不超过 180 字的上游错误说明，不包含请求头或请求正文。"""

    value: Any = None
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            value = error.get("message") or error.get("type") or error.get("code")
        elif isinstance(error, str):
            value = error
        value = value or body.get("message") or body.get("detail")
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:180]


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json_value(text: str) -> Any:
    """从纯 JSON 或常见 Markdown 代码围栏中安全提取一个 JSON 值。"""

    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
            return value
        except json.JSONDecodeError:
            continue
    raise ModelResponseError("模型未返回有效 JSON")


def _is_local_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host in {"localhost", "host.docker.internal", "ollama", "::1"}:
        return True
    if host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _is_kimi_api(profile: ModelProfile) -> bool:
    host = (urlparse(profile.base_url).hostname or "").casefold()
    return host in {
        "api.kimi.com",
        "api.moonshot.cn",
        "api.moonshot.ai",
    }


def _kimi_temperature(model_name: str) -> float:
    return 0.6 if "k2.6" in model_name.casefold() else 1.0


def _apply_kimi_runtime_tuning(payload: dict[str, Any], profile: ModelProfile) -> None:
    """为 Kimi 长任务设置可控的思考与输出预算。"""

    if not _is_kimi_api(profile):
        return
    payload["temperature"] = _kimi_temperature(profile.model_name)
    payload["max_tokens"] = 16_384
    if profile.model_name.casefold().startswith("k3"):
        # K3 未指定时默认高思考；蓝图、出题和审题均是受 JSON Schema
        # 约束的事实任务，low 能显著降低首字延迟且仍保留推理能力。
        payload["reasoning_effort"] = "low"


def ensure_local_profile(profile: ModelProfile) -> None:
    """本地执行模式的硬性边界；不会把失败请求转发到云端。"""

    if profile.local is True or _is_local_url(profile.base_url):
        return
    raise ModelGatewayError("本地模式禁止使用非本地模型地址")


class BaseModelGateway(ABC):
    profile: ModelProfile

    @abstractmethod
    async def complete_json(
        self,
        messages: Sequence[ChatMessage | Mapping[str, str]],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> GatewayResponse:
        """请求一个 JSON 响应。"""

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise ModelGatewayError("当前模型配置不支持 Embedding")

    async def complete_vision_json(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        media_type: str,
        schema: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> GatewayResponse:
        raise ModelGatewayError("当前模型配置不支持图片输入")


class _HTTPGateway(BaseModelGateway):
    def __init__(self, profile: ModelProfile, transport: JSONTransport | None = None) -> None:
        if not profile.model_name:
            raise ValueError("模型名不能为空")
        if not profile.base_url:
            raise ValueError("Base URL 不能为空")
        self.profile = profile
        self._transport: JSONTransport = transport or _httpx_transport

    async def _post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> Any:
        last_error: Exception | None = None
        attempts = max(1, self.profile.max_retries + 1)
        for attempt in range(attempts):
            try:
                status, response_headers, body = await self._transport(
                    url,
                    headers=headers,
                    payload=payload,
                    timeout=self.profile.timeout_seconds,
                )
                if 200 <= status < 300:
                    return body
                if status not in {408, 409, 425, 429, 500, 502, 503, 504}:
                    detail = _upstream_error_detail(body)
                    suffix = f"：{detail}" if detail else ""
                    raise ModelGatewayError(f"模型接口返回 HTTP {status}{suffix}")
                retry_after = response_headers.get("retry-after") or response_headers.get(
                    "Retry-After"
                )
                delay = (
                    min(10.0, float(retry_after)) if retry_after else min(4.0, 0.5 * (2**attempt))
                )
                last_error = ModelGatewayError(f"模型接口暂时不可用（HTTP {status}）")
            except ModelGatewayError:
                raise
            except Exception as exc:  # transport errors are intentionally sanitized
                last_error = ModelGatewayError(f"无法连接模型接口：{type(exc).__name__}")
                delay = min(4.0, 0.5 * (2**attempt))
            if attempt + 1 < attempts:
                await asyncio.sleep(delay + random.random() * 0.1)
        raise last_error or ModelGatewayError("模型调用失败")


class OpenAICompatibleGateway(_HTTPGateway):
    """调用 OpenAI Chat Completions 兼容接口。"""

    def _endpoint(self) -> str:
        base = self.profile.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/chat/completions"

    async def complete_json(
        self,
        messages: Sequence[ChatMessage | Mapping[str, str]],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> GatewayResponse:
        payload: dict[str, Any] = {
            "model": self.profile.model_name,
            "messages": _messages_payload(messages),
        }
        if _is_kimi_api(self.profile):
            # Kimi 新模型只接受各自固定采样温度；官方请求参数也未声明 seed。
            _apply_kimi_runtime_tuning(payload, self.profile)
        else:
            payload["temperature"] = temperature
        if seed is not None and not _is_kimi_api(self.profile):
            payload["seed"] = seed
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_response", "strict": True, "schema": schema},
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.profile.api_key:
            headers["Authorization"] = f"Bearer {self.profile.api_key}"
        body = await self._post(self._endpoint(), headers, payload)
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) for item in content if isinstance(item, Mapping)
                )
            raw_text = str(content)
            usage = body.get("usage") or {}
            model = str(body.get("model") or self.profile.model_name)
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError("OpenAI 兼容接口响应结构不正确") from exc
        return GatewayResponse(extract_json_value(raw_text), raw_text, model, usage)

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if ModelCapability.EMBEDDING not in self.profile.capabilities:
            raise ModelGatewayError("模型配置未声明 Embedding 能力")
        base = self.profile.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base.removesuffix("/chat/completions")
        if not base.endswith("/v1"):
            base += "/v1"
        headers = {"Content-Type": "application/json"}
        if self.profile.api_key:
            headers["Authorization"] = f"Bearer {self.profile.api_key}"
        body = await self._post(
            base + "/embeddings",
            headers,
            {"model": self.profile.model_name, "input": list(texts)},
        )
        try:
            ordered = sorted(body["data"], key=lambda item: int(item.get("index", 0)))
            return [[float(value) for value in item["embedding"]] for item in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelResponseError("OpenAI 兼容 Embedding 响应结构不正确") from exc

    async def complete_vision_json(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        media_type: str,
        schema: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> GatewayResponse:
        if ModelCapability.VISION not in self.profile.capabilities:
            raise ModelGatewayError("模型配置未声明视觉能力")
        visual_prompt = prompt
        if schema is not None and _is_kimi_api(self.profile):
            visual_prompt = (
                f"{prompt}\n\n必须只返回符合以下 JSON Schema 的 JSON 对象：\n"
                f"{json.dumps(dict(schema), ensure_ascii=False)}"
            )
        payload: dict[str, Any] = {
            "model": self.profile.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": visual_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{media_type};base64,"
                                    f"{base64.b64encode(image_bytes).decode('ascii')}"
                                )
                            },
                        },
                    ],
                }
            ],
        }
        if _is_kimi_api(self.profile):
            # Kimi 视觉接口明确支持 JSON Mode；严格 JSON Schema 与图片组合
            # 在 K3 Coding 端点会返回 400，因此结构约束同时写入提示词。
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "visual_analysis",
                    "strict": True,
                    "schema": dict(schema or {"type": "object"}),
                },
            }
        payload["temperature"] = (
            _kimi_temperature(self.profile.model_name)
            if _is_kimi_api(self.profile)
            else 0
        )
        if _is_kimi_api(self.profile):
            _apply_kimi_runtime_tuning(payload, self.profile)
        if seed is not None and not _is_kimi_api(self.profile):
            payload["seed"] = seed
        headers = {"Content-Type": "application/json"}
        if self.profile.api_key:
            headers["Authorization"] = f"Bearer {self.profile.api_key}"
        body = await self._post(self._endpoint(), headers, payload)
        try:
            content = body["choices"][0]["message"]["content"]
            raw_text = str(content)
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError("视觉模型响应结构不正确") from exc
        return GatewayResponse(
            extract_json_value(raw_text),
            raw_text,
            str(body.get("model") or self.profile.model_name),
            body.get("usage") or {},
        )


class OllamaGateway(_HTTPGateway):
    """调用 Ollama 原生 ``/api/chat`` 接口。"""

    def _endpoint(self) -> str:
        base = self.profile.base_url.rstrip("/")
        if base.endswith("/api/chat"):
            return base
        if base.endswith("/api"):
            return base + "/chat"
        return base + "/api/chat"

    async def complete_json(
        self,
        messages: Sequence[ChatMessage | Mapping[str, str]],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> GatewayResponse:
        options: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed
        payload: dict[str, Any] = {
            "model": self.profile.model_name,
            "messages": _messages_payload(messages),
            "stream": False,
            "format": dict(schema) if schema else "json",
            "options": options,
        }
        body = await self._post(self._endpoint(), {"Content-Type": "application/json"}, payload)
        try:
            raw_text = str(body["message"]["content"])
            usage = {
                "prompt_tokens": int(body.get("prompt_eval_count") or 0),
                "completion_tokens": int(body.get("eval_count") or 0),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelResponseError("Ollama 响应结构不正确") from exc
        return GatewayResponse(
            extract_json_value(raw_text), raw_text, self.profile.model_name, usage
        )

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if ModelCapability.EMBEDDING not in self.profile.capabilities:
            raise ModelGatewayError("模型配置未声明 Embedding 能力")
        base = self.profile.base_url.rstrip("/")
        if base.endswith("/api/chat"):
            base = base.removesuffix("/api/chat")
        elif base.endswith("/api"):
            base = base.removesuffix("/api")
        body = await self._post(
            base + "/api/embed",
            {"Content-Type": "application/json"},
            {"model": self.profile.model_name, "input": list(texts)},
        )
        try:
            return [[float(value) for value in item] for item in body["embeddings"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelResponseError("Ollama Embedding 响应结构不正确") from exc

    async def complete_vision_json(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        media_type: str,
        schema: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> GatewayResponse:
        del media_type
        if ModelCapability.VISION not in self.profile.capabilities:
            raise ModelGatewayError("模型配置未声明视觉能力")
        options: dict[str, Any] = {"temperature": 0}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": self.profile.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(image_bytes).decode("ascii")],
                }
            ],
            "stream": False,
            "format": dict(schema or {"type": "object"}),
            "options": options,
        }
        body = await self._post(
            self._endpoint(), {"Content-Type": "application/json"}, payload
        )
        try:
            raw_text = str(body["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise ModelResponseError("Ollama 视觉模型响应结构不正确") from exc
        return GatewayResponse(
            extract_json_value(raw_text), raw_text, self.profile.model_name, {}
        )


class CallableGateway(BaseModelGateway):
    """测试或自定义部署使用的可注入网关。"""

    def __init__(
        self,
        handler: Callable[..., Any | Awaitable[Any]],
        *,
        model_name: str = "callable",
    ) -> None:
        self._handler = handler
        self.profile = ModelProfile(Provider.OLLAMA, model_name, "http://localhost")

    async def complete_json(
        self,
        messages: Sequence[ChatMessage | Mapping[str, str]],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> GatewayResponse:
        result = self._handler(messages, schema=schema, temperature=temperature, seed=seed)
        if asyncio.iscoroutine(result):
            result = await result
        raw_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        data = extract_json_value(result) if isinstance(result, str) else result
        return GatewayResponse(data, raw_text, self.profile.model_name)

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        result = self._handler(texts, operation="embedding")
        if asyncio.iscoroutine(result):
            result = await result
        return [[float(value) for value in item] for item in result]

    async def complete_vision_json(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        media_type: str,
        schema: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> GatewayResponse:
        result = self._handler(
            [ChatMessage("user", prompt)],
            schema=schema,
            temperature=0,
            seed=seed,
            image_bytes=image_bytes,
            media_type=media_type,
        )
        if asyncio.iscoroutine(result):
            result = await result
        raw_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        data = extract_json_value(result) if isinstance(result, str) else result
        return GatewayResponse(data, raw_text, self.profile.model_name)


def create_model_gateway(
    profile: ModelProfile | Mapping[str, Any] | Any,
    *,
    local_mode: bool = False,
    transport: JSONTransport | None = None,
) -> BaseModelGateway:
    """按配置创建唯一网关；此函数刻意没有 fallback 参数。"""

    resolved = ModelProfile.from_value(profile)
    if local_mode:
        ensure_local_profile(resolved)
    if resolved.provider is Provider.OLLAMA:
        return OllamaGateway(resolved, transport)
    return OpenAICompatibleGateway(resolved, transport)
