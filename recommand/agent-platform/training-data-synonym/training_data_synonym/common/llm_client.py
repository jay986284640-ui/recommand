"""LLM client abstraction + Mock + OpenAI-compatible HTTP implementation.

Per research.md D-012 — retry 2x with exponential backoff; fail → record
failure, continue main flow.

The :class:`OpenAICompatClient` performs a `POST {base_url}/chat/completions`
call against any OpenAI-compatible endpoint (OpenAI, Anthropic-compatible
gateways, vLLM, TGI, DeepSeek, etc.). It is selected via
:func:`build_llm_client` when `provider == "openai_compat"`. The `httpx`
dependency is lazy — installed only via `pip install -e .[llm]`.
"""

from __future__ import annotations

import json
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import ValidationError
from .logging import get_logger

logger = get_logger(__name__)


class LLMTimeoutError(Exception):
    """LLM call exceeded timeout."""


class LLMClient(ABC):
    """Abstract LLM client. All subclasses MUST implement `complete(prompt)`.

    Subclasses MUST also expose :attr:`model_name` (str) — used to drop the
    historical hard-coded `"mock-llm"` strings from pipeline outputs.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the underlying model (used as `llm_model` in outputs)."""
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        item_id: str = "",
    ) -> dict[str, Any]:
        """Return parsed JSON dict. Raise LLMTimeoutError on timeout.

        Implementations should retry transient failures per research.md D-012
        and emit one structured log line per call (T097) when the underlying
        transport exposes latency / token accounting. The `item_id` kwarg is
        propagated from the calling pipeline solely for that log line —
        subclasses may safely ignore it (e.g. :class:`MockLLMClient`).
        """
        raise NotImplementedError


# --- Mock implementation (deterministic, no network) ---------------------


