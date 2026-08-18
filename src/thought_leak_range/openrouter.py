from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class BudgetExceeded(RuntimeError):
    pass


class OpenRouterFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StreamResult:
    response_id: str | None
    reported_model: str | None
    provider: str | None
    reasoning_types: tuple[str, ...]
    raw_reasoning_chars: int
    visible_chars: int
    first_byte_ms: float | None
    first_reasoning_ms: float | None
    first_visible_ms: float | None
    total_ms: float
    usage: dict[str, Any]

    @property
    def has_raw_reasoning(self) -> bool:
        return "reasoning.text" in self.reasoning_types and self.raw_reasoning_chars > 0


class CostBudget:
    """Conservative preflight budget plus provider-reported accounting."""

    def __init__(
        self,
        *,
        maximum_usd: float,
        maximum_requests: int,
        input_price_per_million: float = 0.44,
        output_price_per_million: float = 1.32,
    ) -> None:
        if maximum_usd <= 0 or maximum_requests <= 0:
            raise ValueError("budget and request limit must be positive")
        self.maximum_usd = maximum_usd
        self.maximum_requests = maximum_requests
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.reserved_usd = 0.0
        self.reported_usd = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.requests = 0
        self._lock = threading.Lock()

    def reserve(self, messages: list[dict[str, str]], *, max_tokens: int) -> float:
        # CJK and JSON can tokenize densely. Two chars/token is intentionally cautious.
        chars = sum(len(message.get("content", "")) for message in messages)
        estimated_input_tokens = max(1, math.ceil(chars / 2) + len(messages) * 16)
        estimate = (
            estimated_input_tokens * self.input_price_per_million
            + max_tokens * self.output_price_per_million
        ) / 1_000_000
        with self._lock:
            if self.requests >= self.maximum_requests:
                raise BudgetExceeded(
                    f"request guard stopped the run at {self.maximum_requests} requests"
                )
            accounted = max(self.reserved_usd, self.reported_usd)
            if accounted + estimate > self.maximum_usd + 1e-12:
                raise BudgetExceeded(
                    "cost guard stopped the run: "
                    f"accounted=${accounted:.6f}, "
                    f"next_estimate=${estimate:.6f}, "
                    f"limit=${self.maximum_usd:.6f}"
                )
            self.requests += 1
            self.reserved_usd = accounted + estimate
        return estimate

    def record(self, usage: Mapping[str, Any]) -> None:
        with self._lock:
            self.prompt_tokens += _integer_or_zero(
                usage.get("prompt_tokens", usage.get("input_tokens"))
            )
            self.completion_tokens += _integer_or_zero(
                usage.get("completion_tokens", usage.get("output_tokens"))
            )
            cost = _finite_float(usage.get("cost"))
            if cost is not None and cost >= 0:
                self.reported_usd += cost

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "requests": self.requests,
                "maximum_requests": self.maximum_requests,
                "estimated_reserved_usd": self.reserved_usd,
                "reported_cost_usd": self.reported_usd,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "maximum_usd": self.maximum_usd,
            }


ReasoningCallback = Callable[[str, float], None]
VisibleCallback = Callable[[str, float], None]


