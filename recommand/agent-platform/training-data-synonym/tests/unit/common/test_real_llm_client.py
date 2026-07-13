"""Unit tests for OpenAICompatClient + build_llm_client factory.

Skipped automatically when `httpx` is not installed (i.e. `pip install -e .[llm]`
was not run). All HTTP traffic is mocked via `httpx.MockTransport` so no
real API calls occur.
"""

from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")  # skip entire module when [llm] extra absent

from training_data.common import llm_client as llm_module
from training_data.common.exceptions import ValidationError
from training_data.common.llm_client import (
    LLMTimeoutError,
    MockLLMClient,
    OpenAICompatClient,
    OpenAICompatError,
    OpenAICompatValidationError,
    build_llm_client,
    _extract_json,
)


# --- helpers --------------------------------------------------------------


def _make_transport(handler):
    """Build an httpx.Client wired to a mock handler."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://api.test/v1",
        headers={"Authorization": "Bearer test-key"},
    )


def _ok_payload(content: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "claude-haiku-4-5",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


# --- _extract_json --------------------------------------------------------


class TestExtractJson:
    def test_plain_dict(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_strips_json_fence(self):
        text = '```json\n{"a": 1}\n```'
        assert _extract_json(text) == {"a": 1}

    def test_strips_plain_fence(self):
        text = '```\n{"a": 1}\n```'
        assert _extract_json(text) == {"a": 1}

    def test_non_dict_raises_validation_error(self):
        with pytest.raises(ValidationError):
            _extract_json("[1, 2, 3]")

    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("{not valid")


# --- build_llm_client factory --------------------------------------------


class TestBuildFactory:
    def test_mock_provider(self):
        client = build_llm_client(provider="mock", seed=7)
        assert isinstance(client, MockLLMClient)
        assert client.model_name == "mock-llm"

    def test_openai_compat_requires_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            build_llm_client(provider="openai_compat", model="claude-haiku-4-5")

    def test_openai_compat_returns_client(self):
        client = build_llm_client(
            provider="openai_compat", model="claude-haiku-4-5", api_key="sk-test"
        )
        assert isinstance(client, OpenAICompatClient)
        assert client.model_name == "claude-haiku-4-5"

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown provider"):
            build_llm_client(provider="bogus")


# --- OpenAICompatClient ----------------------------------------------------


class TestOpenAICompatClient:
    def test_model_name(self):
        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        assert c.model_name == "claude-haiku-4-5"

    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key"):
            OpenAICompatClient(model="claude-haiku-4-5", api_key="")

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="model"):
            OpenAICompatClient(model="", api_key="sk-test")

    def test_success_path(self):
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            assert request.url.path == "/v1/chat/completions"
            assert json.loads(request.content)["messages"][0]["content"] == "hello"
            return httpx.Response(200, json=_ok_payload('{"category": "咖啡"}'))

        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        out = c.complete("hello", temperature=0.3, item_id="mt-1")
        assert out == {"category": "咖啡"}
        assert calls["count"] == 1

    def test_json_fence_in_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_ok_payload('```json\n{"category": "咖啡"}\n```'),
            )

        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        out = c.complete("hi", item_id="x")
        assert out == {"category": "咖啡"}

    def test_5xx_retries_then_succeeds(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 2:
                return httpx.Response(503, text="upstream busy")
            return httpx.Response(200, json=_ok_payload('{"a": 1}'))

        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        out = c.complete("hi", item_id="x")
        assert out == {"a": 1}
        assert attempts["n"] == 2  # 1 retry

    def test_persistent_5xx_raises_llm_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        with pytest.raises(LLMTimeoutError):
            c.complete("hi", item_id="x")

    def test_4xx_raises_validation_error_no_retry(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(401, text="bad key")

        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        with pytest.raises(OpenAICompatValidationError):
            c.complete("hi", item_id="x")
        assert attempts["n"] == 1  # 4xx does NOT retry

    def test_non_dict_response_raises_validation_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[1, 2, 3])

        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        with pytest.raises(OpenAICompatValidationError):
            c.complete("hi", item_id="x")

    def test_t097_log_emitted_with_token_accounting(self, caplog):
        import logging

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_payload('{"a": 1}', 12, 7))

        caplog.set_level(logging.INFO, logger="training_data.common.llm_client")
        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        c.complete("hi", item_id="mt-42")

        # Find the llm_call record
        llm_records = [r for r in caplog.records if r.getMessage() == "llm_call"]
        assert len(llm_records) == 1
        rec = llm_records[0]
        # T097 contract: item_id, latency_ms, token_in, token_out, outcome
        assert getattr(rec, "item_id", None) == "mt-42"
        assert getattr(rec, "token_in", None) == 12
        assert getattr(rec, "token_out", None) == 7
        assert getattr(rec, "outcome", None) == "success"
        assert getattr(rec, "latency_ms", -1) >= 0

    def test_t097_log_on_failure(self, caplog):
        import logging

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        caplog.set_level(logging.WARNING, logger="training_data.common.llm_client")
        c = OpenAICompatClient(model="claude-haiku-4-5", api_key="sk-test")
        c._client = _make_transport(handler)
        with pytest.raises(LLMTimeoutError):
            c.complete("hi", item_id="mt-fail")

        llm_records = [r for r in caplog.records if r.getMessage() == "llm_call"]
        # Tenacity retries 3x → one log per attempt
        assert len(llm_records) == 3
        for rec in llm_records:
            assert rec.outcome == "timeout"
            assert rec.item_id == "mt-fail"

    def test_module_lazy_loads_httpx(self):
        """Verify httpx is NOT imported at module top-level — only on first call."""
        # If `import httpx` had been hoisted to module-level, this attribute
        # would already exist before any client is constructed. The lazy
        # import path means `httpx` is only resolved inside `_ensure_client`.
        # We assert the module-level attribute is absent.
        assert not hasattr(llm_module, "httpx"), (
            "httpx should be lazy-imported inside _ensure_client, not at module top-level"
        )