class MockLLMClient(LLMClient):
    """Deterministic mock for CI / dev. Returns heuristic JSON from prompt.

    Behavior:
      - If prompt contains {"intent": "..."} (Stage 2 ground-truth injection),
        echo a structured 1-3 turn dialogue back with that intent and
        a {param} -> natural language paraphrase using dictionary values.
      - If prompt contains `原始信息:` (Stage 1), echo back 6 dims based on
        the raw record's category / merchant fields if present, else nulls.
      - Always returns valid JSON; never times out.
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        # 1 in 50 chance to inject a JSON-decode failure to exercise retries.
        self._inject_failure_every = 50
        self._call_count = 0

    @property
    def model_name(self) -> str:
        return "mock-llm"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=0.1, max=1.0),
        retry=retry_if_exception_type((LLMTimeoutError, json.JSONDecodeError)),
        reraise=True,
    )
    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        item_id: str = "",
    ) -> dict[str, Any]:
        self._call_count += 1
        if self._call_count % self._inject_failure_every == 0:
            # Inject transient failure once every N calls.
            raise LLMTimeoutError(f"injected failure at call #{self._call_count}")

        if "目标:" in prompt or "intent:" in prompt:
            return self._mock_sft_dialogue(prompt)
        if "原始信息:" in prompt or "你是一个 O2O 推荐系统的标签补全助手" in prompt:
            return self._mock_enrichment(prompt)
        # Fallback for tests: still produce a structured dialogue so
        # downstream validation does not crash.
        return self._mock_sft_dialogue(prompt)

    # ---- heuristics -----------------------------------------------------

    def _mock_enrichment(self, prompt: str) -> dict[str, Any]:
        """Echo 6-dim JSON from raw record snippet."""
        raw = {}
        # crude extraction of "raw_record" or "原始信息:" block
        try:
            if "原始信息:" in prompt:
                block = prompt.split("原始信息:")[1].strip()
                if block.startswith("{"):
                    raw = json.loads(block)
            elif "raw_record" in prompt:
                block = prompt[prompt.index("raw_record") :]
                # find first {...}
                start = block.index("{")
                end = block.index("}", start) + 1
                raw = json.loads(block[start:end])
        except (json.JSONDecodeError, ValueError):
            raw = {}

        cat = raw.get("Cat_Nm") or raw.get("couponName")
        merch = raw.get("Brnd_Nm") or raw.get("Str_Nm")
        avg = raw.get("Avg_Prc")

        return {
            "category": cat if cat else "咖啡",
            "merchant": merch if merch else None,
            "avg_prc": self._bucket_price(avg) if avg else None,
            "age": "25-35" if self._rng.random() > 0.5 else None,
            "occasion": self._rng.choice(["下午茶", "午餐", None]),
            "taste": self._rng.choice([["甜"], ["咸"], None]),
        }

    def _mock_sft_dialogue(self, prompt: str) -> dict[str, Any]:
        """Echo 1-3 turn dialogue + covered_dims."""
        # crude ground-truth parse
        intent_match = "search_item"
        order_by = None
        covered: list[str] = []

        if "intent: search_item" in prompt:
            intent_match = "search_item"
        elif "intent: use_coupon" in prompt:
            intent_match = "use_coupon"
        elif "intent: pay" in prompt:
            intent_match = "pay"

        if "order_by: distance" in prompt:
            order_by = "distance"
            covered.append("distance")
        if "category" in prompt:
            covered.append("category")
        if "consumable_type" in prompt:
            covered.append("consumable_type")

        n_turns = self._rng.choice([2, 3, 3, 3, 4])
        messages = [
            {"role": "user", "content": f"想看附近有什么推荐({intent_match})"},
            {"role": "assistant", "content": "可以告诉我具体想喝 / 想吃 / 价位吗?"},
        ]
        if n_turns >= 3:
            messages.append({"role": "user", "content": f"{order_by or '随便'},想喝点东西"})
            covered.append("consumable_type")
        if n_turns >= 4:
            messages.append({"role": "assistant", "content": "好的,为您筛选以下门店..."})

        return {"messages": messages, "covered_dims": covered}

    @staticmethod
    def _bucket_price(avg_unc: Any) -> str | None:
        try:
            avg = float(avg_unc)
        except (TypeError, ValueError):
            return None
        if avg <= 30:
            return "0-30"
        if avg <= 50:
            return "30-50"
        if avg <= 100:
            return "50-100"
        if avg <= 200:
            return "100-200"
        return "200+"


# --- OpenAI-compatible HTTP implementation -------------------------------


class OpenAICompatError(Exception):
    """Base for OpenAI-compatible transport errors."""


class OpenAICompatTransientError(OpenAICompatError):
    """Retryable transport failure: 5xx, 408, 429, network timeout."""


class OpenAICompatValidationError(OpenAICompatError):
    """Non-retryable: 4xx (other than 408/429), malformed body, bad JSON."""


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _extract_json(text: str) -> dict[str, Any]:
    """Strip ```json ... ``` fences (if any) and parse as JSON dict.

    Raises:
        json.JSONDecodeError: when content is not valid JSON.
        ValidationError: when the parsed payload is not a dict.
    """
    s = (text or "").strip()
    # Strip a leading ```json (or ```) fence
    s = re.sub(r"<think>.*?</think>\n\n", "", s, flags=re.IGNORECASE | re.DOTALL)
    if s.startswith("```"):
        # drop opening fence line
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        # drop closing fence
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValidationError(f"LLM response is not a dict: {type(data).__name__}")
    return data


class OpenAICompatClient(LLMClient):
    """Real LLM client — POST {base_url}/chat/completions.

    Requires the optional `[llm]` extra (`pip install -e .[llm]`). Imports
    `httpx` lazily so the rest of the package stays import-clean in CI.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout_seconds: float = 15.0,
        max_tokens: int = 1024,
        extra_headers: Optional[dict[str, str]] = None,
        verify_ssl: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAICompatClient: api_key is required")
        if not model:
            raise ValueError("OpenAICompatClient: model is required")
        self._model = model
        self._api_key = api_key
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._timeout_seconds = float(timeout_seconds)
        self._max_tokens = int(max_tokens)
        self._extra_headers = extra_headers or {}
        self._verify_ssl = verify_ssl
        # httpx is imported lazily; resolved on first call().
        self._client = None  # type: ignore[var-annotated]

    @property
    def model_name(self) -> str:
        return self._model

    def _ensure_client(self):
        if self._client is None:
            try:
                import httpx  # noqa: WPS433 — lazy optional dep
            except ImportError as e:  # pragma: no cover - exercised only at use
                raise OpenAICompatError(
                    "httpx is required for openai_compat provider; "
                    "install with `pip install -e .[llm]`"
                ) from e
            default_headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            # Custom headers from YAML config (e.g. X-Workspace-Id, X-API-Version)
            default_headers.update(self._extra_headers)
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                headers=default_headers,
                trust_env=True,  # 读取 http_proxy/https_proxy/no_proxy
                verify=self._verify_ssl,  # SSL 证书校验(生产内网可关)
            )
        return self._client

    def _call(self, prompt: str, *, temperature: float) -> dict[str, Any]:
        """Single HTTP attempt. Raises OpenAICompatTransientError /
        OpenAICompatValidationError. Never retries internally — caller does.
        """
        import httpx  # noqa: WPS433 — lazy optional dep

        client = self._ensure_client()
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }
        try:
            resp = client.post("/chat/completions", json=body)
        except httpx.TimeoutException as e:
            raise OpenAICompatTransientError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            # Network-level error — retryable.
            raise OpenAICompatTransientError(f"http error: {e}") from e

        # Status classification
        status = resp.status_code
        if status in (408, 429) or status >= 500:
            raise OpenAICompatTransientError(f"status {status}: {resp.text[:200]}")
        if status >= 400:
            raise OpenAICompatValidationError(f"status {status}: {resp.text[:200]}")

        try:
            payload = resp.json()
        except json.JSONDecodeError as e:
            raise OpenAICompatValidationError(f"non-JSON body: {e}") from e

        if not isinstance(payload, dict):
            raise OpenAICompatValidationError(f"unexpected payload type: {type(payload).__name__}")
        return payload

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=0.1, max=1.0),
        retry=retry_if_exception_type(
            (LLMTimeoutError, json.JSONDecodeError, OpenAICompatTransientError)
        ),
        reraise=True,
    )
    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        item_id: str = "",
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            payload = self._call(prompt, temperature=temperature)
        except OpenAICompatTransientError as e:
            self._log_outcome(
                item_id=item_id,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                token_in=None,
                token_out=None,
                outcome="timeout",
                error=str(e),
            )
            raise LLMTimeoutError(str(e)) from e
        except OpenAICompatValidationError as e:
            self._log_outcome(
                item_id=item_id,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                token_in=None,
                token_out=None,
                outcome="validation_error",
                error=str(e),
            )
            raise

        # Parse content from choices[0].message.content
        try:
            choices = payload.get("choices") or []
            content = choices[0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as e:
            self._log_outcome(
                item_id=item_id,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                token_in=(payload.get("usage") or {}).get("prompt_tokens"),
                token_out=(payload.get("usage") or {}).get("completion_tokens"),
                outcome="validation_error",
                error=f"bad choices shape: {e}",
            )
            raise OpenAICompatValidationError(f"bad choices shape: {e}") from e

        try:
            data = _extract_json(content)
        except (json.JSONDecodeError, ValidationError) as e:
            self._log_outcome(
                item_id=item_id,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                token_in=(payload.get("usage") or {}).get("prompt_tokens"),
                token_out=(payload.get("usage") or {}).get("completion_tokens"),
                outcome="validation_error",
                error=str(e),
            )
            raise

        usage = payload.get("usage") or {}
        self._log_outcome(
            item_id=item_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            token_in=usage.get("prompt_tokens"),
            token_out=usage.get("completion_tokens"),
            outcome="success",
            error=None,
        )
        return data

    @staticmethod
    def _log_outcome(
        *,
        item_id: str,
        latency_ms: int,
        token_in: Optional[int],
        token_out: Optional[int],
        outcome: str,
        error: Optional[str],
    ) -> None:
        extra: dict[str, Any] = {
            "stage": "llm",
            "event": "llm_call",
            "item_id": item_id,
            "latency_ms": latency_ms,
            "token_in": token_in,
            "token_out": token_out,
            "outcome": outcome,
        }
        if error is not None:
            extra["error"] = error
        if outcome == "success":
            logger.info("llm_call", extra=extra)
        else:
            logger.warning("llm_call", extra=extra)


# --- factory -------------------------------------------------------------


def build_llm_client(
    *,
    provider: str,
    model: str = "mock-llm",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: float = 15.0,
    max_tokens: int = 1024,
    seed: int = 42,
    extra_headers: Optional[dict[str, str]] = None,
    verify_ssl: bool = True,
) -> LLMClient:
    """Construct an :class:`LLMClient` based on `provider`.

    Args:
        provider: ``"mock"`` (default) or ``"openai_compat"``.
        model: model identifier, e.g. ``"claude-haiku-4-5"`` (openai_compat).
        api_key: bearer token (openai_compat); required when provider != "mock".
        base_url: API root URL; defaults to OpenAI public endpoint.
        timeout_seconds: per-request timeout.
        max_tokens: response token cap.
        seed: deterministic seed (used by MockLLMClient only).
    """
    if provider == "mock":
        return MockLLMClient(seed=seed)
    if provider == "openai_compat":
        if not api_key:
            raise ValueError(
                "openai_compat provider requires api_key "
                "(set via --api-key, $OPENAI_API_KEY, or yaml api_key_env)"
            )
        return OpenAICompatClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            extra_headers=extra_headers,
            verify_ssl=verify_ssl,
        )
    raise ValueError(f"unknown provider: {provider!r} (expected 'mock' or 'openai_compat')")


# --- thin helpers ---------------------------------------------------------


def validate_complete_response(payload: Any) -> dict[str, Any]:
    """Ensure payload is a dict (catches LLM returning a list / scalar)."""
    if not isinstance(payload, dict):
        raise ValidationError(f"LLM response is not a dict: {type(payload).__name__}")
    return payload


__all__ = [
    "LLMClient",
    "LLMTimeoutError",
    "MockLLMClient",
    "OpenAICompatClient",
    "OpenAICompatError",
    "OpenAICompatTransientError",
    "OpenAICompatValidationError",
    "build_llm_client",
    "validate_complete_response",
]