class OpenRouterReasoningClient:
    def __init__(
        self,
        *,
        api_key: str,
        budget: CostBudget,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        reasoning_effort: str = "high",
        max_tokens: int = 128,
        timeout_seconds: float = 45.0,
        provider_sort: str = "latency",
        provider_order: tuple[str, ...] = (),
        provider_allow_fallbacks: bool = True,
        preferred_max_latency_seconds: float | None = 0.2,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenRouter API key is empty")
        if reasoning_effort not in {
            "max",
            "xhigh",
            "high",
            "medium",
            "low",
            "minimal",
            "none",
        }:
            raise ValueError("unsupported reasoning effort")
        if not 16 <= max_tokens <= 512:
            raise ValueError("max_tokens must be between 16 and 512")
        if provider_sort not in {"latency", "throughput", "price"}:
            raise ValueError("provider sort must be latency, throughput, or price")
        if preferred_max_latency_seconds is not None and preferred_max_latency_seconds <= 0:
            raise ValueError("preferred provider latency must be positive")
        self._api_key = api_key.strip()
        self.budget = budget
        self.model = model
        self.endpoint = endpoint
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.provider_sort = provider_sort
        self.provider_order = provider_order
        self.provider_allow_fallbacks = provider_allow_fallbacks
        self.preferred_max_latency_seconds = preferred_max_latency_seconds
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                connect=10.0,
                read=timeout_seconds,
                write=15.0,
                pool=10.0,
            ),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "X-Title": "Thought Leak Range",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def warmup(self) -> float:
        """Establish TLS/HTTP2 before the latency-measured model request."""

        started = time.monotonic()
        try:
            response = await self._client.get("https://openrouter.ai/api/v1/auth/key")
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as error:
            raise OpenRouterFailure(
                self._redact(f"OpenRouter warmup failed: {error}")
            ) from error
        return (time.monotonic() - started) * 1000.0

    async def stream(
        self,
        *,
        messages: list[dict[str, str]],
        on_reasoning: ReasoningCallback,
        on_visible: VisibleCallback | None = None,
        stop: list[str] | None = None,
        temperature: float | None = None,
        reasoning_enabled: bool = True,
    ) -> StreamResult:
        self.budget.reserve(messages, max_tokens=self.max_tokens)
        provider: dict[str, Any] = {
            "data_collection": "deny",
            "sort": self.provider_sort,
            "allow_fallbacks": self.provider_allow_fallbacks,
        }
        if self.provider_order:
            provider["order"] = list(self.provider_order)
        if self.preferred_max_latency_seconds is not None:
            provider["preferred_max_latency"] = {
                "p50": self.preferred_max_latency_seconds
            }

        reasoning: dict[str, Any] = {
            "enabled": reasoning_enabled,
            "exclude": not reasoning_enabled,
        }
        if reasoning_enabled:
            reasoning["effort"] = self.reasoning_effort

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "reasoning": reasoning,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "provider": provider,
        }
        if stop:
            payload["stop"] = stop
        if temperature is not None:
            payload["temperature"] = temperature

        started = time.monotonic()
        first_byte_at: float | None = None
        first_reasoning_at: float | None = None
        first_visible_at: float | None = None
        reasoning_types: set[str] = set()
        reasoning_chars = 0
        visible_chars = 0
        response_id: str | None = None
        reported_model: str | None = None
        provider: str | None = None
        usage: dict[str, Any] = {}

        try:
            async with self._client.stream(
                "POST", self.endpoint, json=payload
            ) as response:
                if response.status_code >= 400:
                    error_bytes = await response.aread()
                    detail = error_bytes.decode("utf-8", errors="replace")
                    raise OpenRouterFailure(
                        self._redact(
                            f"OpenRouter HTTP {response.status_code}: "
                            f"{_safe_error_detail(detail)}"
                        )
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    arrived_at = time.monotonic()
                    if first_byte_at is None:
                        first_byte_at = arrived_at
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue

                    stream_error = chunk.get("error")
                    if stream_error is not None:
                        if isinstance(stream_error, dict):
                            message = _optional_text(stream_error.get("message"))
                            code = stream_error.get("code")
                            detail = f"code={code} message={message or stream_error}"
                        else:
                            detail = str(stream_error)
                        raise OpenRouterFailure(
                            self._redact(
                                "OpenRouter stream returned an error: "
                                f"{' '.join(detail.split())[:1200]}"
                            )
                        )

                    response_id = _optional_text(chunk.get("id")) or response_id
                    reported_model = (
                        _optional_text(chunk.get("model")) or reported_model
                    )
                    provider = _optional_text(chunk.get("provider")) or provider
                    chunk_usage = chunk.get("usage")
                    if isinstance(chunk_usage, dict):
                        usage = dict(chunk_usage)

                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue

                    details = delta.get("reasoning_details")
                    if isinstance(details, list):
                        for detail in details:
                            if not isinstance(detail, dict):
                                continue
                            detail_type = _optional_text(detail.get("type"))
                            if detail_type:
                                reasoning_types.add(detail_type)
                            if detail_type != "reasoning.text":
                                continue
                            text = detail.get("text")
                            if not isinstance(text, str) or not text:
                                continue
                            if first_reasoning_at is None:
                                first_reasoning_at = arrived_at
                            reasoning_chars += len(text)
                            on_reasoning(text, arrived_at)

                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        if first_visible_at is None:
                            first_visible_at = arrived_at
                        visible_chars += len(content)
                        if on_visible is not None:
                            on_visible(content, arrived_at)
        except (httpx.HTTPError, OSError) as error:
            raise OpenRouterFailure(
                self._redact(f"OpenRouter stream failed: {error}")
            ) from error

        self.budget.record(usage)
        finished = time.monotonic()
        return StreamResult(
            response_id=response_id,
            reported_model=reported_model,
            provider=provider,
            reasoning_types=tuple(sorted(reasoning_types)),
            raw_reasoning_chars=reasoning_chars,
            visible_chars=visible_chars,
            first_byte_ms=_elapsed_ms(started, first_byte_at),
            first_reasoning_ms=_elapsed_ms(started, first_reasoning_at),
            first_visible_ms=_elapsed_ms(started, first_visible_at),
            total_ms=(finished - started) * 1000.0,
            usage=usage,
        )

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "<redacted>")


def _safe_error_detail(body: str) -> str:
    """Keep useful routing diagnostics without echoing account metadata."""

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return f"non-JSON response body omitted ({len(body)} chars)"
    if not isinstance(decoded, dict):
        return "unexpected error response omitted"
    error = decoded.get("error")
    if not isinstance(error, dict):
        return "error details omitted"

    parts: list[str] = []
    code = error.get("code")
    if isinstance(code, (str, int)) and not isinstance(code, bool):
        parts.append(f"code={code}")
    message = _optional_text(error.get("message"))
    if message:
        parts.append(f"message={message[:300]}")

    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        provider_name = _optional_text(metadata.get("provider_name"))
        if provider_name:
            parts.append(f"provider={provider_name[:100]}")
        limit_source = _optional_text(metadata.get("limit_source"))
        if limit_source:
            parts.append(f"limit_source={limit_source[:100]}")
        previous = metadata.get("previous_errors")
        if isinstance(previous, list):
            providers = {
                name
                for item in previous
                if isinstance(item, dict)
                for name in [_optional_text(item.get("provider_name"))]
                if name
            }
            if providers:
                parts.append(f"previous_providers={','.join(sorted(providers))[:300]}")
    return " ".join(parts) if parts else "error details omitted"


def load_api_key(*, env_file: Path | None = None) -> str:
    process_value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if process_value:
        return process_value
    if env_file is None:
        raise ValueError(
            "OPENROUTER_API_KEY is absent; set it or pass --env-file"
        )
    if not env_file.is_file():
        raise ValueError(f"env file does not exist: {env_file}")

    pattern = re.compile(
        r"^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$"
    )
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if value:
            return value
    raise ValueError(f"OPENROUTER_API_KEY is absent from env file: {env_file}")


def _integer_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    number = _finite_float(value)
    return max(0, int(number)) if number is not None else 0


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _elapsed_ms(started: float, event_at: float | None) -> float | None:
    return None if event_at is None else (event_at - started) * 1000.0
